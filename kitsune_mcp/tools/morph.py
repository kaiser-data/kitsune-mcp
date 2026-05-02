"""Morph tools: shapeshift, shiftback, craft, connect, release."""

import asyncio
import contextlib
import dataclasses
import inspect as _inspect
import json
import os
import shlex

import httpx
from mcp.server.fastmcp import Context

from kitsune_mcp.app import mcp
from kitsune_mcp.constants import (
    TIMEOUT_PROMPT_LIST,
    TIMEOUT_RESOURCE_LIST,
    TRUST_HIGH,
    TRUST_LOW,
    TRUST_MEDIUM,
)
from kitsune_mcp.credentials import _credentials_guide, _credentials_ready
from kitsune_mcp.probe import _format_setup_guide
from kitsune_mcp.session import session
from kitsune_mcp.shapeshift import _json_type_to_py
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import BaseTransport, _process_pool
from kitsune_mcp.utils import _estimate_tokens, _get_http_client


async def _commit_shapeshift(
    server_id: str,
    transport: BaseTransport,
    tool_schemas: list,
    resolved_config: dict,
    tools: list[str] | None,
    ctx: Context,
    pool_key: str | None,
    trust_note: str,
    lean_eligible: bool = False,
) -> str:
    """Register tools/resources/prompts, update session, notify client, return output string.

    Called by both the pool-connection path and the registry path of shapeshift() so
    neither path has to duplicate the ~70-line registration + output block.
    """
    only = set(tools) if tools else None
    registered = _state._register_proxy_tools(
        server_id, tool_schemas, transport, resolved_config, _state._BASE_TOOL_NAMES, only
    )
    if not registered:
        return f"No tools could be shapeshifted from '{server_id}'."

    shapeshift_resources: list[str] = []
    shapeshift_prompts: list[str] = []
    if hasattr(transport, "list_resources"):
        with contextlib.suppress(Exception):
            raw_res = await asyncio.wait_for(transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST)
            shapeshift_resources = _state._register_proxy_resources(transport, raw_res)
    if hasattr(transport, "list_prompts"):
        with contextlib.suppress(Exception):
            raw_prompts = await asyncio.wait_for(transport.list_prompts(), timeout=TIMEOUT_PROMPT_LIST)
            shapeshift_prompts = _state._register_proxy_prompts(transport, raw_prompts)

    session["shapeshift_tools"] = registered
    session["shapeshift_resources"] = shapeshift_resources
    session["shapeshift_prompts"] = shapeshift_prompts
    session["current_form"] = server_id
    session["current_form_pool_key"] = pool_key

    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()
    if shapeshift_resources:
        with contextlib.suppress(Exception):
            await ctx.session.send_resource_list_changed()
    if shapeshift_prompts:
        with contextlib.suppress(Exception):
            await ctx.session.send_prompt_list_changed()

    missing_env: list[str] = []
    with contextlib.suppress(Exception):
        missing_env = _state._probe_requirements(tool_schemas, "").get("missing_env", [])

    lean = f" (lean: {', '.join(tools)})" if tools else ""
    extras = []
    if shapeshift_resources:
        extras.append(f"{len(shapeshift_resources)} resource(s)")
    if shapeshift_prompts:
        extras.append(f"{len(shapeshift_prompts)} prompt(s)")
    extra_note = f" + {', '.join(extras)}" if extras else ""

    lines = [
        f"Shapeshifted into '{server_id}'{lean} — {len(registered)} tool(s){extra_note} registered:",
        *[f"  {t}" for t in registered],
    ]
    if shapeshift_resources:
        shown = ", ".join(shapeshift_resources[:3]) + (" ..." if len(shapeshift_resources) > 3 else "")
        lines.append(f"Resources ({len(shapeshift_resources)}): {shown}")
    if shapeshift_prompts:
        shown = ", ".join(shapeshift_prompts[:3]) + (" ..." if len(shapeshift_prompts) > 3 else "")
        lines.append(f"Prompts ({len(shapeshift_prompts)}): {shown}")
    example_tool = registered[0]
    example_args: dict = {}
    from kitsune_mcp.shapeshift import _proxy_name_for
    example_schema = next(
        (
            ts for ts in tool_schemas
            if isinstance(ts, dict)
            and _proxy_name_for(server_id, ts.get("name", ""), _state._BASE_TOOL_NAMES) == example_tool
        ),
        {},
    )
    schema = example_schema.get("inputSchema", {})
    required = schema.get("required", [])
    props = schema.get("properties", {})
    if required and required[0] in props:
        p = required[0]
        ptype = props[p].get("type", "string")
        example_args = {p: _state._EXAMPLE_VALUES.get(ptype, "value")}
    lines += ["", f"In this session: call({example_tool!r}, arguments={example_args!r})"]
    lines.append(trust_note)
    if missing_env:
        lines.append("\n⚠️  Credentials may be required — add to .env:")
        for var in missing_env:
            lines.append(f"  {var}=your-value")
        lines.append(f'  Or: key("{missing_env[0]}", "your-value")')
    if lean_eligible and not tools and len(registered) > 4:
        tool_cost = _estimate_tokens(tool_schemas)
        lines.append(
            f"\n💡 {len(registered)} tools loaded (~{tool_cost:,} tokens). "
            f"For lean mounting: shapeshift(\"{server_id}\", tools=[\"{registered[0]}\"])"
        )
    return "\n".join(lines)


@mcp.tool()
async def shapeshift(
    server_id: str,
    ctx: Context,
    tools: list[str] | None = None,
    confirm: bool = False,
    source: str = "auto",
) -> str:
    """Shapeshift into a server's form. The fox takes on the server's shape — its tools become available natively in the session.

    source: "auto" (default) | "local" (force npx/uvx install) | "smithery" (force HTTP via Smithery) | "official" (official/mcpregistry only)
    tools: load only specific tools instead of everything
    confirm: proceed with community (npm/pypi/github) sources after reviewing
    KITSUNE_TRUST=community env var skips the community trust gate globally
    """
    # Pool connections (from connect()) take priority — user already vetted these, bypass trust gates
    for _pk, conn in session["connections"].items():
        if conn.get("name") == server_id or conn.get("command") == server_id:
            cmd = conn["command"].split()
            tool_names = conn.get("tools", [])
            _state._do_shed()
            session["current_form_local_install"] = None

            transport: BaseTransport = _state.PersistentStdioTransport(cmd)
            raw_tools = await transport.list_tools()
            if not raw_tools and tool_names:
                raw_tools = [{"name": n, "description": "", "inputSchema": {}} for n in tool_names]

            return await _commit_shapeshift(
                server_id, transport, raw_tools, {}, tools, ctx,
                json.dumps(cmd, sort_keys=True),
                "\n⚠️  Source: pool connection (local — verify command before use)",
            )

    # Registry path — source controls which registries/transports are preferred
    if source == "smithery" and not _state._smithery_available():
        return (
            f"Cannot use source='smithery' — SMITHERY_API_KEY is not set.\n\n"
            f"Set it: key(\"SMITHERY_API_KEY\", \"your-key\")\n"
            f"Or use: shapeshift(\"{server_id}\", source=\"local\") to install locally."
        )

    if server_id.startswith(("http://", "https://")):
        srv = _state._synthetic_http_server(server_id)
    else:
        reg_source = source if source in ("smithery", "official") else None
        srv = await _state._registry.get_server(server_id, source_preference=reg_source)
        if srv is None:
            return f"Server '{server_id}' not found. Use search() to find servers, or connect() for local servers."

    srv_source = srv.source

    # Check source constraint first — clearer error than the trust gate when source="official" resolves non-official
    if source == "official" and srv_source not in ("official", "mcpregistry"):
        return (
            f"No official/verified listing found for '{server_id}' (resolved source: {srv_source}).\n"
            f"Try: shapeshift(\"{server_id}\") for auto, or shapeshift(\"{server_id}\", source=\"local\")."
        )

    trust_level = (os.getenv("KITSUNE_TRUST") or "").lower()
    _trust_override = trust_level in ("community", "all", "low")

    if srv_source in TRUST_LOW and not confirm and not _trust_override:
        preview_lines = []
        if srv.tools:
            names = ", ".join(t.get("name", "?") for t in srv.tools[:8])
            suffix = f" +{len(srv.tools) - 8} more" if len(srv.tools) > 8 else ""
            preview_lines.append(f"Tools ({len(srv.tools)}): {names}{suffix}")
        cred_status = _credentials_ready(srv.credentials, srv_source)
        preview_lines.append(f"Credentials: {cred_status}")
        preview = ("\n" + "\n".join(preview_lines) + "\n") if preview_lines else "\n"
        return (
            f"⚠️  '{server_id}' is from {srv_source} (community — not verified by the official MCP registry)."
            f"{preview}"
            f"To proceed: shapeshift('{server_id}', confirm=True)\n"
            f"To always trust community: key(\"KITSUNE_TRUST\", \"community\")"
        )

    if source == "local" and not confirm and not _trust_override:
        install_cmd = srv.install_cmd or _state._infer_install_cmd(server_id)
        return (
            f"⚠️  source='local' will run: {' '.join(install_cmd)}\n\n"
            f"This downloads and executes the package locally.\n"
            f"Review first: inspect('{server_id}')\n\n"
            f"To proceed: shapeshift('{server_id}', source='local', confirm=True)\n"
            f"To always trust local installs: key(\"KITSUNE_TRUST\", \"community\")"
        )

    # All gates passed — resolve credentials before dropping current form
    resolved_config, missing = _state._resolve_config(srv.credentials, {})
    if missing:
        creds_msg = _credentials_guide(server_id, srv.credentials, resolved_config)
        return f"Cannot shapeshift into '{server_id}' — missing credentials:\n\n{creds_msg}"

    _state._do_shed()
    session["current_form_local_install"] = None  # overwritten below for source="local"

    if source == "local":
        install_cmd = srv.install_cmd or _state._infer_install_cmd(server_id)
        srv = dataclasses.replace(srv, transport="stdio", install_cmd=install_cmd)
        session["current_form_local_install"] = {"cmd": srv.install_cmd, "package": server_id}

    if srv.transport == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        # PersistentStdioTransport keeps the process alive for subsequent tool calls
        transport = _state.PersistentStdioTransport(cmd)
        pool_key: str | None = json.dumps(cmd, sort_keys=True)
        tool_schemas = srv.tools or []
        if not tool_schemas:
            with contextlib.suppress(Exception):
                tool_schemas = await transport.list_tools()
    else:
        transport = _state._get_transport(server_id, srv)
        pool_key = None
        tool_schemas = srv.tools or []
        if not tool_schemas and hasattr(transport, "list_tools"):
            tool_schemas = await transport.list_tools(resolved_config)

    if not tool_schemas:
        return f"No tools found for '{server_id}'. Try inspect() first."

    transport_label = " via local npx/uvx" if srv.transport == "stdio" else ""
    if srv_source in TRUST_HIGH | TRUST_MEDIUM:
        trust_note = f"\n✓  Source: {srv_source}{transport_label}"
    else:
        trust_note = f"\n⚠️  Source: {srv_source}{transport_label} (community — not verified by official MCP registry)"

    return await _commit_shapeshift(
        server_id, transport, tool_schemas, resolved_config, tools, ctx,
        pool_key, trust_note, lean_eligible=True,
    )


@mcp.tool()
async def shiftback(ctx: Context, kill: bool = False, uninstall: bool = False) -> str:
    """Shift back to Kitsune's true form. Removes all shapeshifted tools.

    kill=True      also terminate the underlying server process
    uninstall=True also uninstall the locally installed package (implies kill=True;
                   only applies when shapeshifted via source='local')
    """
    has_tools = bool(session["shapeshift_tools"])
    has_resources = bool(session.get("shapeshift_resources"))
    has_prompts = bool(session.get("shapeshift_prompts"))
    if not has_tools and not has_resources and not has_prompts:
        return "Already in base form."

    form = session["current_form"]
    local_install = session.pop("current_form_local_install", None)
    # Snapshot counts before _do_shed() clears the lists
    n_res = len(session.get("shapeshift_resources", []))
    n_prompts = len(session.get("shapeshift_prompts", []))
    removed = _state._do_shed()

    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()
    if n_res:
        with contextlib.suppress(Exception):
            await ctx.session.send_resource_list_changed()
    if n_prompts:
        with contextlib.suppress(Exception):
            await ctx.session.send_prompt_list_changed()

    extras = []
    if n_res:
        extras.append(f"{n_res} resource(s)")
    if n_prompts:
        extras.append(f"{n_prompts} prompt(s)")
    extra_note = f", {', '.join(extras)}" if extras else ""

    result_lines = [f"Shifted back from '{form}'. Removed: {', '.join(removed)}{extra_note}"]

    if (kill or uninstall) and form:
        # Use the exact pool key stored at shapeshift() time — no fragile string matching needed
        exact_key = session.pop("current_form_pool_key", None)
        killed = []
        keys_to_check = [exact_key] if exact_key else list(_process_pool.keys())
        for pool_key in keys_to_check:
            entry = _process_pool.get(pool_key)
            if entry is None:
                continue
            with contextlib.suppress(Exception):
                entry.proc.kill()
                await asyncio.wait_for(entry.proc.wait(), timeout=TIMEOUT_RESOURCE_LIST)
            _process_pool.pop(pool_key, None)
            killed.append(entry.name or entry.install_cmd[0])
        if killed:
            result_lines.append(f"Released: {', '.join(killed)}")

    if uninstall and local_install:
        uninstall_cmd = _state._local_uninstall_cmd(local_install["cmd"])
        pkg = local_install["package"]
        if uninstall_cmd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *uninstall_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode == 0:
                    result_lines.append(f"Uninstalled: {pkg}")
                else:
                    err = stderr.decode().strip()[:120]
                    result_lines.append(f"Uninstall failed ({pkg}): {err}")
            except Exception as e:
                result_lines.append(f"Uninstall error ({pkg}): {e}")
        else:
            # npx packages are cached, not permanently installed — no action needed
            result_lines.append(f"Note: '{pkg}' was run via npx (cached, not permanently installed — cache expires automatically)")
    elif local_install and not uninstall:
        pkg = local_install["package"]
        result_lines.append(f"Local package '{pkg}' is still cached. To remove: shiftback(uninstall=True)")

    return "\n".join(result_lines)


@mcp.tool()
async def craft(
    ctx: Context,
    name: str,
    description: str,
    params: dict,
    url: str,
    method: str = "POST",
    headers: dict | None = None,
) -> str:
    """Register a custom tool backed by your HTTP endpoint — live immediately. POST=JSON body, GET=query params. shiftback() removes it."""
    if not name or not name.replace("_", "").isalnum():
        return "name must be alphanumeric (underscores allowed)."
    if not url.startswith(("http://", "https://")):
        return "url must start with http:// or https://"

    _url = url
    _method = method.upper()
    _headers = headers or {}

    # Build Python parameters from JSON Schema properties
    py_params = []
    for pname, pschema in (params or {}).items():
        json_type = pschema.get("type", "string") if isinstance(pschema, dict) else "string"
        ptype = _json_type_to_py(json_type)
        py_params.append(_inspect.Parameter(
            pname, _inspect.Parameter.KEYWORD_ONLY,
            default=_inspect.Parameter.empty, annotation=ptype,
        ))

    async def _endpoint_proxy(**kwargs) -> str:
        try:
            client = _get_http_client()
            if _method == "GET":
                r = await client.get(_url, params=kwargs, headers=_headers, timeout=30.0)
            else:
                r = await client.request(_method, _url, json=kwargs, headers=_headers, timeout=30.0)
            r.raise_for_status()
            return r.text
        except httpx.HTTPStatusError as e:
            return f"HTTP {e.response.status_code} from {_url}: {e.response.text[:200]}"
        except Exception as e:
            return f"Error calling {_url}: {e}"

    _endpoint_proxy.__name__ = name
    _endpoint_proxy.__doc__ = description[:120]
    _endpoint_proxy.__signature__ = _inspect.Signature(py_params, return_annotation=str)

    # Remove previous registration if re-crafting the same name
    if name in session["crafted_tools"]:
        with contextlib.suppress(Exception):
            mcp.remove_tool(name)
        session["shapeshift_tools"] = [t for t in session["shapeshift_tools"] if t != name]

    try:
        mcp.add_tool(_endpoint_proxy)
    except Exception as e:
        return f"Failed to register tool '{name}': {e}"

    session["crafted_tools"][name] = {
        "url": url, "method": _method, "description": description, "params": params or {},
    }
    if name not in session["shapeshift_tools"]:
        session["shapeshift_tools"].append(name)

    with contextlib.suppress(Exception):
        await ctx.session.send_tool_list_changed()

    param_list = ", ".join(params.keys()) if params else "(none)"
    return (
        f"✓ Tool '{name}' registered — {_method} {url}\n"
        f"Params: {param_list}\n\n"
        f"Call it directly, or shiftback() to remove it."
    )


@mcp.tool()
async def connect(command: str, name: str = "", timeout: int = 60, inherit_stderr: bool = True) -> str:
    """Start a persistent server. command: server_id or shell cmd (e.g. 'uvx voice-mode'). name: alias for release()."""
    # Detect server_id vs shell command: if it has no spaces and doesn't start with a
    # known executor, try registry lookup first.
    _EXECUTORS = ("npx", "uvx", "node", "python", "python3", "uv", "deno", "docker")
    looks_like_cmd = " " in command or command.split()[0] in _EXECUTORS
    install_cmd: list[str] | None = None

    if not looks_like_cmd:
        srv = await _state._registry.get_server(command)
        if srv and srv.install_cmd:
            install_cmd = srv.install_cmd
            if not name:
                name = srv.name or command

    if install_cmd is None:
        install_cmd = shlex.split(command)
    pool_key = json.dumps(install_cmd, sort_keys=True)
    friendly = name or install_cmd[0]

    # Already connected?
    existing = _process_pool.get(pool_key)
    if existing is not None and existing.is_alive():
        uptime = int(existing.uptime_seconds())
        calls = existing.call_count
        label = existing.name or friendly
        return (
            f"Already connected: {label} (PID {existing.pid()}) | "
            f"uptime: {uptime}s | calls: {calls}"
        )

    transport = _state.PersistentStdioTransport(install_cmd, inherit_stderr=inherit_stderr)
    try:
        entry = await asyncio.wait_for(transport._start_process(), timeout=timeout)
    except TimeoutError:
        return f"Timeout starting '{command}' after {timeout}s."
    except RuntimeError as e:
        return str(e)

    entry.name = friendly

    # Fetch tool list from live process
    tools = await transport.list_tools()
    tool_names = [t.get("name", "?") for t in tools]

    resource_text = await _state._fetch_resource_docs(transport)

    # Update session connections
    session["connections"][pool_key] = {
        "name": friendly,
        "command": command,
        "pid": entry.pid(),
        "started_at": entry.started_at,
        "tools": tool_names,
    }

    tool_summary = f"Tools ({len(tool_names)}): {', '.join(tool_names)}" if tool_names else "Tools: none listed"
    setup_guide = _format_setup_guide(_state._probe_requirements(tools, resource_text), friendly, tools=tools)

    # Trust / source note — resolve from registry if possible, otherwise flag as local
    _conn_srv = await _state._registry.get_server(command) if not looks_like_cmd else None
    conn_source = _conn_srv.source if _conn_srv else "local"
    if conn_source in TRUST_HIGH | TRUST_MEDIUM:
        trust_note = f"✓  Source: {conn_source}"
    else:
        trust_note = f"⚠️  Source: {conn_source} (verify command before connecting)"

    parts = [
        f"Connected: {friendly} (PID {entry.pid()})",
        tool_summary,
        f"Release with: release('{friendly}')",
    ]
    if setup_guide:
        parts.append(setup_guide)
        parts.append(f"\nCall setup('{friendly}') for step-by-step guidance.")
    parts.append(trust_note)
    return "\n".join(parts)


@mcp.tool()
async def release(name: str) -> str:
    """Kill a persistent connection by name."""
    # Find entry by name or pool_key
    found_key = None
    found_entry = None

    for pool_key, entry in _process_pool.items():
        if entry.name == name or pool_key == name:
            found_key = pool_key
            found_entry = entry
            break

    if found_key is None or found_entry is None:
        active = [e.name or k for k, e in _process_pool.items()]
        if active:
            return f"No connection named '{name}'. Active: {', '.join(active)}"
        return "No active connections. Use connect() to start one."

    uptime = int(found_entry.uptime_seconds())
    calls = found_entry.call_count
    pid = found_entry.pid()
    label = found_entry.name or found_key

    try:
        found_entry.proc.kill()
        await asyncio.wait_for(found_entry.proc.wait(), timeout=TIMEOUT_RESOURCE_LIST)
    except Exception:
        pass

    _process_pool.pop(found_key, None)
    session["connections"].pop(found_key, None)

    return f"Released: {label} (PID {pid}) | uptime: {uptime}s | calls: {calls}"
