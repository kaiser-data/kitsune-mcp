"""Integration tests: lean vs forge tool surface (#28).

Guards against profile drift — tools silently added to or removed from the
lean profile without updating docs/onboarding examples.
"""
import os
import contextlib

import pytest


# ---------------------------------------------------------------------------
# Helpers — import server with a clean tool registry each time
# ---------------------------------------------------------------------------

def _get_registered_tools(kitsune_tools_env: str) -> set[str]:
    """Import server.py with KITSUNE_TOOLS set to the given value and return
    the set of tool names currently registered with the FastMCP app."""
    import importlib
    import sys

    # Patch env before importing
    old = os.environ.get("KITSUNE_TOOLS")
    if kitsune_tools_env:
        os.environ["KITSUNE_TOOLS"] = kitsune_tools_env
    else:
        os.environ.pop("KITSUNE_TOOLS", None)

    try:
        # Force reimport of server and all tool modules so the profile pruning
        # runs again with the new env value.
        for mod in list(sys.modules.keys()):
            if mod == "server" or mod.startswith("kitsune_mcp.tools"):
                sys.modules.pop(mod, None)

        import server  # noqa: F401 — side effects register/prune tools
        from kitsune_mcp.app import mcp
        # FastMCP exposes registered tools via ._tool_manager or similar; use the
        # public list_tools() sync path if available, else inspect internals.
        try:
            tools = mcp.list_tools()
            if hasattr(tools, "__await__"):
                import asyncio
                tools = asyncio.get_event_loop().run_until_complete(tools)
            return {t.name for t in tools}
        except Exception:
            # Fallback: read from internal dict
            mgr = getattr(mcp, "_tool_manager", None) or getattr(mcp, "_tools", {})
            if hasattr(mgr, "_tools"):
                return set(mgr._tools.keys())
            if isinstance(mgr, dict):
                return set(mgr.keys())
            return set()
    finally:
        if old is not None:
            os.environ["KITSUNE_TOOLS"] = old
        else:
            os.environ.pop("KITSUNE_TOOLS", None)


# ---------------------------------------------------------------------------
# Expected surfaces
# ---------------------------------------------------------------------------

LEAN_REQUIRED = {
    "shapeshift", "shiftback", "search", "inspect",
    "compare", "call", "auto", "key", "status",
}

# Tools that must NOT appear in lean (forge-only)
FORGE_ONLY = {
    "run", "fetch", "craft", "connect", "release",
    "test", "bench", "setup", "onboard",
}

ALL_TOOLS = LEAN_REQUIRED | FORGE_ONLY


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_lean_profile_has_required_tools():
    """Lean profile must expose exactly the core discovery + hub tools."""
    from server import _LEAN_TOOLS
    missing = LEAN_REQUIRED - _LEAN_TOOLS
    assert not missing, f"Lean profile is missing expected tools: {missing}"


def test_lean_profile_excludes_forge_only_tools():
    """Forge-only tools must not be in the lean profile."""
    from server import _LEAN_TOOLS
    leaked = FORGE_ONLY & _LEAN_TOOLS
    assert not leaked, f"Forge-only tools leaked into lean profile: {leaked}"


def test_compare_is_in_lean():
    """compare is a discovery tool and must be in the lean profile (#24)."""
    from server import _LEAN_TOOLS
    assert "compare" in _LEAN_TOOLS, "compare must be in lean profile"


def test_auto_is_in_lean():
    """auto is a core UX tool and must be in the lean profile."""
    from server import _LEAN_TOOLS
    assert "auto" in _LEAN_TOOLS, "auto must be in lean profile"


def test_base_tool_names_covers_lean_and_forge():
    """_BASE_TOOL_NAMES must be the superset of lean + forge."""
    from kitsune_mcp.tools._state import _BASE_TOOL_NAMES
    from server import _LEAN_TOOLS
    uncovered = _LEAN_TOOLS - _BASE_TOOL_NAMES
    assert not uncovered, f"Lean tools not in _BASE_TOOL_NAMES: {uncovered}"


def test_lean_tools_documented_count():
    """Lean profile size is documented in server.py header — catch silent drift."""
    from server import _LEAN_TOOLS
    # If this changes, update the server.py docstring and this assertion together.
    assert len(_LEAN_TOOLS) == 9, (
        f"Lean tool count changed to {len(_LEAN_TOOLS)} — update server.py header comment "
        f"and this test. Lean tools: {sorted(_LEAN_TOOLS)}"
    )
