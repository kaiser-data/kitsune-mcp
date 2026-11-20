import asyncio
from contextvars import ContextVar
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import Context, MCPServer

from kitsune_mcp import __version__
from kitsune_mcp._fastmcp_compat import _assert_internals

_request_context: ContextVar[ServerRequestContext[Any, Any] | None] = ContextVar(
    "kitsune_request_context", default=None
)


async def _bind_request(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
    token = _request_context.set(ctx)
    try:
        return await call_next(ctx)
    finally:
        _request_context.reset(token)


def get_context() -> Context:
    return Context(request_context=_request_context.get(), mcp_server=mcp)


mcp = MCPServer("kitsune", version=__version__, middleware=[_bind_request])
_assert_internals(mcp)

# Guards all mutations to the tool registry (mcp.add_tool / remove_tool) and the
# session state that mirrors it (shapeshift_tools, current_form, etc.).
# Held from _do_shed() through the end of _commit_shapeshift() so that a concurrent
# shapeshift cannot interleave between "shed old tools" and "register new tools",
# which would leave orphaned tools that shiftback() can never clean up.
_registry_lock = asyncio.Lock()
