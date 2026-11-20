"""Private SDK registration helpers.

MCPServer has public remove_tool and remove_prompt, but no remove_resource and
no way to add a pre-built Tool, so those two still reach into its managers.
"""

from typing import Any


def _assert_internals(mcp: Any) -> None:
    """Verify MCPServer still has the private fields we depend on."""
    rm = getattr(mcp, "_resource_manager", None)
    if rm is None or not hasattr(rm, "_resources"):
        raise RuntimeError(
            "MCPServer internals changed: _resource_manager._resources missing. "
            "Update kitsune_mcp/_fastmcp_compat.py."
        )


def remove_resource(mcp: Any, uri: str) -> bool:
    """Unregister a resource by URI. Returns True if it was present."""
    rm = getattr(mcp, "_resource_manager", None)
    if rm is None:
        return False
    return rm._resources.pop(uri, None) is not None


def add_tool_object(mcp: Any, tool: Any) -> bool:
    """Register a pre-built Tool (MCPServer only builds them from functions).

    Returns False if a tool with that name exists, matching add_tool(), which
    keeps the existing one.
    """
    tm = getattr(mcp, "_tool_manager", None)
    if tm is None or not hasattr(tm, "_tools"):
        raise RuntimeError(
            "MCPServer internals changed: _tool_manager._tools missing. "
            "Update kitsune_mcp/_fastmcp_compat.py."
        )
    if tool.name in tm._tools:
        return False
    tm._tools[tool.name] = tool
    return True
