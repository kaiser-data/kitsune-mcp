"""shapeshift keeps the current server when none of the new tools can be registered."""

from unittest.mock import AsyncMock, MagicMock, patch

from kitsune_mcp import shapeshift as core
from kitsune_mcp.app import mcp
from server import ServerInfo, _registry, session, shapeshift

_T = {"name": "t", "description": "", "inputSchema": {"type": "object", "properties": {}}}


def _check(tools, only=None):
    return core._registrable_tools("org/new", tools, MagicMock(), {}, set(), only)


def test_tools_filter_matching_nothing_registers_nothing():
    assert _check([_T], only={"other"}) == []


def test_name_held_by_an_unrelated_tool_is_not_registrable(monkeypatch):
    monkeypatch.setitem(mcp._tool_manager._tools, "t", object())
    monkeypatch.setitem(session, "shapeshift_tools", [])
    assert _check([_T]) == []


def test_name_held_by_the_current_form_is_free(monkeypatch):
    """The current server is shed right before registering, so its names free up."""
    monkeypatch.setitem(mcp._tool_manager._tools, "t", object())
    monkeypatch.setitem(session, "shapeshift_tools", ["t"])
    assert _check([_T]) == ["t"]


def test_a_schema_that_cannot_be_built_is_not_registrable():
    with patch.object(core, "_make_proxy_tool", side_effect=ValueError("bad schema")):
        assert _check([_T]) == []


def test_check_registers_nothing():
    before = set(mcp._tool_manager._tools)
    assert _check([_T]) == ["t"]
    assert set(mcp._tool_manager._tools) == before


async def test_shapeshift_keeps_current_form_when_nothing_would_register():
    srv = ServerInfo(
        id="org/new",
        name="new",
        description="",
        source="official",
        transport="stdio",
        url="",
        install_cmd=["npx", "-y", "new"],
        credentials={},
        tools=[],
        token_cost=0,
    )
    shed = MagicMock(return_value=[])
    with (
        patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
        patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT,
        patch("kitsune_mcp.tools._state._do_shed", shed),
    ):
        MockT.return_value.list_tools = AsyncMock(return_value=[_T])
        out = await shapeshift("org/new", MagicMock(), tools=["does_not_exist"])
    assert out.startswith("❌") and "could be registered" in out
    shed.assert_not_called()
