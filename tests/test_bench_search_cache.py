"""bench() stops when a call may have run; partial searches are not cached (Grok review 2 #4, #11)."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import kitsune_mcp.tools.exec  # noqa: F401  (package re-exports a function of that name)
from kitsune_mcp.registry import MultiRegistry, ServerInfo
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import _outcome_unknown_message

ex = sys.modules["kitsune_mcp.tools.exec"]


def _srv():
    return ServerInfo(
        id="org/s",
        name="s",
        description="",
        source="official",
        transport="http",
        url="https://s.example/mcp",
        install_cmd=[],
        credentials={},
        tools=[],
        token_cost=0,
    )


async def _bench_with(execute, iterations=5, timeout=None):
    t = MagicMock()
    t.execute = execute
    with (
        patch.object(_state._registry, "get_server", AsyncMock(return_value=_srv())),
        patch.object(_state, "transport_for_exec", return_value=(t, "")),
        patch.object(ex, "guard_call", AsyncMock(return_value=None)),
    ):
        if timeout is not None:
            with patch.object(ex, "TIMEOUT_STDIO_TOOL", timeout):
                return await ex.bench("org/s", "delete_thing", {}, iterations)
        return await ex.bench("org/s", "delete_thing", {}, iterations)


async def test_bench_stops_after_outcome_unknown():
    calls = []

    async def execute(tool, args, config):
        calls.append(1)
        return _outcome_unknown_message(tool, "org/s", "no reply")

    out = await _bench_with(execute)
    assert len(calls) == 1
    assert "Stopped after call 1 of 5" in out


async def test_bench_stops_after_timeout():
    calls = []

    async def execute(tool, args, config):
        calls.append(1)
        if len(calls) == 2:
            await asyncio.sleep(5)
        return "ok"

    out = await _bench_with(execute, timeout=0.2)
    assert len(calls) == 2
    assert "Stopped after call 2 of 5" in out


async def test_search_with_a_failed_registry_is_not_cached():
    reg = MultiRegistry()
    ok = MagicMock()
    ok.search = AsyncMock(return_value=[_srv()])
    bad = MagicMock()
    bad.search = AsyncMock(side_effect=RuntimeError("npm down"))
    reg._registries = [ok, bad]
    reg._reg_names = ["ok", "bad"]
    await reg.search("thing", 5)
    await reg.search("thing", 5)
    assert bad.search.await_count == 2, "partial result was served from cache"
    assert reg.last_registry_errors == {"bad": "RuntimeError"}


async def test_complete_search_is_cached():
    reg = MultiRegistry()
    ok = MagicMock()
    ok.search = AsyncMock(return_value=[_srv()])
    reg._registries = [ok]
    reg._reg_names = ["ok"]
    await reg.search("thing", 5)
    await reg.search("thing", 5)
    assert ok.search.await_count == 1
