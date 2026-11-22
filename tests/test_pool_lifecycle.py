"""Pool lifecycle: one start per key, no orphans on failed start, no eviction mid-call."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import kitsune_mcp.credentials as _creds
import kitsune_mcp.transport as tr
from kitsune_mcp.transport import PersistentStdioTransport, _PoolEntry, _process_pool

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {}},
}


def _proc(stdout=None):
    proc = MagicMock()
    proc.returncode = None
    proc.pid = 99999
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdout = stdout or MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


def _slow_stdout(responses):
    lines = iter((json.dumps(r) + "\n").encode() for r in responses)

    async def readline():
        await asyncio.sleep(0.02)  # let a concurrent caller run meanwhile
        return next(lines, b"")

    out = MagicMock()
    out.readline = readline
    return out


def _hanging_stdout():
    async def readline():
        await asyncio.Event().wait()

    out = MagicMock()
    out.readline = readline
    return out


def _entry(proc, age=0.0):
    e = _PoolEntry(proc=proc, install_cmd=["x"], started_at=time.monotonic())
    e.last_used_at = time.monotonic() - age
    return e


class TestSingleStartPerKey:
    async def test_concurrent_first_calls_spawn_one_process(self):
        spawned = []

        async def spawn(*a, **kw):
            p = _proc(_slow_stdout([_INIT]))
            spawned.append(p)
            return p

        with patch("asyncio.create_subprocess_exec", side_effect=spawn):
            t = PersistentStdioTransport(["race-cmd"])
            e1, e2 = await asyncio.gather(t._get_or_start(), t._get_or_start())

        assert len(spawned) == 1, "second caller spawned an orphan process"
        assert e1 is e2


class TestFailedStartKillsChild:
    async def test_cancelled_handshake_kills_child(self):
        proc = _proc(_hanging_stdout())
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            t = PersistentStdioTransport(["cancel-cmd"])
            task = asyncio.create_task(t._start_process())
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        proc.kill.assert_called()
        assert t._pool_key not in _process_pool

    async def test_broken_pipe_during_handshake_kills_child(self):
        proc = _proc()
        proc.stdin.drain = AsyncMock(side_effect=BrokenPipeError())
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            t = PersistentStdioTransport(["pipe-cmd"])
            with pytest.raises(RuntimeError, match="exited during the MCP handshake"):
                await t._start_process()
        proc.kill.assert_called()
        assert t._pool_key not in _process_pool


class TestNoEvictionMidCall:
    async def test_idle_sweep_skips_entry_with_call_in_flight(self):
        proc = _proc()
        e = _entry(proc, age=tr.POOL_MAX_IDLE_SECONDS + 100)
        _process_pool["busy"] = e
        async with e.lock:
            tr._evict_stale_pool_entries(force=True)
        assert "busy" in _process_pool
        proc.kill.assert_not_called()

    async def test_cap_sweep_skips_entry_with_call_in_flight(self):
        busy, idle = _proc(), _proc()
        eb, ei = _entry(busy, age=50), _entry(idle, age=10)
        _process_pool["busy"], _process_pool["idle"] = eb, ei
        with patch.object(tr, "POOL_MAX_PROCESSES", 1):
            async with eb.lock:
                tr._evict_stale_pool_entries(force=True)
        busy.kill.assert_not_called()
        idle.kill.assert_called()
        assert list(_process_pool) == ["busy"]

    async def test_call_start_counts_as_use(self):
        """A call that starts now must not look idle to a sweep that runs mid-call."""
        proc = _proc(_hanging_stdout())
        t = PersistentStdioTransport(["long-cmd"])
        e = _entry(proc, age=tr.POOL_MAX_IDLE_SECONDS + 100)
        e.dotenv_revision = _creds._dotenv_revision
        _process_pool[t._pool_key] = e
        task = asyncio.create_task(t.call_tool("slow", {}, {}))
        await asyncio.sleep(0.05)
        assert time.monotonic() - e.last_used_at < 5
        task.cancel()

    async def test_dotenv_change_does_not_kill_busy_process(self):
        proc = _proc()
        t = PersistentStdioTransport(["env-cmd"])
        e = _entry(proc)
        e.dotenv_revision = _creds._dotenv_revision - 1
        _process_pool[t._pool_key] = e
        async with e.lock:
            got = await t._get_or_start()
        assert got is e
        proc.kill.assert_not_called()
