import asyncio
import os
import re
import json
import base64
from datetime import datetime
import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("smithery-lattice")

SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY")
REGISTRY_BASE = "https://registry.smithery.ai"
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

# Session state
session = {
    "explored": {},   # qualifiedName -> {displayName, description, status}
    "skills": {},     # qualifiedName -> {content, tokens, installed_at}
    "grown": {},      # qualifiedName -> {tools, credentials, status}
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def registry_headers():
    return {
        "Authorization": f"Bearer {SMITHERY_API_KEY}",
        "Accept": "application/json",
    }


def _check_api_key() -> str | None:
    if not SMITHERY_API_KEY:
        return "🔷 No API key found — set SMITHERY_API_KEY environment variable to feed the network."
    return None


def _to_env_var(key: str) -> str:
    """Convert camelCase credential key to UPPER_SNAKE_CASE env var name.

    exaApiKey -> EXA_API_KEY
    githubPersonalAccessToken -> GITHUB_PERSONAL_ACCESS_TOKEN
    """
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', key)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    return s.upper()


def _save_to_env(env_var: str, value: str) -> None:
    """Persist a key to .env and set it in the current process."""
    try:
        try:
            with open(ENV_PATH, 'r') as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []

        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={value}\n"
                found = True
                break
        if not found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"{env_var}={value}\n")

        with open(ENV_PATH, 'w') as f:
            f.writelines(lines)
    except OSError:
        pass  # Non-fatal — key still works in-memory for this session

    os.environ[env_var] = value


def _resolve_config(credentials: dict[str, str], user_config: dict) -> tuple[dict, dict]:
    """Merge user_config with env-var auto-loading for missing credentials.

    Returns (resolved_config, missing_credentials).
    """
    resolved = dict(user_config)
    for key in credentials:
        if not resolved.get(key):
            val = os.getenv(_to_env_var(key))
            if val:
                resolved[key] = val
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    return resolved, missing


def _extract_credentials(connections: list) -> list[str]:
    if not connections:
        return []
    for conn in connections:
        props = conn.get("configSchema", {}).get("properties", {})
        if props:
            return list(props.keys())
    return []


async def _fetch_credentials(qualified_name: str) -> dict[str, str]:
    """Return {field: description} for all credentials a server requires."""
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{REGISTRY_BASE}/servers/{qualified_name}",
                headers=registry_headers(),
                timeout=10.0,
            )
            r.raise_for_status()
            server = r.json()
    except Exception:
        return {}
    result = {}
    for conn in server.get("connections", []):
        props = conn.get("configSchema", {}).get("properties", {})
        for key, val in props.items():
            result[key] = val.get("description", "")
    return result


def _credentials_guide(qualified_name: str, credentials: dict[str, str], resolved: dict) -> str:
    """Return a human-readable guide for missing credentials."""
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    if not missing:
        return ""
    example = {k: f"YOUR_{_to_env_var(k)}" for k in credentials}
    first_var = _to_env_var(next(iter(missing)))
    lines = [
        "🔷 This node needs keys before it can join the lattice.",
        "",
        f"SERVER: {qualified_name}",
        "",
        "MISSING KEYS",
    ]
    for key, desc in missing.items():
        lines.append(f"• {key}  →  env: {_to_env_var(key)}")
        if desc:
            lines.append(f"  {desc}")
    lines += [
        "",
        "Option 1 — Save permanently (auto-used in all future calls):",
        f'  set_key("{first_var}", "your-value")',
        "",
        "Option 2 — Pass inline via grow():",
        f'  grow("{qualified_name}", "<tool>", {{...}}, {json.dumps(example)})',
        "",
        "Option 3 — Pass inline via harvest() with one-shot save:",
        f'  harvest("<task>", "<tool>", {{...}}, server_hint="{qualified_name}",',
        '          keys={' + ", ".join(f'"{_to_env_var(k)}": "your-value"' for k in missing) + '})',
    ]
    return "\n".join(lines)


def _estimate_tokens(tools: list) -> int:
    return sum(len(json.dumps(t)) for t in tools) // 4


# ---------------------------------------------------------------------------
# Shared HTTP+SSE executor
# ---------------------------------------------------------------------------

async def _execute_tool_call(
    qualified_name: str,
    tool_name: str,
    arguments: dict,
    config: dict,
) -> str:
    """Execute a tool call on a remote Smithery server via HTTP+SSE.

    Returns result text on success, or an error string starting with 🔷.
    """
    key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    config_b64 = base64.urlsafe_b64encode(
        json.dumps(config).encode()
    ).decode().rstrip("=")
    base_url = (
        f"https://server.smithery.ai/{qualified_name}"
        f"?config={config_b64}&api_key={key}"
    )
    import pathlib
    pathlib.Path("/tmp/lattice_debug.txt").write_text(
        f"qualified_name={qualified_name}\n"
        f"tool_name={tool_name}\n"
        f"module_key={SMITHERY_API_KEY!r}\n"
        f"runtime_key={key!r}\n"
        f"url={base_url}\n"
    )
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def _parse_sse(text: str) -> dict | None:
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    return json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    pass
        return None

    async def _post(client, payload, session_id=None):
        hdrs = dict(headers)
        if session_id:
            hdrs["mcp-session-id"] = session_id
        return await client.post(base_url, content=json.dumps(payload), headers=hdrs, timeout=30.0)

    async def _run():
        async with httpx.AsyncClient() as client:
            r = await _post(client, {
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "smithery-lattice", "version": "1.0.0"},
                },
            })
            if r.status_code in (401, 403):
                import pathlib
                pathlib.Path("/tmp/lattice_debug.txt").write_text(
                    f"status={r.status_code}\n"
                    f"key_used={key!r}\n"
                    f"url={base_url[:200]}\n"
                    f"body={r.text[:500]}\n"
                )
                raise PermissionError(f"HTTP {r.status_code}")
            r.raise_for_status()

            session_id = r.headers.get("mcp-session-id")
            init_msg = _parse_sse(r.text)
            if init_msg and "error" in init_msg:
                raise RuntimeError(f"Initialize failed: {init_msg['error']}")

            await _post(client, {
                "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
            }, session_id)

            r2 = await _post(client, {
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }, session_id)
            r2.raise_for_status()

            msg = _parse_sse(r2.text)
            if msg is None:
                raise RuntimeError(f"Empty response: {r2.text[:200]}")
            return msg

    try:
        response = await asyncio.wait_for(_run(), timeout=30.0)
    except asyncio.TimeoutError:
        return (
            f"🔷 The connection to {qualified_name} went silent. "
            "The server may be sleeping. Try again or use a different server."
        )
    except PermissionError:
        credentials = await _fetch_credentials(qualified_name)
        if credentials:
            resolved, missing = _resolve_config(credentials, config)
            if missing:
                return _credentials_guide(qualified_name, credentials, resolved)
        return (
            f"🔷 Authentication failed connecting to {qualified_name}. "
            "Check your Smithery API key at smithery.ai/account/api-keys"
        )
    except Exception as e:
        return f"🔷 Failed to connect to {qualified_name}: {e}"

    if "error" in response:
        err_obj = response["error"]
        return (
            f"🔷 {qualified_name} returned an error from tool '{tool_name}':\n"
            f"{err_obj.get('message', json.dumps(err_obj))}"
        )

    result = response.get("result", {})
    content = result.get("content", [])
    if content:
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(text_parts) if text_parts else json.dumps(content, indent=2)
    return json.dumps(result, indent=2)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def explore(query: str, limit: int = 5) -> str:
    """Search the Smithery MCP registry for servers matching your intent.

    Scans the Smithery lattice for verified MCP servers relevant to your query.
    Returns server names, descriptions, and credential requirements.
    """
    err = _check_api_key()
    if err:
        return err

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{REGISTRY_BASE}/servers",
                params={"q": f"{query} is:verified", "pageSize": limit},
                headers=registry_headers(),
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return "🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key."
        return f"🔷 Smithery Lattice couldn't reach Smithery registry. Status {e.response.status_code}."
    except Exception:
        return "🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key or network."

    servers = data.get("servers", [])
    if not servers:
        return f"🔷 No nodes found matching '{query}' in the lattice. Try a broader query."

    lines = [f"🔷 LATTICE SCAN — '{query}' ({len(servers)} nodes found)\n"]

    for s in servers:
        qname = s.get("qualifiedName", "unknown")
        display = s.get("displayName") or qname
        description = s.get("description", "No description").strip()
        remote = s.get("remote", False)
        scan_passed = (s.get("security") or {}).get("scanPassed", False)
        tool_count = len(s.get("tools") or []) or "?"
        credentials = _extract_credentials(s.get("connections", []))
        cred_str = ", ".join(credentials) if credentials else "none required"

        lines.append(f"🔹 {qname}")
        lines.append(f"   {display} — {description}")
        lines.append(f"   Remote: {'✓' if remote else '✗'}  |  Security scan: {'✓' if scan_passed else '—'}  |  Tools: {tool_count}")
        lines.append(f"   Needs: {cred_str}")
        lines.append("")

        session["explored"][qname] = {
            "displayName": display,
            "description": description,
            "status": "explored",
        }

    lines.append("Use inspect('<qualifiedName>') to see full tool details.")
    return "\n".join(lines)


@mcp.tool()
async def inspect(qualified_name: str) -> str:
    """Inspect a specific Smithery MCP server — tools, credentials needed, token cost.

    Reveals the full node blueprint: what it can do, what keys it needs to join the lattice,
    and how much context pressure it will add.
    """
    err = _check_api_key()
    if err:
        return err

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{REGISTRY_BASE}/servers/{qualified_name}",
                headers=registry_headers(),
                timeout=15.0,
            )
            r.raise_for_status()
            server = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"🔷 No server found for '{qualified_name}'. Try explore() to find the right qualified name."
        if e.response.status_code == 401:
            return "🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key."
        return f"🔷 Smithery Lattice couldn't reach Smithery registry. Status {e.response.status_code}."
    except Exception:
        return "🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key or network."

    qname = server.get("qualifiedName", qualified_name)
    display = server.get("displayName") or qname
    description = server.get("description", "No description").strip()
    remote = server.get("remote", False)
    scan_passed = (server.get("security") or {}).get("scanPassed", False)
    connections = server.get("connections", [])
    tools_list = server.get("tools") or []

    credentials_raw = {}
    for conn in connections:
        for key, val in conn.get("configSchema", {}).get("properties", {}).items():
            credentials_raw[key] = val.get("description", "No description")

    token_estimate = _estimate_tokens(tools_list)

    lines = [
        f"🔷 {display} ({qname})",
        "",
        "DESCRIPTION",
        description,
        "",
        "CONNECTION",
        f"Type: {'Remote (hosted on Smithery)' if remote else 'Local (stdio)'}",
        f"Security scan: {'PASSED ✓' if scan_passed else 'NOT SCANNED —'}",
        "",
    ]

    if credentials_raw:
        lines.append("KEYS REQUIRED")
        for key, desc in credentials_raw.items():
            lines.append(f"• {key}  →  env: {_to_env_var(key)}")
            lines.append(f"  {desc}")
        lines.append("")
    else:
        lines += ["KEYS REQUIRED", "• None — this node joins the lattice freely", ""]

    if tools_list:
        lines.append(f"TOOLS ({len(tools_list)})")
        for tool in tools_list:
            tname = tool.get("name", "unnamed")
            tdesc = tool.get("description", "No description").strip()
            params = list((tool.get("inputSchema") or {}).get("properties", {}).keys())
            param_str = f"({', '.join(params)})" if params else ""
            lines.append(f"• {tname}{param_str} — {tdesc}")
        lines.append("")
    else:
        lines += ["TOOLS", "• No tools listed in registry", ""]

    lines.append("CONTEXT COST (estimated)")
    lines.append(f"Tool schemas: ~{token_estimate:,} tokens")
    lines.append("")

    if credentials_raw:
        lines.append(f"To grow this node: set keys via set_key(), then call grow() or harvest()")
    else:
        lines.append("To grow this node: call grow() or harvest() — no keys required")

    session["explored"][qname] = {
        "displayName": display,
        "description": description,
        "status": "inspected",
    }

    return "\n".join(lines)


@mcp.tool()
async def inoculate_skill(qualified_name: str) -> str:
    """Fetch and inject a Smithery skill into your context — changes how Claude thinks.

    Weaves a skill document into the lattice. Claude automatically incorporates it,
    augmenting its reasoning for the skill's domain.
    """
    err = _check_api_key()
    if err:
        return err

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{REGISTRY_BASE}/skills/{qualified_name}",
                headers=registry_headers(),
                timeout=15.0,
            )
            r.raise_for_status()
            skill_meta = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"🔷 No skill found for '{qualified_name}'. Check the qualified name."
        if e.response.status_code == 401:
            return "🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key."
        return f"🔷 Smithery Lattice couldn't reach Smithery registry. Status {e.response.status_code}."
    except Exception:
        return "🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key or network."

    skill_name = skill_meta.get("name") or skill_meta.get("displayName") or qualified_name
    skill_desc = skill_meta.get("description", "").strip()

    content = None
    content_url = skill_meta.get("contentUrl") or skill_meta.get("url") or skill_meta.get("content_url")
    if content_url:
        try:
            async with httpx.AsyncClient() as client:
                rc = await client.get(content_url, timeout=15.0)
                rc.raise_for_status()
                content = rc.text
        except Exception:
            content = None

    if not content:
        content = skill_meta.get("content") or skill_meta.get("markdown") or skill_meta.get("text")

    if not content:
        token_estimate = len(json.dumps(skill_meta)) // 4
        lines = [
            f"🔷 Skill woven into the lattice: {skill_name} ({qualified_name})",
            f"Description: {skill_desc}" if skill_desc else "",
            f"Estimated tokens: ~{token_estimate}",
            "",
            "⚠️  Could not fetch skill content document. Metadata only:",
            "",
            json.dumps(skill_meta, indent=2),
        ]
        return "\n".join(l for l in lines if l is not None)

    token_estimate = len(content) // 4

    session["skills"][qualified_name] = {
        "name": skill_name,
        "content": content,
        "tokens": token_estimate,
        "installed_at": datetime.utcnow().isoformat(),
    }

    lines = [
        f"🔷 Skill woven into the lattice: {skill_name} ({qualified_name})",
        f"Description: {skill_desc}" if skill_desc else None,
        f"Context cost: ~{token_estimate:,} tokens",
        "",
        "--- SKILL CONTENT (now active in your context) ---",
        "",
        content,
    ]
    return "\n".join(l for l in lines if l is not None)


@mcp.tool()
async def set_key(env_var: str, value: str) -> str:
    """Save an API key to .env for persistent use across sessions.

    Persists the key so it's automatically used whenever a server needs it —
    no need to pass config manually in grow() or harvest() calls.

    The key is matched to server credentials by converting camelCase schema names
    to UPPER_SNAKE_CASE (e.g. exaApiKey -> EXA_API_KEY).

    Example: set_key("EXA_API_KEY", "your-key-here")
    """
    var = env_var.upper().replace(" ", "_")
    _save_to_env(var, value)
    return f"🔷 Key saved: {var} written to .env and active for this session."


@mcp.tool()
async def grow(
    qualified_name: str,
    tool_name: str,
    arguments: dict = {},
    config: dict = {},
) -> str:
    """Call a tool on a remote Smithery-hosted MCP server via WebSocket.

    Routes a tool call through the lattice to a live Smithery server.
    Credentials are auto-loaded from .env if available — use set_key() to persist them.
    """
    err = _check_api_key()
    if err:
        return err

    credentials = await _fetch_credentials(qualified_name)
    resolved_config, missing = _resolve_config(credentials, config)

    if missing:
        return _credentials_guide(qualified_name, credentials, resolved_config)

    result_text = await _execute_tool_call(qualified_name, tool_name, arguments, resolved_config)

    prior = session["grown"].get(qualified_name, {"calls": 0})
    session["grown"][qualified_name] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    calls = session["grown"][qualified_name]["calls"]

    return "\n".join([
        f"🔷 LATTICE RESPONSE — {qualified_name} / {tool_name}",
        "",
        result_text,
        "",
        f"Node active in lattice. ({calls} call(s) total)",
    ])


@mcp.tool()
async def harvest(
    task: str,
    tool_name: str = "",
    arguments: dict = {},
    server_hint: str = "",
    keys: dict = {},
) -> str:
    """Auto-discover, connect, and call the best Smithery server for a task.

    Full pipeline: explore → credential check → call. No manual grow() needed.
    Credentials are auto-loaded from .env; pass `keys` to save new ones in one shot.

    Args:
        task:        What you want to do (used for server discovery)
        tool_name:   Tool to call. If omitted, returns available tools for the best match.
        arguments:   Arguments for the tool call.
        server_hint: Skip discovery — use this qualified name directly.
        keys:        {ENV_VAR: value} pairs to persist to .env and use immediately.
                     Example: {"EXA_API_KEY": "abc123"}
    """
    err = _check_api_key()
    if err:
        return err

    # Persist any provided keys first
    for env_var, value in keys.items():
        _save_to_env(env_var.upper(), str(value))

    # Discover server
    if server_hint:
        qualified_name = server_hint
        display_name = server_hint
    else:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{REGISTRY_BASE}/servers",
                    params={"q": f"{task} is:verified", "pageSize": 3},
                    headers=registry_headers(),
                    timeout=15.0,
                )
                r.raise_for_status()
                servers = r.json().get("servers", [])
        except Exception as e:
            return f"🔷 Could not scan lattice: {e}"

        if not servers:
            return f"🔷 No nodes found for '{task}'. Try explore() or provide server_hint."

        best = servers[0]
        qualified_name = best.get("qualifiedName", "")
        display_name = best.get("displayName") or qualified_name
        if not qualified_name:
            return "🔷 Could not determine server qualified name."

        session["explored"][qualified_name] = {
            "displayName": display_name,
            "description": best.get("description", ""),
            "status": "harvested",
        }

    # Resolve credentials (env auto-load + user-provided keys)
    credentials = await _fetch_credentials(qualified_name)
    resolved_config, missing = _resolve_config(credentials, {})

    if missing:
        missing_vars = {_to_env_var(k): v for k, v in missing.items()}
        args_repr = json.dumps(arguments) if arguments else "{}"
        lines = [
            f"🔷 Node {qualified_name} needs keys to join the lattice.",
            "",
            "MISSING KEYS",
        ]
        for env_var, desc in missing_vars.items():
            lines.append(f"• {env_var}")
            if desc:
                lines.append(f"  {desc}")
        lines += [
            "",
            "Save keys and retry in one call:",
            f'  harvest("{task}", "{tool_name}", {args_repr},',
            f'    server_hint="{qualified_name}",',
            '    keys={' + ", ".join(f'"{k}": "your-value"' for k in missing_vars) + '})',
            "",
            "Or save permanently first:",
            f'  set_key("{next(iter(missing_vars))}", "your-value")',
        ]
        return "\n".join(lines)

    # If no tool specified, return available tools so caller can choose
    if not tool_name:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(
                    f"{REGISTRY_BASE}/servers/{qualified_name}",
                    headers=registry_headers(),
                    timeout=10.0,
                )
                r.raise_for_status()
                server_detail = r.json()
        except Exception:
            server_detail = {}

        tools_list = server_detail.get("tools") or []
        if tools_list:
            tool_lines = [f"• {t['name']} — {t.get('description', '').strip()}" for t in tools_list]
            return "\n".join([
                f"🔷 Node {display_name} ({qualified_name}) is ready.",
                "Credentials resolved. Available tools:",
                "",
                *tool_lines,
                "",
                f'Call: harvest("{task}", tool_name="<name>", arguments={{...}}, server_hint="{qualified_name}")',
            ])
        return (
            f"🔷 Node {qualified_name} is ready but has no tools listed in registry. "
            "Use grow() to call tools directly."
        )

    # Execute
    result_text = await _execute_tool_call(qualified_name, tool_name, arguments, resolved_config)

    prior = session["grown"].get(qualified_name, {"calls": 0})
    session["grown"][qualified_name] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }
    calls = session["grown"][qualified_name]["calls"]

    return "\n".join([
        f"🔷 LATTICE RESPONSE — {qualified_name} / {tool_name}",
        "",
        result_text,
        "",
        f"Node active in lattice. ({calls} call(s) total)",
    ])


@mcp.tool()
async def network_status() -> str:
    """Show the current state of the Smithery Lattice — connected nodes and active skills."""
    explored = session["explored"]
    skills = session["skills"]
    grown = session["grown"]

    lines = ["🔷 SMITHERY LATTICE STATUS", ""]

    if explored:
        lines.append(f"EXPLORED THIS SESSION ({len(explored)})")
        for qname, info in explored.items():
            lines.append(f"• {qname} — {info.get('status', 'explored')}")
        lines.append("")
    else:
        lines += ["EXPLORED THIS SESSION (0)", "• None yet. Use explore() to scan the lattice.", ""]

    if grown:
        lines.append(f"GROWN NODES ({len(grown)})")
        for qname, info in grown.items():
            lines.append(
                f"• {qname} — {info.get('status', 'active')} | "
                f"{info.get('calls', 0)} call(s) | last: {info.get('last_tool', '—')}"
            )
        lines.append("")

    total_tokens = 0
    if skills:
        lines.append(f"ACTIVE SKILLS ({len(skills)})")
        for qname, info in skills.items():
            tokens = info.get("tokens", 0)
            total_tokens += tokens
            lines.append(f"• {qname} — ~{tokens:,} tokens")
        lines.append("")
    else:
        lines += ["ACTIVE SKILLS (0)", "• None. Use inoculate_skill() to augment the lattice.", ""]

    lines.append(f"TOTAL CONTEXT PRESSURE: ~{total_tokens:,} tokens")
    if total_tokens > 8000:
        lines.append("🚨 The lattice is under heavy load.")
    elif total_tokens > 4000:
        lines.append("⚠️  Consider removing unused skills if context grows heavy.")
    else:
        lines.append("✓ Context pressure nominal.")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
