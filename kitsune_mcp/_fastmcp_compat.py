"""Isolated access to FastMCP private API.

FastMCP exposes `add_resource` / `add_prompt` but no public removal. We reach
into `_resource_manager._resources` and `_prompt_manager._prompts` to undo
shapeshift registrations. This module is the single point of contact — if
FastMCP's internals change, only this file fails, and the assertions below
fail at import time rather than silently no-op'ing at runtime.

If/when FastMCP adds public `remove_resource` / `remove_prompt`, replace the
bodies here with the public calls and delete the assertions.
"""

from typing import Any


def _assert_internals(mcp: Any) -> None:
    """Verify FastMCP still has the private fields we depend on."""
    rm = getattr(mcp, "_resource_manager", None)
    pm = getattr(mcp, "_prompt_manager", None)
    if rm is None or not hasattr(rm, "_resources"):
        raise RuntimeError(
            "FastMCP internals changed: _resource_manager._resources missing. "
            "Update kitsune_mcp/_fastmcp_compat.py."
        )
    if pm is None or not hasattr(pm, "_prompts"):
        raise RuntimeError(
            "FastMCP internals changed: _prompt_manager._prompts missing. "
            "Update kitsune_mcp/_fastmcp_compat.py."
        )


def remove_resource(mcp: Any, uri: str) -> bool:
    """Unregister a resource by URI. Returns True if it was present."""
    rm = getattr(mcp, "_resource_manager", None)
    if rm is None:
        return False
    return rm._resources.pop(uri, None) is not None


def remove_prompt(mcp: Any, name: str) -> bool:
    """Unregister a prompt by name. Returns True if it was present."""
    pm = getattr(mcp, "_prompt_manager", None)
    if pm is None:
        return False
    return pm._prompts.pop(name, None) is not None
