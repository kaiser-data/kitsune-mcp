import inspect as _inspect
import re
from collections.abc import Callable

from mcp.server.fastmcp.prompts.base import Prompt as _Prompt
from mcp.server.fastmcp.resources.types import FunctionResource as _FunctionResource

from kitsune_mcp._fastmcp_compat import remove_prompt, remove_resource
from kitsune_mcp.app import mcp
from kitsune_mcp.session import session
from kitsune_mcp.transport import BaseTransport

# Matches URI template parameters like {path} or {file_name}
_URI_TEMPLATE_RE = re.compile(r'\{[a-zA-Z_][a-zA-Z0-9_]*\}')


def _json_type_to_py(json_type: str) -> type:
    """Convert JSON Schema type string to Python type."""
    mapping = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    return mapping.get(json_type, str)


def _make_proxy(
    server_id: str,
    tool_schema: dict,
    transport: BaseTransport,
    config: dict,
    proxy_name: str = None,
) -> Callable:
    """Create a proxy callable that forwards calls to a remote/local MCP tool.

    proxy_name: the name the tool will be registered as in FastMCP.
                Defaults to tool_schema["name"]. The transport always uses
                the original schema name when calling the remote server.
    """
    original_name = tool_schema["name"]
    fn_name = proxy_name or original_name
    props = (tool_schema.get("inputSchema") or {}).get("properties", {})
    required_set = set((tool_schema.get("inputSchema") or {}).get("required", []))

    params = []
    for pname, pschema in props.items():
        ptype = _json_type_to_py(pschema.get("type", "string"))
        default = _inspect.Parameter.empty if pname in required_set else None
        params.append(_inspect.Parameter(
            pname, _inspect.Parameter.KEYWORD_ONLY,
            default=default, annotation=ptype,
        ))

    async def proxy_fn(**kwargs) -> str:
        # Optional params get default=None in our signature so FastMCP/pydantic
        # accept calls that omit them. But forwarding `None` to the inner
        # MCP server fails its schema validation: JSON Schema rejects null for
        # typed params unless explicitly declared as ["type", "null"], which is
        # rare. Drop None-valued kwargs so the inner server applies its own
        # defaults instead of seeing a poison value.
        cleaned = {k: v for k, v in kwargs.items() if v is not None}
        return await transport.execute(original_name, cleaned, config)

    proxy_fn.__name__ = fn_name
    proxy_fn.__doc__ = (tool_schema.get("description") or "")[:120]
    proxy_fn.__signature__ = _inspect.Signature(params, return_annotation=str)
    return proxy_fn


def _do_shed() -> list[str]:
    """Remove all shapeshifted proxy tools, resources, and prompts.

    Returns list of removed tool names (resources/prompts cleaned up silently).
    """
    removed = []
    for tname in session["shapeshift_tools"]:
        try:
            mcp.remove_tool(tname)
            removed.append(tname)
        except Exception:
            pass
    session["shapeshift_tools"] = []

    for uri in session.get("shapeshift_resources", []):
        remove_resource(mcp, uri)
    session["shapeshift_resources"] = []

    for pname in session.get("shapeshift_prompts", []):
        remove_prompt(mcp, pname)
    session["shapeshift_prompts"] = []

    session["current_form"] = None
    return removed


def _register_proxy_resources(transport: "BaseTransport", resources: list[dict]) -> list[str]:
    """Proxy static (non-template) resources from a transport.

    Returns normalized URI strings that were successfully registered.
    Template URIs (containing {param} placeholders) are skipped — they require
    parameter binding that is out of scope for basic proxying.
    """
    registered = []
    for res in resources:
        uri = res.get("uri", "")
        if not uri or _URI_TEMPLATE_RE.search(uri):
            continue
        name = res.get("name") or uri
        description = (res.get("description") or "")[:120]
        mime_type = res.get("mimeType") or "text/plain"
        _uri, _t = uri, transport

        async def _proxy(_u=_uri, _tr=_t) -> str:  # no type annotations — validate_call would reject BaseTransport
            try:
                return await _tr.read_resource(_u)
            except Exception as e:
                return f"[Resource unavailable: {e}]"

        _proxy.__name__ = name  # type: ignore[attr-defined]
        try:
            r = _FunctionResource.from_function(
                fn=_proxy, uri=_uri, name=name, description=description, mime_type=mime_type,
            )
            mcp.add_resource(r)
            registered.append(str(r.uri))
        except Exception:
            pass
    return registered


def _register_proxy_prompts(transport: "BaseTransport", prompts: list[dict]) -> list[str]:
    """Proxy prompts from a transport.

    Returns list of registered prompt names.
    Builds a proper __signature__ so FastMCP sees the correct argument list.
    """
    registered = []
    for prompt_schema in prompts:
        name = prompt_schema.get("name", "")
        if not name:
            continue
        description = (prompt_schema.get("description") or "")[:120]
        args_schema = prompt_schema.get("arguments", [])
        _name, _t = name, transport

        async def _proxy(**kwargs) -> str:  # noqa: B023
            messages = await _t.get_prompt(_name, kwargs)  # noqa: B023
            return "\n---\n".join(
                f"[{m.get('role', 'user')}]: {m.get('content', {}).get('text', '')}"
                for m in messages
                if isinstance(m, dict)
            )

        # Build named parameter signature so FastMCP / Pydantic see correct arguments.
        # MUST set both __signature__ (for inspect) and __annotations__ (for Pydantic's
        # get_type_hints()) — Prompt.from_function calls validate_call which reads both.
        params = []
        annotations: dict[str, type] = {"return": str}
        for arg in args_schema:
            arg_name = arg.get("name", "")
            if not arg_name:
                continue
            default = _inspect.Parameter.empty if arg.get("required") else ""
            params.append(_inspect.Parameter(
                arg_name, _inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=default, annotation=str,
            ))
            annotations[arg_name] = str
        _proxy.__signature__ = _inspect.Signature(params)  # type: ignore[attr-defined]
        _proxy.__annotations__ = annotations  # type: ignore[attr-defined]
        _proxy.__name__ = name  # type: ignore[attr-defined]
        _proxy.__doc__ = description

        try:
            p = _Prompt.from_function(fn=_proxy, name=name, description=description)
            mcp.add_prompt(p)
            registered.append(name)
        except Exception:
            pass
    return registered


def _proxy_name_for(server_id: str, raw_name: str, base_tool_names: set | None) -> str:
    """Translate a raw tool name to the name it will be registered under (handles collisions)."""
    if base_tool_names and raw_name in base_tool_names:
        sanitized = re.sub(r'[^a-z0-9_]', '_', server_id.lower())
        return f"{sanitized}_{raw_name}"
    return raw_name


def _register_proxy_tools(
    server_id: str, tools: list, transport: "BaseTransport", config: dict,
    base_tool_names: set = None,
    only: set[str] | None = None,
) -> list[str]:
    """Register proxy tools for a server, handling name collisions with base tools.

    only: if provided, only register tools whose names are in this set (lean shapeshift).
    """
    registered = []
    for tool_schema in tools:
        raw_name = tool_schema.get("name", "")
        if not raw_name:
            continue
        if only is not None and raw_name not in only:
            continue
        proxy_name = _proxy_name_for(server_id, raw_name, base_tool_names)
        proxy = _make_proxy(server_id, tool_schema, transport, config, proxy_name)
        try:
            mcp.add_tool(proxy)
            registered.append(proxy_name)
        except Exception:
            pass
    return registered
