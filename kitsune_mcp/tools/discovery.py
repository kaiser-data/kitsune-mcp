"""Discovery tools: search, inspect, compare, status."""

import asyncio
import contextlib
import os
import shutil

from kitsune_mcp.app import mcp
from kitsune_mcp.constants import (
    MAX_INSPECT_DESC,
    TIMEOUT_STDIO_INIT,
)
from kitsune_mcp.credentials import (
    _credentials_inspect_block,
    _credentials_ready,
    _to_env_var,
)
from kitsune_mcp.session import session
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import _ping, _process_pool
from kitsune_mcp.utils import _estimate_tokens, _rss_mb


def _kill_probe(pool_key: str) -> None:
    """Kill and evict a probe process immediately after use.

    Probe processes are one-shot (list_tools only) — keeping them alive wastes
    200-300 MB each. We kill synchronously; the OS reclaims the child on next
    event-loop tick.
    """
    entry = _process_pool.pop(pool_key, None)
    if entry is not None:
        with contextlib.suppress(Exception):
            entry.proc.kill()


async def _compare_probe(srv, allow_low_trust: bool) -> dict:
    """Probe one server for compare(). Always best-effort, never raises.

    Returns a dict with: id, name, source, tools, tokens, status, action.
    """
    row = {
        "id": srv.id,
        "name": srv.name,
        "source": srv.source,
        "tools": None,
        "tokens": None,
        "status": "",
        "action": f'shapeshift("{srv.id}")',
    }
    last_err: str | None = None

    # 0. Already-cached schemas in the registry — free, accurate.
    if srv.tools:
        row["tools"] = len(srv.tools)
        row["tokens"] = _estimate_tokens(srv.tools)
        row["status"] = "registry"
        return row

    # 1. Smithery short-circuit — no key, no probe possible.
    if srv.source == "smithery" and not _state._smithery_available():
        row["status"] = "needs SMITHERY_API_KEY"
        row["action"] = 'auth("SMITHERY_API_KEY", "...") then compare(...)'
    # 2. Any other HTTP transport — let _get_transport pick direct-OAuth vs Smithery.
    elif srv.transport == "http":
        try:
            transport = _state._get_transport(srv.id, srv)
            tools = await asyncio.wait_for(
                transport.list_tools(), timeout=TIMEOUT_STDIO_INIT
            )
            if tools:
                row["tools"] = len(tools)
                row["tokens"] = _estimate_tokens(tools)
                if srv.url and ".run.tools" in srv.url:
                    row["status"] = "live (smithery)"
                else:
                    row["status"] = "live (oauth)"
                return row
            # Empty tools list without exception — endpoint reachable but auth
            # or config issue we can't diagnose from here.
            if srv.source == "smithery":
                row["status"] = "reachable — no tools returned (check account)"
                row["action"] = f'inspect("{srv.id}")  # diagnose smithery setup'
            else:
                row["status"] = "HTTP-only (no tools via probe)"
                row["action"] = f'inspect("{srv.id}")  # diagnose'
        except Exception as e:
            last_err = _state._humanize_probe_error(str(e))
            row["status"] = f"unreachable: {last_err}"
            row["action"] = f'inspect("{srv.id}")  # see full error'

    # 3. Stdio probe via install_cmd — gated by trust unless overridden.
    if srv.install_cmd and not row["status"]:
        allow_probe, gate_reason = _state._probe_trust_ok(srv)
        if allow_probe or allow_low_trust:
            try:
                _probe_transport = _state.PersistentStdioTransport(
                    srv.install_cmd, probe_env=_state._probe_env(srv)
                )
                tools = await asyncio.wait_for(
                    _probe_transport.list_tools(),
                    timeout=TIMEOUT_STDIO_INIT,
                )
                _kill_probe(_probe_transport._pool_key)
                if tools:
                    row["tools"] = len(tools)
                    row["tokens"] = _estimate_tokens(tools)
                    row["status"] = "live"
                    return row
            except Exception as e:
                last_err = _state._humanize_probe_error(str(e))
            # Probe ran but yielded no tools — diagnose. Strict cred check
            # because the registry already curated which creds are required.
            missing = _state._compare_missing_creds(srv)
            if missing:
                first = missing[0]
                row["status"] = f"needs {first}"
                row["action"] = f'auth("{first}", "...") then compare(...)'
            elif last_err:
                row["status"] = f"failed: {last_err}"
                row["action"] = f'inspect("{srv.id}", probe=True)  # see full error'
            else:
                row["status"] = "probe failed (no tools)"
                row["action"] = f'inspect("{srv.id}", probe=True)'
        else:
            row["status"] = "gated"
            row["action"] = f'inspect("{srv.id}", probe=True)  # {gate_reason}'

    # 4. Fallback estimate from description hint or known tool count.
    if row["tokens"] is None:
        ntools = row["tools"] or _state._tool_count_hint(srv.description)
        if ntools:
            row["tools"] = ntools
            row["tokens"] = ntools * _state._AVG_TOKENS_PER_TOOL
            row["status"] = (row["status"] + ", est") if row["status"] else "est"
    return row


@mcp.tool()
async def search(query: str, compare: bool = False, registry: str = "all", limit: int = 5) -> str:
    """Search MCP servers. compare=True shows side-by-side token cost table.

    registry: all|official|mcpregistry|glama|npm|smithery|pypi
    """
    if compare:
        return await _run_compare(query, limit)

    if registry == "smithery":
        reg = _state.SmitheryRegistry()
    elif registry == "npm":
        reg = _state.NpmRegistry()
    elif registry == "pypi":
        reg = _state.PyPIRegistry()
    elif registry in ("official", "mcpregistry", "glama"):
        from kitsune_mcp.official_registry import OfficialMCPRegistry
        from kitsune_mcp.registry import GlamaRegistry, McpRegistryIO
        reg = {"official": OfficialMCPRegistry(), "mcpregistry": McpRegistryIO(), "glama": GlamaRegistry()}[registry]
    else:
        reg = _state._registry

    servers = await reg.search(query, limit)
    if not servers:
        return f"No servers found for '{query}'. Try a different query or registry."

    lines = [f"SERVERS — '{query}' ({len(servers)} found)\n"]
    # Report any registry failures when searching all registries
    if registry == "all":
        errors = getattr(_state._registry, "last_registry_errors", {})
        if errors:
            _ERR_LABELS = {
                "TimeoutError": "timeout", "asyncio.TimeoutError": "timeout",
                "ReadTimeout": "timeout", "ConnectTimeout": "timeout",
                "HTTPStatusError": "HTTP error", "ConnectError": "unreachable",
                "RemoteProtocolError": "protocol error",
            }
            failed = ", ".join(
                f"{n} ({_ERR_LABELS.get(exc, exc)})"
                for n, exc in errors.items()
            )
            lines.insert(1, f"⚠️  Skipped: {failed}\n")
    for s in servers:
        cred_status = _credentials_ready(s.credentials, s.source)
        lines.append(f"{s.id} | {s.name} — {s.description} | {s.source}/{s.transport} | {cred_status}")
        session["explored"][s.id] = {"name": s.name, "desc": s.description, "status": "explored"}

    _is_fresh = not session["grown"] and session["stats"]["total_calls"] <= 1
    if _is_fresh:
        lines.append(
            "\n💡 New here? Try: shapeshift('duckduckgo-websearch', confirm=True)  — free, no key needed"
        )
    else:
        lines.append("\nauth('<id>') to check credentials | shapeshift('<id>') to mount")
    return "\n".join(lines)


@mcp.tool()
async def inspect(server_id: str, probe: bool = False) -> str:
    """Show server tools, schemas, and required credentials.

    Auto-probes high/medium-trust sources for live tool schemas.
    Community sources (npm, github, glama-via-github) are gated — pass
    probe=True to install and probe them, or set KITSUNE_TRUST=community.
    """
    if server_id.startswith(("http://", "https://")):
        srv = _state._synthetic_http_server(server_id)
    else:
        srv = await _state._registry.get_server(server_id)
        if srv is None:
            return f"Server '{server_id}' not found. Use search() to find servers."

    lines = [
        f"{srv.name} ({srv.id})",
        f"Source: {srv.source} | Transport: {srv.transport}",
        f"Description: {srv.description[:200]}",
        "",
    ]

    resolved_creds, _ = _state._resolve_config(srv.credentials, {})
    lines += _credentials_inspect_block(srv.credentials, resolved_creds, srv.source)

    if srv.transport == "stdio":
        cmd_str = " ".join(srv.install_cmd) if srv.install_cmd else f"npx -y {srv.id}"
        lines += [f"RUN: {cmd_str}", ""]

    # Decide whether we may probe live (auto-allowed for trusted sources;
    # community sources require explicit probe=True or KITSUNE_TRUST).
    allow_probe, gate_reason = _state._probe_trust_ok(srv)
    if probe:
        allow_probe, gate_reason = True, ""
    can_probe_via_install = bool(srv.install_cmd)
    can_probe_via_oauth = srv.source == "direct" and srv.transport == "http"

    tools = srv.tools or []
    live_source = False
    probe_error: str | None = None
    probe_gated = False

    if allow_probe and (can_probe_via_install or can_probe_via_oauth):
        try:
            if can_probe_via_oauth:
                transport = _state._get_transport(srv.id, srv)
                live_tools = await asyncio.wait_for(
                    transport.list_tools(), timeout=TIMEOUT_STDIO_INIT
                )
            else:
                probe_env = _state._probe_env(srv)
                tmpdir = probe_env.get("TMPDIR", "")
                try:
                    _probe_t = _state.PersistentStdioTransport(
                        srv.install_cmd, probe_env=probe_env
                    )
                    live_tools = await asyncio.wait_for(
                        _probe_t.list_tools(),
                        timeout=TIMEOUT_STDIO_INIT,
                    )
                    _kill_probe(_probe_t._pool_key)
                finally:
                    if tmpdir:
                        shutil.rmtree(tmpdir, ignore_errors=True)
            if live_tools:
                tools = live_tools
                live_source = True
        except Exception as e:
            probe_error = str(e)[:200]
    elif (can_probe_via_install or can_probe_via_oauth) and not allow_probe:
        probe_gated = True

    if tools:
        suffix = f", {_state._probe_label(srv)}" if live_source else ""
        label = f"TOOLS (live{suffix})" if live_source else "TOOLS"
        lines.append(f"{label} ({len(tools)})")
        for t in tools:
            tname = t.get("name", "?")
            tdesc = (t.get("description") or "")[:MAX_INSPECT_DESC]
            params = list((t.get("inputSchema") or {}).get("properties", {}).keys())
            pstr = f"({', '.join(params)})" if params else ""
            lines.append(f"  {tname}{pstr} — {tdesc}")
        # Prefer measured cost from actual schemas over registry estimate
        token_cost = _estimate_tokens(tools)
        lines.append(f"\nToken cost: ~{token_cost} tokens (measured)")
    else:
        if probe_gated:
            lines.append(
                f"TOOLS: not probed ({gate_reason} — would run code from {srv.source})"
            )
            lines.append(f"To probe live: inspect(\"{srv.id}\", probe=True)")
            lines.append("To always trust community: auth(\"KITSUNE_TRUST\", \"community\")")
        elif probe_error:
            lines.append(f"TOOLS: live probe failed — {probe_error}")
        elif srv.transport == "stdio":
            lines.append("TOOLS: probe skipped (no install command)")
        else:
            lines.append("TOOLS: not listed in registry")
        token_cost = srv.token_cost or 0

    session["explored"][srv.id] = {
        "name": srv.name, "desc": srv.description,
        "status": "inspected", "token_cost": token_cost,
    }

    # Suggest next action based on credential state and probe outcome
    _, missing_creds = _state._resolve_config(srv.credentials, {})
    if probe_error and missing_creds:
        first_var = _to_env_var(next(iter(missing_creds)))
        lines.append(
            f"\nProbe may have failed due to missing creds. "
            f"Try: auth(\"{first_var}\", \"...\") then inspect(\"{srv.id}\")"
        )
    elif probe_error:
        lines.append(
            "\nIf the server needs credentials not declared in registry, "
            "set them with auth() and retry inspect."
        )
    elif missing_creds:
        first_var = _to_env_var(next(iter(missing_creds)))
        lines.append(f"\nNext: auth(\"{first_var}\", \"...\") then shapeshift(\"{srv.id}\")")
    else:
        lean_hint = f", tools=[\"{tools[0].get('name', '')}\"]" if tools and len(tools) > 4 else ""
        lines.append(f"\nNext: shapeshift(\"{srv.id}\"{lean_hint})")

    return "\n".join(lines)


async def _run_compare(query: str, limit: int = 6, probe: bool = False) -> str:
    """Core compare logic, shared by compare() and search(..., compare=True)."""
    servers = await _state._registry.search(query, limit)
    if not servers:
        return f"No servers found for '{query}'. Try a different query."

    rows = await asyncio.gather(
        *[_compare_probe(s, allow_low_trust=probe) for s in servers],
        return_exceptions=False,
    )
    # Sort: known token cost first (ascending), then unknown last.
    rows.sort(key=lambda r: (r["tokens"] is None, r["tokens"] or 0))

    lines = [f"COMPARING — '{query}' ({len(rows)} candidates)\n"]
    header = f"{'tokens':>9}  {'tools':>5}  {'src':<11}  {'status':<24}  id"
    lines.append(header)
    lines.append("-" * 84)
    for r in rows:
        tokens_s = f"{r['tokens']:,}" if r["tokens"] is not None else "—"
        tools_s = str(r["tools"]) if r["tools"] is not None else "—"
        src = r["source"][:11]
        status = r["status"][:24]
        lines.append(f"{tokens_s:>9}  {tools_s:>5}  {src:<11}  {status:<24}  {r['id']}")

    # Pick winners (ready = measured live / cached).
    _live_statuses = {"registry", "live", "live (oauth)", "live (smithery)"}
    ready = [r for r in rows if r["tokens"] is not None and r["status"] in _live_statuses]
    if ready:
        cheapest = ready[0]
        lines.append(
            f"\n💡 Cheapest ready-to-use: {cheapest['id']} "
            f"(~{cheapest['tokens']:,} tokens, {cheapest['tools']} tools, {cheapest['status']})"
        )
        lines.append(f"   Next: shapeshift(\"{cheapest['id']}\")")
    else:
        lines.append("\nNo candidates were ready to use without setup.")

    # Per-row actions for non-ready rows so the user sees what to do next.
    non_ready = [r for r in rows if r not in ready]
    if non_ready:
        lines.append("\nNext steps for the rest:")
        for r in non_ready:
            lines.append(f"  {r['id']:<40} → {r['action']}")

    if not probe:
        gated_count = sum(1 for r in rows if r["status"] == "gated")
        if gated_count:
            lines.append(
                f"\n({gated_count} community source{'s' if gated_count != 1 else ''} gated. "
                f"Run: compare(\"{query}\", probe=True) to probe them too.)"
            )
    return "\n".join(lines)


@mcp.tool()
async def compare(query: str, limit: int = 6, probe: bool = False) -> str:
    """Side-by-side token cost & creds for the top N candidates of a search.

    Probes ALL candidates in parallel. Use to pick a server before shapeshift().
    probe=True overrides the community-trust gate for community sources.
    """
    return await _run_compare(query, limit, probe)


@mcp.tool()
async def status() -> str:
    """Show provider auth state, current form, active connections, token stats.

    Provider section is shown first because the most common first-run failure
    is reaching for a server whose auth requirements are unmet — that's
    actionable info, performance stats are not.
    """
    from kitsune_mcp.credentials import _smithery_available

    explored = session["explored"]
    skills_data = session["skills"]
    grown = session["grown"]
    stats = session["stats"]
    current_form = session["current_form"]
    shapeshifted = session["shapeshift_tools"]

    from kitsune_mcp import __version__
    from kitsune_mcp.credentials import _registry_headers
    from kitsune_mcp.registry import REGISTRY_BASE
    from kitsune_mcp.utils import _get_http_client
    lines = [f"KITSUNE MCP  v{__version__}", ""]

    # PROVIDERS — Smithery key is validated with a live ping so users see
    # "verified" vs "set but INVALID" rather than just presence/absence.
    smithery_ok = _smithery_available()
    if smithery_ok:
        try:
            _r = await asyncio.wait_for(
                _get_http_client().get(
                    f"{REGISTRY_BASE}/servers",
                    params={"pageSize": 1},
                    headers=_registry_headers(),
                ),
                timeout=3.0,
            )
            if _r.status_code == 200:
                smithery_label = "(SMITHERY_API_KEY set — verified ✓)"
                smithery_icon = "✓"
            elif _r.status_code in (401, 403):
                smithery_label = "(SMITHERY_API_KEY set but INVALID — get a new key at smithery.ai/account/api-keys)"
                smithery_icon = "⚠️"
            else:
                smithery_label = f"(SMITHERY_API_KEY set — unverified, HTTP {_r.status_code})"
                smithery_icon = "✓"
        except Exception:
            smithery_label = "(SMITHERY_API_KEY set — could not verify)"
            smithery_icon = "✓"
    else:
        smithery_label = "(no key — auth('SMITHERY_API_KEY', 'sm-...') to unlock 3000+ servers)"
        smithery_icon = "🔑"

    lines.append("PROVIDERS")
    lines.append(f"  {smithery_icon}  Smithery  {smithery_label}")
    lines.append("  ✓  Official MCP Registry  (no key required)")
    lines.append("  ✓  npm + PyPI  (no key required)")
    lines.append("  ✓  Glama  (no key required)")
    if os.getenv("KITSUNE_TRUST", "").lower() in ("community", "all", "low"):
        lines.append("  ⚠️  KITSUNE_TRUST=community  (community-source confirmation gate is OFF)")
    lines.append("")

    # Gateway section — competing servers + absorbed servers
    try:
        from kitsune_mcp.gateway import _find_mcp_configs, _load_absorbed_servers
        gw_lines: list[str] = []
        for cfg in _find_mcp_configs():
            competing = [s for s in cfg.servers if "kitsune" not in s.id.lower()]
            if competing:
                tool_est = sum(s.estimated_tools for s in competing)
                gw_lines.append(
                    f"  ⚠  {len(competing)} other server(s) active in {cfg.client} "
                    f"(~{tool_est} extra tools in context)"
                )
                gw_lines.append("     Run setup() to harvest their credentials and reduce bloat")
        absorbed = _load_absorbed_servers()
        if absorbed:
            gw_lines.append(
                f"  ✓  Absorbed: {', '.join(a.id for a in absorbed)} (available via shapeshift)"
            )
        if gw_lines:
            lines.append("GATEWAY")
            lines.extend(gw_lines)
            lines.append("")
    except Exception:
        pass

    # First-run onboarding — show once when session is completely clean
    is_first_run = not explored and not grown and stats["total_calls"] == 0
    if is_first_run:
        lines += [
            "✨ Quick start:",
            "  1. shapeshift(\"mcp-server-time\")",
            "  2. call(\"get_current_time\", {\"timezone\": \"UTC\"})",
            "  3. shapeshift()",
            "  More: search(\"what you need\") | auth(\"SMITHERY_API_KEY\", \"sm-...\") for 3000+ servers",
            "",
        ]

    if current_form:
        lines.append(f"CURRENT FORM: {current_form}")
        lines.append(f"SHAPESHIFTED TOOLS ({len(shapeshifted)}): {', '.join(shapeshifted)}")
        lines.append("")
    else:
        lines += ["CURRENT FORM: base (no shapeshift active)", ""]

    crafted = session.get("crafted_tools", {})
    if crafted:
        lines.append(f"CRAFTED TOOLS ({len(crafted)})  [persisted — survive restarts]")
        for cname, cinfo in crafted.items():
            lines.append(f"  {cname} — {cinfo.get('method', 'POST')} {cinfo.get('url', '')}")
        lines.append("")

    # Persistent connections — ping all in parallel
    from kitsune_mcp.transport import _process_pool
    if _process_pool:
        pool_items = list(_process_pool.items())
        ping_results = await asyncio.gather(
            *[_ping(entry) for _, entry in pool_items],
            return_exceptions=True,
        )
        lines.append(f"PERSISTENT CONNECTIONS ({len(pool_items)})")
        for (pool_key, entry), responsive in zip(pool_items, ping_results, strict=False):
            label = entry.name or pool_key
            if not entry.is_alive():
                health = "dead"
            elif responsive is True:
                health = "alive+responsive"
            else:
                health = "alive+unresponsive"
            uptime = int(entry.uptime_seconds())
            mem = _rss_mb(entry.pid())
            mem_str = f" | mem: {mem}" if mem else ""
            conn_info = session["connections"].get(pool_key, {})
            tool_names = conn_info.get("tools", [])
            tool_str = f"Tools: {', '.join(tool_names)}" if tool_names else "Tools: none"
            lines.append(
                f"  {label} | PID {entry.pid()} | {health} | uptime: {uptime}s | calls: {entry.call_count}{mem_str}"
            )
            lines.append(f"    {tool_str}")
        lines.append("")

    if explored:
        lines.append(f"EXPLORED ({len(explored)})")
        for sid, info in explored.items():
            lines.append(f"  {sid} [{info.get('status', '?')}]")
        lines.append("")

    if grown:
        lines.append(f"ACTIVE NODES ({len(grown)})")
        for sid, info in grown.items():
            lines.append(
                f"  {sid} | {info.get('calls', 0)} calls | last: {info.get('last_tool', '—')}"
            )
        lines.append("")

    skill_tokens = 0
    if skills_data:
        lines.append(f"SKILLS ({len(skills_data)})")
        for sid, info in skills_data.items():
            t = info.get("tokens", 0)
            skill_tokens += t
            lines.append(f"  {sid} ~{t:,} tokens")
        lines.append("")

    # Token savings vs always-on: sum measured schema costs for inspected servers
    # that are NOT currently shapeshifted (those would be loaded if always-on).
    not_shapeshifted = {
        sid: info
        for sid, info in explored.items()
        if info.get("token_cost") and sid != current_form
    }
    lazy_saved = sum(info["token_cost"] for info in not_shapeshifted.values())

    lines += [
        "PERFORMANCE STATS",
        f"  Total calls:       {stats['total_calls']}",
        f"  Tokens sent:     ~{stats['tokens_sent']:,}",
        f"  Tokens received: ~{stats['tokens_received']:,}",
        f"  Saved via fetch: ~{stats['tokens_saved_browse']:,}",
        f"  Skill context:   ~{skill_tokens:,} tokens",
    ]
    if stats["total_calls"] > 0:
        avg = stats["tokens_received"] // stats["total_calls"]
        lines.append(f"  Avg response:    ~{avg} tokens")
    if lazy_saved > 0:
        n = len(not_shapeshifted)
        lines.append(
            f"  Saved vs always-on: ~{lazy_saved:,} tokens "
            f"[based on {n} inspected schema(s)]"
        )

    return "\n".join(lines)
