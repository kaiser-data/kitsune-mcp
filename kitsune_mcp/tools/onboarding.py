"""Onboarding tools: skill, key, auto, setup."""

import asyncio
import contextlib
import ipaddress
import json
import re
from datetime import datetime
from urllib.parse import urlparse

import httpx

from kitsune_mcp.app import mcp
from kitsune_mcp.constants import (
    TIMEOUT_FETCH_URL,
    TIMEOUT_STDIO_INIT,
)
from kitsune_mcp.credentials import (
    _registry_headers,
    _save_to_env,
    _to_env_var,
)
from kitsune_mcp.probe import _format_setup_guide
from kitsune_mcp.registry import REGISTRY_BASE
from kitsune_mcp.session import _save_skills, session
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import BaseTransport
from kitsune_mcp.utils import _get_http_client


def _is_safe_url(url: str) -> bool:
    """Return True only for public HTTPS URLs — blocks SSRF to private/loopback addresses."""
    try:
        p = urlparse(url)
        if p.scheme != "https":
            return False
        host = p.hostname or ""
        if not host or host == "localhost":
            return False
        try:
            addr = ipaddress.ip_address(host)
            return addr.is_global
        except ValueError:
            pass  # hostname, not a bare IP — allow it
        return True
    except Exception:
        return False


@mcp.tool()
async def skill(qualified_name: str, forget: bool = False) -> str:
    """Load a Smithery skill into context. forget=True removes it."""
    # --- forget / uninstall ---
    if forget:
        if qualified_name in session["skills"]:
            name = session["skills"][qualified_name].get("name", qualified_name)
            del session["skills"][qualified_name]
            _save_skills()
            return f"Skill removed: {name} ({qualified_name})"
        return f"Skill '{qualified_name}' is not installed."

    # --- serve from cache if already loaded ---
    cached = session["skills"].get(qualified_name)
    if cached and cached.get("content"):
        content = cached["content"]
        skill_name = cached.get("name", qualified_name)
        token_estimate = cached.get("tokens", len(content) // 4)
        lines = [
            f"Skill injected (cached): {skill_name} ({qualified_name})",
            f"Context cost: ~{token_estimate:,} tokens",
            "", "--- SKILL CONTENT ---", "", content,
        ]
        return "\n".join(lines)

    # --- fetch from Smithery API ---
    if not _state._smithery_available():
        return "No SMITHERY_API_KEY set. Run: key('SMITHERY_API_KEY', 'your-key')"

    try:
        r = await _get_http_client().get(
            f"{REGISTRY_BASE}/skills/{qualified_name}",
            headers=_registry_headers(),
            timeout=TIMEOUT_FETCH_URL,
        )
        r.raise_for_status()
        skill_meta = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Skill '{qualified_name}' not found."
        return f"Registry error: {e.response.status_code}"
    except Exception as e:
        return f"Failed to fetch skill: {e}"

    skill_name = skill_meta.get("name") or skill_meta.get("displayName") or qualified_name
    skill_desc = (skill_meta.get("description") or "").strip()

    content = None
    content_url = (skill_meta.get("contentUrl") or skill_meta.get("url")
                   or skill_meta.get("content_url"))
    if content_url and _is_safe_url(content_url):
        try:
            rc = await _get_http_client().get(content_url, timeout=TIMEOUT_FETCH_URL)
            rc.raise_for_status()
            content = rc.text
        except Exception:
            content = None

    if not content:
        content = (skill_meta.get("content") or skill_meta.get("markdown")
                   or skill_meta.get("text"))

    if not content:
        return "\n".join([
            f"Skill: {skill_name} ({qualified_name})",
            f"Description: {skill_desc}" if skill_desc else "",
            "Warning: could not fetch skill content.",
            json.dumps(skill_meta, indent=2),
        ])

    token_estimate = len(content) // 4
    session["skills"][qualified_name] = {
        "name": skill_name,
        "content": content,
        "tokens": token_estimate,
        "installed_at": datetime.utcnow().isoformat(),
    }
    _save_skills()

    lines = [
        f"Skill injected: {skill_name} ({qualified_name})",
        f"Context cost: ~{token_estimate:,} tokens",
    ]
    if skill_desc:
        lines.append(f"Description: {skill_desc}")
    lines += ["", "--- SKILL CONTENT ---", "", content]
    return "\n".join(lines)


@mcp.tool()
async def key(env_var: str, value: str) -> str:
    """Save an API key to .env for persistent use. e.g. key('EXA_API_KEY', 'sk-...')"""
    var = env_var.upper().replace(" ", "_")
    _save_to_env(var, value)
    _state._registry.bust_cache()  # credentials changed — invalidate cached server records
    return f"Saved: {var} written to .env and active for this session."


@mcp.tool()
async def auto(
    task: str,
    tool_name: str = "",
    arguments: dict | None = None,
    server_hint: str = "",
    keys: dict | None = None,
) -> str:
    """Search → pick best server → call tool in one step."""
    if arguments is None:
        arguments = {}
    if keys is None:
        keys = {}
    for env_var, value in keys.items():
        _save_to_env(env_var.upper(), str(value))

    if server_hint:
        srv = await _state._registry.get_server(server_hint)
        if srv:
            server_id, server_name, credentials = srv.id, srv.name, srv.credentials
        else:
            server_id, server_name, credentials = server_hint, server_hint, {}
    else:
        servers = await _state._registry.search(task, limit=3)
        if not servers:
            return f"No servers found for '{task}'. Use search() or provide server_hint."
        best = servers[0]
        server_id, server_name, credentials = best.id, best.name, best.credentials
        session["explored"][server_id] = {
            "name": server_name, "desc": best.description, "status": "harvested"
        }

    resolved_config, missing = _state._resolve_config(credentials, {})
    if missing:
        missing_vars = {_to_env_var(k): v for k, v in missing.items()}
        lines = [f"Server '{server_id}' needs keys:", ""]
        for ev, desc in missing_vars.items():
            lines.append(f"  {ev}" + (f": {desc[:60]}" if desc else ""))
        args_repr = json.dumps(arguments) if arguments else "{}"
        lines += [
            "",
            "Retry:",
            f'  auto("{task}", "{tool_name}", {args_repr},',
            f'    server_hint="{server_id}",',
            '    keys={' + ", ".join(f'"{k}": "val"' for k in missing_vars) + '})',
        ]
        return "\n".join(lines)

    if not tool_name:
        srv = await _state._registry.get_server(server_id)
        tools = (srv.tools if srv else []) or []

        # For stdio servers with no registry tools, fetch live schemas
        if not tools and srv and srv.transport == "stdio":
            cmd = srv.install_cmd or ["npx", "-y", server_id]
            with contextlib.suppress(Exception):
                tools = await asyncio.wait_for(
                    _state.PersistentStdioTransport(cmd).list_tools(), timeout=TIMEOUT_STDIO_INIT
                )

        if not tools:
            return f"{server_id} ready (no tools listed). Use call() to call tools directly."

        # Auto-select: only one tool → use it; multiple → pick best match for task
        if len(tools) == 1:
            tool_name = tools[0]["name"]
        else:
            task_lc = task.lower()
            task_words = set(re.split(r'\W+', task_lc))

            def _tool_score(t: dict) -> float:
                n = (t.get("name") or "").lower()
                d = (t.get("description") or "").lower()
                score = 0.0
                if task_lc in n:
                    score += 10.0
                score += sum(2.0 for w in task_words if w and w in n)
                score += sum(1.0 for w in task_words if w and w in d)
                return score

            scored = sorted(tools, key=_tool_score, reverse=True)
            best_score = _tool_score(scored[0])
            if best_score > 0:
                tool_name = scored[0]["name"]
            else:
                # No match — list tools and ask user to pick
                tool_lines = [f"  {t['name']} — {(t.get('description') or '')[:80]}" for t in tools]
                return "\n".join([
                    f"{server_name} ({server_id}) ready. Available tools:",
                    "",
                    *tool_lines,
                    "",
                    f'Call: auto("{task}", "<tool>", args, server_hint="{server_id}")',
                ])

    srv = await _state._registry.get_server(server_id)
    transport: BaseTransport = _state._get_transport(server_id, srv)
    result = await transport.execute(tool_name, arguments, resolved_config)

    _state._track_call(server_id, tool_name)
    return result


@mcp.tool()
async def setup(name: str) -> str:
    """Setup wizard for a connected server. Call repeatedly until all requirements are met."""
    conn = next((c for c in session["connections"].values() if c.get("name") == name), None)
    if conn is None:
        connected = [c.get("name", "?") for c in session["connections"].values()]
        if connected:
            return f"No connection named '{name}'. Connected: {', '.join(connected)}"
        return f"No connection named '{name}'. Use connect() first."

    install_cmd = conn["command"].split()
    transport = _state.PersistentStdioTransport(install_cmd)
    tools = await transport.list_tools()

    resource_text = await _state._fetch_resource_docs(transport)
    reqs = _state._probe_requirements(tools, resource_text)
    guide = _format_setup_guide(reqs, name, tools=tools)

    lines = [f"Setup: {name}"]

    if reqs["needs_oauth"]:
        lines.append("⚠️  OAuth flow detected — browser authentication may be required.")

    if reqs["schema_creds"]:
        schema_missing = [c for c in reqs["schema_creds"] if c not in reqs["set_env"]]
        if schema_missing:
            lines.append(f"Required credentials (from schema): {', '.join(schema_missing)}")

    if not guide:
        lines.append("✅ All requirements satisfied — ready to call tools.")
        if tools:
            lines.append(f"\nAvailable tools ({len(tools)}): {', '.join(t.get('name', '?') for t in tools)}")
        return "\n".join(lines)

    lines.append(guide)

    if not reqs["resource_scan"]:
        lines.append("\n(No resource docs found — probe based on tool schemas only.)")

    return "\n".join(lines)
