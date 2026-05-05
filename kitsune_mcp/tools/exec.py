"""Execution tools: call, run, fetch, test, bench."""

import asyncio
import json
import time

from kitsune_mcp.app import mcp
from kitsune_mcp.constants import (
    MAX_RESPONSE_TOKENS,
    TIMEOUT_FETCH_URL,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
    TRUST_HIGH,
    TRUST_MEDIUM,
)
from kitsune_mcp.credentials import _credentials_guide
from kitsune_mcp.session import session
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import BaseTransport
from kitsune_mcp.utils import (
    _estimate_tokens,
    _get_http_client,
    _strip_html,
    _truncate,
    _try_axonmcp,
)


@mcp.tool()
async def call(
    tool_name: str,
    server_id: str | None = None,
    arguments: dict | None = None,
    config: dict | None = None,
) -> str:
    """Call a tool on an MCP server. server_id optional when shapeshifted — current form used.
    After shapeshift(): call('list_directory', arguments={'path': '/tmp'})
    Direct:             call('list_directory', '@some-server', {'path': '/tmp'})"""
    if server_id is None:
        server_id = session.get("current_form")
        if not server_id:
            return "Provide a server_id, or use shapeshift() first to set a current form."
    if arguments is None:
        arguments = {}
    if config is None:
        config = {}
    if server_id.startswith(("http://", "https://")):
        srv = _state._synthetic_http_server(server_id)
    else:
        srv = await _state._registry.get_server(server_id)
    credentials = srv.credentials if srv else {}

    resolved_config, missing = _state._resolve_config(credentials, config)
    if missing:
        return _credentials_guide(server_id, credentials, resolved_config)

    # When call() targets the currently shapeshifted form, prefer the pooled transport
    # that shapeshift() created — this respects source='local' and other overrides that
    # _get_transport() can't see (it re-resolves from registry and picks HTTP for
    # Smithery servers regardless of what shapeshift set up).
    pool_key = session.get("current_form_pool_key")
    if server_id == session.get("current_form") and pool_key:
        transport: BaseTransport = _state.PersistentStdioTransport(json.loads(pool_key))
    else:
        transport = _state._get_transport(server_id, srv)
    result = await transport.execute(tool_name, arguments, resolved_config)

    _state._track_call(server_id, tool_name)

    if srv is not None:
        source = srv.source
        if source not in TRUST_HIGH | TRUST_MEDIUM:
            result = result + f"\n[source: {source}]"
    return result


@mcp.tool()
async def run(
    package: str,
    tool_name: str,
    arguments: dict | None = None,
) -> str:
    """Run a tool from npm/pip. package: 'pkg-name' (npx) or 'uvx:pkg-name' (Python)."""
    if arguments is None:
        arguments = {}
    cmd = ["uvx", package[4:]] if package.startswith("uvx:") else ["npx", "-y", package]

    transport = _state.PersistentStdioTransport(cmd)
    result = await transport.execute(tool_name, arguments, {})

    _state._track_call(package, tool_name)
    return result


@mcp.tool()
async def fetch(url: str, intent: str = "") -> str:
    """Fetch a URL and return compressed content (~500 tokens vs ~25K raw HTML)."""
    raw_estimate = 6000  # typical webpage token count before compression

    axon_result = await _try_axonmcp(url, intent)
    if axon_result:
        saved = max(0, raw_estimate - _estimate_tokens(axon_result))
        session["stats"]["tokens_saved_browse"] += saved
        return axon_result

    # Fallback: httpx + HTML stripping
    try:
        r = await _get_http_client().get(
            url, timeout=TIMEOUT_FETCH_URL, headers={"User-Agent": "Mozilla/5.0"}
        )
        r.raise_for_status()
        text = r.text
    except Exception as e:
        return f"Failed to fetch {url}: {e}"

    stripped = _strip_html(text)
    result = _truncate(stripped, max_tokens=MAX_RESPONSE_TOKENS)
    saved = max(0, raw_estimate - _estimate_tokens(result))
    session["stats"]["tokens_saved_browse"] += saved

    header = f"[{url}]" + (f" — intent: {intent}" if intent else "")
    return f"{header}\n\n{result}"


@mcp.tool()
async def test(server_id: str, level: str = "basic") -> str:
    """Quality-score a server 0–100. level: 'basic' (schema checks) or 'full' (live calls)."""
    score = 0
    checks = []

    # Check 1: Registry lookup (15 pts)
    srv = await _state._registry.get_server(server_id)
    if srv is not None:
        score += 15
        checks.append("✅ Registry lookup found server (+15)")
    else:
        checks.append("❌ Server not found in registry (0)")
        return f"Score: {score}/100 (Poor)\n\n" + "\n".join(checks) + "\nGrade: Poor — server not found."

    # Check 2: Known transport type (5 pts)
    if srv.transport in ("http", "stdio"):
        score += 5
        checks.append(f"✅ Transport type known: {srv.transport} (+5)")
    else:
        checks.append(f"❌ Unknown transport: {srv.transport!r} (0)")

    # Check 3: Has description (5 pts)
    if srv.description and len(srv.description) > 10:
        score += 5
        checks.append("✅ Has description (+5)")
    else:
        checks.append("❌ Missing or too-short description (0)")

    # Check 4: tools/list responds (15 pts)
    tools = srv.tools or []
    if not tools and srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        try:
            tools = await asyncio.wait_for(
                _state.PersistentStdioTransport(cmd).list_tools(), timeout=TIMEOUT_STDIO_INIT
            )
        except TimeoutError:
            tools = []

    if tools:
        score += 15
        checks.append(f"✅ tools/list responded with {len(tools)} tools (+15)")
    else:
        checks.append("❌ tools/list returned no tools (0)")

    # Check 5: Tool schemas valid (10 pts)
    if tools:
        valid_schemas = sum(
            1 for t in tools
            if t.get("name") and t.get("inputSchema")
        )
        schema_score = min(10, int(10 * valid_schemas / len(tools)))
        score += schema_score
        checks.append(f"✅ Schema quality: {valid_schemas}/{len(tools)} tools valid (+{schema_score})")
    else:
        checks.append("⚠️  No tools to check schemas (0)")

    # Check 6: No collision with base tool names (10 pts)
    collisions = [t.get("name") for t in tools if t.get("name") in _state._BASE_TOOL_NAMES]
    if not collisions:
        score += 10
        checks.append("✅ No name collisions with Kitsune base tools (+10)")
    else:
        checks.append(f"⚠️  Name collisions: {', '.join(collisions)} (0) — will be prefixed on shapeshift()")

    # Check 7: Live tool calls (full mode only, 10 pts per tool, max 5 tools)
    if level == "full" and tools:
        checks.append("\n--- FULL MODE: live tool calls ---")
        call_score = 0
        resolved_config, _ = _state._resolve_config(srv.credentials, {})
        # Build one transport for the full-mode run — reuse pool entry across all tool calls
        transport_obj: BaseTransport = _state._get_transport(server_id, srv)
        for t in tools[:5]:
            tname = t.get("name", "")
            props, required = _state._extract_tool_schema(t)
            dummy_args = {
                pname: _state._DUMMY_VALUES.get(pschema.get("type", "string"), "test")
                for pname, pschema in props.items()
                if pname in required
            }

            try:
                result = await asyncio.wait_for(
                    transport_obj.execute(tname, dummy_args, resolved_config), timeout=TIMEOUT_STDIO_TOOL
                )
                if "error" not in result.lower() and "failed" not in result.lower()[:50]:
                    call_score += 10
                    checks.append(f"  ✅ {tname}() callable (+10)")
                else:
                    checks.append(f"  ⚠️  {tname}() returned error (0)")
            except Exception as e:
                checks.append(f"  ❌ {tname}() raised exception: {e!s:.60} (0)")

        score += min(50, call_score)

    # Grade
    if score >= 90:
        grade = "Excellent"
    elif score >= 75:
        grade = "Good"
    elif score >= 50:
        grade = "Fair"
    else:
        grade = "Poor"

    header = f"Score: {score}/100 ({grade}) — {server_id}"
    return header + "\n\n" + "\n".join(checks) + f"\n\nGrade: {grade}"


@mcp.tool()
async def bench(server_id: str, tool_name: str, args: dict | None = None, iterations: int = 5) -> str:
    """Benchmark tool latency — p50, p95, min, max ms. iterations: 1–20."""
    if args is None:
        args = {}
    iterations = max(1, min(20, iterations))

    srv = await _state._registry.get_server(server_id)
    if srv is None:
        return f"Server '{server_id}' not found. Use search() to find servers."

    transport_obj: BaseTransport = _state._get_transport(server_id, srv)
    resolved_config, missing = _state._resolve_config(srv.credentials, {})
    if missing:
        return _credentials_guide(server_id, srv.credentials, resolved_config)

    latencies: list[float] = []
    errors: list[str] = []
    boot_ms: float | None = None  # first call includes process boot — reported separately

    for i in range(iterations):
        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                transport_obj.execute(tool_name, args, resolved_config), timeout=TIMEOUT_STDIO_TOOL
            )
            elapsed_ms = (time.monotonic() - t0) * 1000
            _r = result.lower()
            if any(kw in _r for kw in ("error", "auth failed", "failed to connect", "timeout connecting")):
                errors.append(f"call {i + 1}: tool returned error")
            elif i == 0 and isinstance(transport_obj, _state.PersistentStdioTransport):
                boot_ms = elapsed_ms  # exclude boot from latency stats
            else:
                latencies.append(elapsed_ms)
        except TimeoutError:
            errors.append(f"call {i + 1}: timeout (>30s)")
        except Exception as e:
            errors.append(f"call {i + 1}: {e!s:.60}")

    if not latencies and boot_ms is None:
        return f"All {iterations} calls failed:\n" + "\n".join(errors)

    # If all calls were boot or only one iteration, fall back to including boot_ms
    if not latencies and boot_ms is not None:
        latencies = [boot_ms]
        boot_ms = None

    latencies.sort()
    n = len(latencies)
    p50 = latencies[int(n * 0.50)]
    p95 = latencies[min(n - 1, int(n * 0.95))]
    avg = sum(latencies) / n

    lines = [
        f"Benchmark: {server_id}/{tool_name} ({n}/{iterations} succeeded)",
    ]
    if boot_ms is not None:
        lines.append(f"  boot:  {boot_ms:.0f}ms (process start, excluded from stats)")
    lines += [
        f"  p50: {p50:.0f}ms",
        f"  p95: {p95:.0f}ms",
        f"  min: {latencies[0]:.0f}ms",
        f"  max: {latencies[-1]:.0f}ms",
        f"  avg: {avg:.0f}ms",
    ]
    if errors:
        lines.append(f"  errors ({len(errors)}): " + "; ".join(errors))
    return "\n".join(lines)
