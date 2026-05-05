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
    _smithery_available,
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
    preview = value[:4] + "***" + value[-2:] if len(value) > 6 else "***"
    return f"Saved: {var} = {preview} written to .env (mode 0o600) and active for this session."


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

    # When the caller pins a server, single-shot. Otherwise search and try
    # candidates in order, skipping ones that are unreachable due to missing
    # creds we can't fill. The user asked for "web search" — they don't care
    # which provider answers, only that one of them does.
    candidates: list = []  # list[ServerInfo] from registry, or [] if server_hint path
    if server_hint:
        srv = await _state._registry.get_server(server_hint)
        if srv:
            server_id, server_name, credentials = srv.id, srv.name, srv.credentials
        else:
            server_id, server_name, credentials = server_hint, server_hint, {}
    else:
        candidates = list(await _state._registry.search(task, limit=3))
        if not candidates:
            return f"No servers found for '{task}'. Use search() or provide server_hint."
        # Pick the first candidate whose creds we can satisfy. If none, fall
        # through to the first overall — call() will surface the missing-cred
        # message which the agent can act on.
        chosen = next(
            (s for s in candidates if not _state._resolve_config(s.credentials, {})[1]),
            candidates[0],
        )
        server_id, server_name, credentials = chosen.id, chosen.name, chosen.credentials
        # Remove the chosen one from the fallback queue
        candidates = [s for s in candidates if s.id != chosen.id]
        session["explored"][server_id] = {
            "name": server_name, "desc": chosen.description, "status": "harvested"
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

    selected_tool_schema: dict | None = None
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
            reg_errors = getattr(_state._registry, "last_registry_errors", {})
            lines = [f"{server_id} — could not fetch tool schema."]
            if reg_errors:
                err_summary = ", ".join(f"{n} {e}" for n, e in reg_errors.items())
                lines.append(f"Registry fetch failures: {err_summary}.")
            from kitsune_mcp.credentials import _smithery_available
            if srv and getattr(srv, "source", None) == "smithery" and not _smithery_available():
                lines += [
                    "This server is Smithery-hosted and requires SMITHERY_API_KEY.",
                    "→ key('SMITHERY_API_KEY', 'sm-...') then retry,"
                    " or search() for a free alternative.",
                ]
            else:
                lines.append("Use call() to invoke tools directly if the server is running.")
            return "\n".join(lines)

        # Auto-select: only one tool → use it; multiple → pick best match for task
        if len(tools) == 1:
            tool_name = tools[0]["name"]
            selected_tool_schema = tools[0]
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
                selected_tool_schema = scored[0]
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

    # If caller picked a tool implicitly and supplied no arguments, fill the
    # primary required string param from `task`. Common case: auto("web search")
    # with auto-selected `search(query: string)` — without this, every search
    # tool fails with "query: undefined". Only triggers when arguments is empty
    # AND we have a schema to inspect AND there's exactly one obvious string
    # field to fill.
    if not arguments and selected_tool_schema:
        arguments = _infer_args_from_task(selected_tool_schema, task)

    # Execute with fallback: if the chosen server returns an auth-failure
    # response and the caller didn't pin via server_hint, try the next candidate.
    # Wall-clock cap of 5s per provider is enforced by transport timeouts already.
    attempted: list[tuple[str, str]] = []
    last_result: str = ""
    while True:
        srv = await _state._registry.get_server(server_id)
        transport: BaseTransport = _state._get_transport(server_id, srv)
        last_result = await transport.execute(tool_name, arguments, resolved_config)
        _state._track_call(server_id, tool_name)
        attempted.append((server_id, tool_name))

        # Auth-failure detection — surfaces from the inner server's text response
        # (which arrives via Kitsune's transport.execute as a string body).
        # We only fall back when the caller didn't pin a server AND there are
        # candidates left.
        is_auth_fail = any(
            kw in last_result.lower()
            for kw in ("auth failed", "unauthorized", "401", "403", "invalid token", "smithery_api_key")
        )
        if not is_auth_fail or not candidates:
            break

        # Try the next candidate
        nxt = candidates.pop(0)
        # Skip candidates whose creds we still can't satisfy
        cfg2, missing2 = _state._resolve_config(nxt.credentials, {})
        if missing2:
            continue
        server_id, server_name, credentials = nxt.id, nxt.name, nxt.credentials
        resolved_config = cfg2
        # If a different server is chosen, the previously picked tool_name may
        # not exist there. Reset selection so the loop's tool-pick logic runs
        # again — but that logic is in the section above the loop. Simpler:
        # retry only when the new server has a same-named tool. Otherwise stop
        # and report what we tried.
        new_srv = await _state._registry.get_server(server_id)
        new_tools = (new_srv.tools if new_srv else []) or []
        if not any(t.get("name") == tool_name for t in new_tools):
            # Different schema — append a hint to the failure response
            attempted_str = ", ".join(f"{sid}/{t}" for sid, t in attempted)
            return (
                f"{last_result}\n\n"
                f"⚠️  auto() tried {attempted_str}; remaining candidates have different tool names. "
                f'Retry with: auto("{task}", server_hint="<id>")'
            )

    return last_result


def _infer_args_from_task(tool_schema: dict, task: str) -> dict:
    """When auto() implicit-selects a tool but caller passed no arguments,
    infer the primary string param from `task`. Returns {} if no clear winner.

    Picks the first required string-typed param whose name matches a search-like
    convention (`query`, `q`, `text`, `prompt`, `input`). Strict on purpose —
    we don't fill creative-named params silently; better to surface the
    schema-validation error and let the agent retry with explicit args.
    """
    schema = (tool_schema.get("inputSchema") or {})
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    string_required = [p for p in required if props.get(p, {}).get("type") == "string"]
    if len(string_required) != 1:
        return {}
    common_query_names = ("query", "q", "text", "prompt", "input", "search", "term")
    for pname in common_query_names:
        if pname in required and props.get(pname, {}).get("type") == "string":
            return {pname: task}
    return {string_required[0]: task}


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


# Free-tier servers verified to work without any API key. Curated list — these
# are zero-config wins for new users. Updated when new free servers ship.
_FREE_TIER_SERVERS = [
    ("mcp-server-time", "Time queries + timezone conversions (419 timezones)"),
    ("@modelcontextprotocol/server-memory", "Persistent KG memory across calls"),
    ("mcp-server-fetch", "Fetch web pages, get clean markdown"),
    ("@modelcontextprotocol/server-filesystem", "Read/write local files"),
    ("@upstash/context7-mcp", "Up-to-date library docs (no key needed)"),
]


@mcp.tool()
async def onboard() -> str:
    """First-run wizard — show provider auth state + the fastest path to a working tool call.

    Run once at the start of a new session if `kitsune:status` shows you're
    in base form with nothing explored. Returns provider health + a curated
    list of zero-config servers you can shapeshift into immediately.
    """
    import os
    lines = [
        "🦊  Welcome to Kitsune.",
        "",
        "PROVIDERS",
    ]

    # Active providers — check auth state explicitly
    smithery_ok = _smithery_available()
    lines.append(f"  {'✓' if smithery_ok else '🔑'}  Smithery"
                 f"  {'(SMITHERY_API_KEY set — 3000+ verified servers)' if smithery_ok else '(unconfigured — get a key at smithery.ai/account/api-keys to unlock 3000+ servers)'}")
    lines.append("  ✓  Official MCP Registry  (modelcontextprotocol.io — no key needed)")
    lines.append("  ✓  npm + PyPI  (community servers, no key needed)")
    lines.append("  ✓  Glama  (community directory, no key needed)")
    if os.getenv("KITSUNE_TRUST", "").lower() in ("community", "all", "low"):
        lines.append("  ⚠️  KITSUNE_TRUST=community  (community-source confirmation gate is OFF)")
    lines.append("")

    # Recommended starting point — the free tier
    lines.append("FASTEST PATH TO A WORKING TOOL CALL (no API keys required)")
    for sid, desc in _FREE_TIER_SERVERS:
        lines.append(f"  shapeshift(\"{sid}\")")
        lines.append(f"    → {desc}")
    lines.append("")

    # The "3 step" promise
    lines.append("3-STEP CHECK")
    lines.append("  1. shapeshift(\"mcp-server-time\")")
    lines.append("  2. call(\"get_current_time\", arguments={\"timezone\": \"UTC\"})")
    lines.append("  3. shiftback()")
    lines.append("  → If step 2 returns a timestamp, your install works end-to-end.")
    lines.append("")

    # Optional upgrade
    if not smithery_ok:
        lines.append("UPGRADE PATH")
        lines.append("  Get more servers (incl. GitHub, Notion, Linear, Slack, …):")
        lines.append("    1. Sign up at https://smithery.ai/account/api-keys")
        lines.append("    2. key(\"SMITHERY_API_KEY\", \"sm-...\")")
        lines.append("    3. search(\"<what you need>\")")
    else:
        lines.append("All providers active — explore freely with search() / shapeshift().")

    return "\n".join(lines)
