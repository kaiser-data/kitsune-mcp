"""Tests for reload() — the one-call MCP REPL (release + connect + remount).

reload('dev') removes the "connect() handed back the old process" footgun by
always releasing the stale process first, then restarting fresh code and
remounting so the client sees the new schemas.
"""
import importlib
import json
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.conftest import make_mock_process  # noqa: E402


def _seed_connection(name="dev", command="uvx --from . my-mcp-server"):
    """Put a live pool entry + session connection in place, as connect() would."""
    from kitsune_mcp.session import session
    from kitsune_mcp.transport import _PoolEntry, _process_pool

    install_cmd = ["uvx", "--from", ".", "my-mcp-server"]
    pool_key = json.dumps(install_cmd, sort_keys=True)
    entry = _PoolEntry(proc=make_mock_process(), install_cmd=install_cmd, started_at=0.0)
    entry.name = name
    _process_pool[pool_key] = entry
    session["connections"][pool_key] = {
        "name": name,
        "command": command,
        "install_cmd": install_cmd,
        "pid": entry.pid(),
        "started_at": 0.0,
        "tools": ["summarize"],
    }
    return pool_key, entry


# ---------------------------------------------------------------------------
# Profile: reload is lean, alongside connect/release
# ---------------------------------------------------------------------------

class TestReloadProfile:
    def test_reload_in_base_tools(self):
        from kitsune_mcp.tools._state import _BASE_TOOL_NAMES
        assert "reload" in _BASE_TOOL_NAMES

    def test_repl_trio_in_lean(self):
        from kitsune_mcp.tools._state import _LEAN_TOOL_NAMES
        assert {"connect", "release", "reload"} <= _LEAN_TOOL_NAMES


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

class TestReload:
    @pytest.mark.asyncio
    async def test_reloads_release_then_connect_then_remount(self):
        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")

        _seed_connection()
        calls = []

        async def _release(name):
            calls.append(("release", name))
            return f"Released: {name} (PID 99999) | uptime: 1s | calls: 0"

        async def _connect(command, name=""):
            calls.append(("connect", command, name))
            return f"Connected: {name} (PID 12345)\nTools (1): summarize"

        async def _shapeshift(server_id="", ctx=None, **kw):
            calls.append(("shapeshift", server_id))
            return "Now: dev | 1 tool"

        with (
            patch.object(ss, "release", _release),
            patch.object(ss, "connect", _connect),
            patch.object(ss, "shapeshift", _shapeshift),
        ):
            out = await ss.reload("dev")

        # Order matters: release BEFORE connect (this is the footgun fix).
        assert [c[0] for c in calls] == ["release", "connect", "shapeshift"]
        assert calls[1] == ("connect", "uvx --from . my-mcp-server", "dev")
        assert calls[2] == ("shapeshift", "dev")
        assert "Reloaded: dev" in out
        assert "was PID 99999" in out

    @pytest.mark.asyncio
    async def test_unknown_name_lists_active(self):
        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")

        _seed_connection(name="dev")
        out = await ss.reload("nope")
        assert "No connection named 'nope'" in out
        assert "dev" in out

    @pytest.mark.asyncio
    async def test_no_connections_at_all(self):
        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")
        from kitsune_mcp.transport import _process_pool

        _process_pool.clear()
        out = await ss.reload("dev")
        assert "No active connections" in out

    @pytest.mark.asyncio
    async def test_missing_stored_command_is_reported(self):
        from kitsune_mcp.session import session
        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")

        pool_key, _ = _seed_connection(name="dev")
        # Simulate a pre-reload connection with no stored command.
        session["connections"][pool_key].pop("command", None)

        out = await ss.reload("dev")
        assert "Cannot reload 'dev'" in out
        assert "connect(" in out

    @pytest.mark.asyncio
    async def test_connect_failure_surfaces_and_skips_remount(self):
        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")

        _seed_connection()
        remounted = []

        async def _release(name):
            return "Released: dev (PID 99999) | uptime: 1s | calls: 0"

        async def _connect(command, name=""):
            return "Timeout starting 'uvx --from . my-mcp-server' after 60s."

        async def _shapeshift(server_id="", ctx=None, **kw):
            remounted.append(server_id)
            return "should not happen"

        with (
            patch.object(ss, "release", _release),
            patch.object(ss, "connect", _connect),
            patch.object(ss, "shapeshift", _shapeshift),
        ):
            out = await ss.reload("dev")

        assert "could not restart" in out
        assert "Timeout" in out
        assert remounted == []  # remount skipped when the fresh process failed
