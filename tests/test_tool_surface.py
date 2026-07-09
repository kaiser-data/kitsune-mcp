"""Integration tests: lean vs forge tool surface (#28).

Guards against profile drift — tools silently added to or removed from the
lean profile without updating docs/onboarding examples.
"""
import os

# ---------------------------------------------------------------------------
# Helpers — import server with a clean tool registry each time
# ---------------------------------------------------------------------------

def _get_registered_tools(kitsune_tools_env: str) -> set[str]:
    """Import server.py with KITSUNE_TOOLS set to the given value and return
    the set of tool names currently registered with the FastMCP app."""
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
    "shapeshift", "search", "auth", "call", "status", "auto",
}

# Tools that must NOT appear in lean (forge-only)
FORGE_ONLY = {
    "shiftback", "inspect", "compare", "key", "onboard",
    "run", "fetch", "craft", "connect", "release",
    "test", "bench", "setup",
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


def test_auth_is_in_lean():
    """auth replaces key+login in the lean profile."""
    from server import _LEAN_TOOLS
    assert "auth" in _LEAN_TOOLS, "auth must be in lean profile"


def test_auto_is_in_lean():
    """auto moved to lean profile in v0.19."""
    from server import _LEAN_TOOLS
    assert "auto" in _LEAN_TOOLS, "auto must be in lean profile (v0.19+)"


def test_base_tool_names_covers_lean_and_forge():
    """_BASE_TOOL_NAMES must be the superset of lean + forge."""
    from kitsune_mcp.tools._state import _BASE_TOOL_NAMES
    from server import _LEAN_TOOLS
    uncovered = _LEAN_TOOLS - _BASE_TOOL_NAMES
    assert not uncovered, f"Lean tools not in _BASE_TOOL_NAMES: {uncovered}"


def test_lean_tools_documented_count():
    """Lean profile is exactly 6 tools — catch silent drift."""
    from server import _LEAN_TOOLS
    assert len(_LEAN_TOOLS) == 6, (
        f"Lean tool count changed to {len(_LEAN_TOOLS)} — update server.py header comment "
        f"and this test. Lean tools: {sorted(_LEAN_TOOLS)}"
    )


# ---------------------------------------------------------------------------
# _active_tool_names() — shared profile resolution
# ---------------------------------------------------------------------------

def test_active_tool_names_default_is_lean(monkeypatch):
    from kitsune_mcp.tools._state import _LEAN_TOOL_NAMES, _active_tool_names
    monkeypatch.delenv("KITSUNE_TOOLS", raising=False)
    assert _active_tool_names() == _LEAN_TOOL_NAMES


def test_active_tool_names_all_is_full_surface(monkeypatch):
    from kitsune_mcp.tools._state import _BASE_TOOL_NAMES, _active_tool_names
    monkeypatch.setenv("KITSUNE_TOOLS", "all")
    assert _active_tool_names() == _BASE_TOOL_NAMES


def test_active_tool_names_custom_subset_intersects_base(monkeypatch):
    from kitsune_mcp.tools._state import _active_tool_names
    monkeypatch.setenv("KITSUNE_TOOLS", "shapeshift, call, not-a-real-tool")
    assert _active_tool_names() == {"shapeshift", "call"}


# ---------------------------------------------------------------------------
# GATEWAY bloat hint — must only recommend tools in the active profile
# ---------------------------------------------------------------------------

def _fake_client_config():
    from pathlib import Path

    from kitsune_mcp.gateway import AbsorbedServer, ClientConfig
    return ClientConfig(
        client="test-client",
        path=Path("/dev/null"),
        servers=[AbsorbedServer(id="github", command="npx", client="test-client")],
    )


async def _status_with_competing_server():
    from unittest import mock

    from kitsune_mcp.tools import status
    with (
        mock.patch("kitsune_mcp.gateway._find_mcp_configs", return_value=[_fake_client_config()]),
        mock.patch("kitsune_mcp.gateway._load_absorbed_servers", return_value=[]),
    ):
        return await status()


async def test_gateway_hint_lean_profile_does_not_recommend_setup(monkeypatch):
    """Lean profile has no setup() — the hint must point to KITSUNE_TOOLS=all instead."""
    monkeypatch.delenv("KITSUNE_TOOLS", raising=False)
    result = await _status_with_competing_server()
    assert "GATEWAY" in result
    assert "Run setup()" not in result
    assert "KITSUNE_TOOLS=all" in result


async def test_gateway_hint_forge_profile_recommends_setup(monkeypatch):
    """With the full surface active, setup() exists and the hint may name it directly."""
    monkeypatch.setenv("KITSUNE_TOOLS", "all")
    result = await _status_with_competing_server()
    assert "GATEWAY" in result
    assert "Run setup()" in result
