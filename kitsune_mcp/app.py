from mcp.server.fastmcp import FastMCP

from kitsune_mcp._fastmcp_compat import _assert_internals

mcp = FastMCP("kitsune")
_assert_internals(mcp)
