"""test() scores the server you are building, not just registry packages.

Before: test('dev') on a connect()'d local server answered "Server not found in
registry — Poor", which contradicts the pitch (an agent testing the MCP server it is
building). Now a live connect() alias is scored on what a developer can fix: tool
descriptions, parameter descriptions, schema shape and name collisions, with a
per-tool fix list.
"""

import json
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.conftest import make_mock_process  # noqa: E402

GOOD_TOOL = {
    "name": "get_forecast",
    "description": "Return the 3-day weather forecast for a city.",
    "inputSchema": {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City name, e.g. 'Berlin'"}},
        "required": ["city"],
    },
}
BAD_TOOL = {
    "name": "do_it",
    "description": "",
    "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}},
}


@pytest.fixture
def dev_connection():
    """A live connect('uv run server.py', name='dev') as connect() leaves it."""
    from kitsune_mcp.session import session
    from kitsune_mcp.transport import _PoolEntry, _process_pool

    install_cmd = ["uv", "run", "server.py"]
    pool_key = json.dumps(install_cmd, sort_keys=True)
    entry = _PoolEntry(proc=make_mock_process(), install_cmd=install_cmd, started_at=0.0)
    entry.name = "dev"
    _process_pool[pool_key] = entry
    session["connections"][pool_key] = {"name": "dev", "command": "uv run server.py"}
    yield pool_key
    _process_pool.pop(pool_key, None)
    session["connections"].pop(pool_key, None)


def _tools(*tools):
    return patch(
        "kitsune_mcp.transport.PersistentStdioTransport.list_tools",
        AsyncMock(return_value=list(tools)),
    )


def _no_registry():
    return patch(
        "kitsune_mcp.tools._state._registry.get_server",
        AsyncMock(side_effect=AssertionError("a connect() alias must not hit registries")),
    )


@pytest.mark.asyncio
async def test_connected_server_is_scored_not_rejected(dev_connection):
    from kitsune_mcp.tools import exec as exec_mod

    with _tools(GOOD_TOOL), _no_registry():
        out = await exec_mod.test("dev")
    assert "not found in registry" not in out
    assert out.startswith("Score: 100/100 (Excellent) — dev (local)")


@pytest.mark.asyncio
async def test_weak_definitions_lower_score_and_name_the_fix(dev_connection):
    from kitsune_mcp.tools import exec as exec_mod

    with _tools(GOOD_TOOL, BAD_TOOL), _no_registry():
        out = await exec_mod.test("dev")
    score = int(out.split("/100")[0].removeprefix("Score: "))
    assert score < 90
    assert "do_it: add a tool description" in out
    assert "do_it.x: add a parameter description" in out
    assert "do_it: declare 'required'" in out
    assert "get_forecast" not in out.split("Fix list:")[1]


@pytest.mark.asyncio
async def test_collision_with_base_tool_is_flagged(dev_connection):
    from kitsune_mcp.tools import exec as exec_mod

    clash = dict(GOOD_TOOL, name="call")
    with _tools(clash), _no_registry():
        out = await exec_mod.test("dev")
    assert "call: rename" in out


@pytest.mark.asyncio
async def test_no_tools_is_poor(dev_connection):
    from kitsune_mcp.tools import exec as exec_mod

    with _tools(), _no_registry():
        out = await exec_mod.test("dev")
    assert out.startswith("Score: 0/100 (Poor)")
    assert "tools/list returned no tools" in out


@pytest.mark.asyncio
async def test_full_mode_calls_tools_on_the_connected_process(dev_connection):
    from kitsune_mcp.tools import exec as exec_mod

    execute = AsyncMock(return_value="sunny")
    with (
        _tools(GOOD_TOOL),
        _no_registry(),
        patch("kitsune_mcp.transport.PersistentStdioTransport.execute", execute),
    ):
        out = await exec_mod.test("dev", level="full")
    execute.assert_awaited_once()
    assert execute.await_args.args[:2] == ("get_forecast", {"city": "test"})
    assert "get_forecast() callable" in out
    assert out.startswith("Score: 100/100")


@pytest.mark.asyncio
async def test_full_mode_failing_tool_halves_score(dev_connection):
    from kitsune_mcp.tools import exec as exec_mod

    execute = AsyncMock(return_value="Error: boom")
    with (
        _tools(GOOD_TOOL),
        _no_registry(),
        patch("kitsune_mcp.transport.PersistentStdioTransport.execute", execute),
    ):
        out = await exec_mod.test("dev", level="full")
    assert out.startswith("Score: 50/100")


@pytest.mark.asyncio
async def test_dead_connection_falls_back_to_registry(dev_connection):
    """A connection row restored from state.json has no process: don't score it."""
    from kitsune_mcp.tools import exec as exec_mod
    from kitsune_mcp.transport import _process_pool

    _process_pool.pop(dev_connection)
    with patch("kitsune_mcp.tools._state._registry.get_server", AsyncMock(return_value=None)):
        out = await exec_mod.test("dev")
    assert "not found in registry" in out
    assert "connect(" in out  # the miss explains how to test a local server
