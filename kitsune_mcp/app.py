import asyncio

from mcp.server.fastmcp import FastMCP

from kitsune_mcp._fastmcp_compat import _assert_internals

mcp = FastMCP("kitsune")
_assert_internals(mcp)

# Guards all mutations to the tool registry (mcp.add_tool / remove_tool) and the
# session state that mirrors it (shapeshift_tools, current_form, etc.).
# Held from _do_shed() through the end of _commit_shapeshift() so that a concurrent
# shapeshift cannot interleave between "shed old tools" and "register new tools",
# which would leave orphaned tools that shiftback() can never clean up.
_registry_lock = asyncio.Lock()
