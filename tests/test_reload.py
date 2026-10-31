"""Tests for reload() — the one-call MCP REPL (release + connect + remount).

reload('dev') removes the "connect() handed back the old process" footgun by
always releasing the stale process first, then restarting fresh code and
remounting so the client sees the new schemas.
"""

import importlib
import json
import os
import sys
from unittest.mock import MagicMock, patch

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

        async def _connect(command, name="", **kw):
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
        from kitsune_mcp.session import session
        from kitsune_mcp.transport import _process_pool

        _process_pool.clear()
        session["connections"].clear()  # a stored launch record alone is reloadable
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

        async def _connect(command, name="", **kw):
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


class TestReloadRecovery:
    """Codex P1: reload keeps launch settings, survives a failed restart, and
    doesn't claim a remount that failed."""

    @pytest.mark.asyncio
    async def test_reload_keeps_custom_launch_settings(self):
        from kitsune_mcp.session import session

        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")
        pool_key, _ = _seed_connection()
        session["connections"][pool_key].update({"timeout": 180, "inherit_stderr": False})
        seen = {}

        async def _connect(command, name="", **kw):
            seen.update(kw)
            return f"Connected: {name} (PID 1)"

        async def _shapeshift(server_id="", ctx=None, **kw):
            return "Now: dev"

        with (
            patch.object(ss, "release", MagicMock(side_effect=_async("Released: dev"))),
            patch.object(ss, "connect", _connect),
            patch.object(ss, "shapeshift", _shapeshift),
        ):
            await ss.reload("dev")
        assert seen == {"timeout": 180, "inherit_stderr": False}

    @pytest.mark.asyncio
    async def test_failed_restart_can_be_retried_with_reload(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.transport import _process_pool

        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")
        pool_key, _ = _seed_connection()
        attempts = []

        async def _connect(command, name="", **kw):
            attempts.append(command)
            if len(attempts) == 1:
                return "SyntaxError in my_mcp_server.py line 3"
            return f"Connected: {name} (PID 2)"

        async def _shapeshift(server_id="", ctx=None, **kw):
            return "Now: dev"

        try:
            with (
                patch.object(ss, "connect", _connect),
                patch.object(ss, "shapeshift", _shapeshift),
                patch.object(ss, "_kill_process_tree", MagicMock()),
            ):
                first = await ss.reload("dev")
                assert "could not restart" in first
                assert pool_key not in _process_pool  # old process is gone
                second = await ss.reload("dev")  # fixed the syntax error, retry
        finally:
            _process_pool.pop(pool_key, None)
            session["connections"].pop(pool_key, None)
        assert attempts == ["uvx --from . my-mcp-server"] * 2
        assert "Reloaded: dev" in second

    @pytest.mark.asyncio
    async def test_failed_remount_is_not_reported_as_remounted(self):
        ss = importlib.import_module("kitsune_mcp.tools.shapeshift")
        _seed_connection()

        async def _connect(command, name="", **kw):
            return f"Connected: {name} (PID 3)"

        async def _shapeshift(server_id="", ctx=None, **kw):
            return "❌ shapeshift failed: no tools could be registered from 'dev'."

        with (
            patch.object(ss, "release", MagicMock(side_effect=_async("Released: dev"))),
            patch.object(ss, "connect", _connect),
            patch.object(ss, "shapeshift", _shapeshift),
        ):
            out = await ss.reload("dev")
        assert "remounted" not in out.lower().split("\n")[0]
        assert "remount failed" in out.lower()
        assert "❌ shapeshift failed" in out


def _async(value):
    async def _f(*a, **k):
        return value

    return _f


# ---------------------------------------------------------------------------
# call() on a connect() alias stays local
# ---------------------------------------------------------------------------


class TestCallOnConnectAlias:
    """call() must not resolve a connect() alias like 'dev' in the registries.

    Regression: an npm package named 'dev' lent the user's own server its
    credentials and a '[source: npm]' label.
    """

    async def test_alias_skips_registry_and_uses_pool(self):
        from unittest.mock import AsyncMock

        from kitsune_mcp.session import session
        from kitsune_mcp.tools import _state
        from kitsune_mcp.transport import PersistentStdioTransport, _process_pool

        call_mod = sys.modules["kitsune_mcp.tools.exec"]
        pool_key, _ = _seed_connection()
        registry_lookup = AsyncMock()
        used_keys = []

        async def execute(self, tool_name, arguments, config):
            used_keys.append(self._pool_key)
            return "Berlin: 15°C"

        try:
            with (
                patch.object(_state._registry, "get_server", registry_lookup),
                patch.object(PersistentStdioTransport, "execute", execute),
            ):
                out = await call_mod.call(
                    "get_weather", server_id="dev", arguments={"city": "Berlin"}
                )
        finally:
            _process_pool.pop(pool_key, None)
            session["connections"].pop(pool_key, None)

        assert out == "Berlin: 15°C"
        registry_lookup.assert_not_called()
        assert used_keys == [pool_key]  # the connect()'d process, not a new one

    async def _call_dev(self, registry_lookup):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.transport import PersistentStdioTransport

        call_mod = sys.modules["kitsune_mcp.tools.exec"]
        used_keys = []

        async def execute(self, tool_name, arguments, config):
            used_keys.append(self._pool_key)
            return "ok"

        with (
            patch.object(_state._registry, "get_server", registry_lookup),
            patch.object(PersistentStdioTransport, "execute", execute),
        ):
            await call_mod.call("get_weather", server_id="dev", arguments={})
        return used_keys

    async def test_restored_row_without_process_is_ignored(self):
        """A connection row restored from state.json has no live process behind it."""
        from unittest.mock import AsyncMock

        from kitsune_mcp.session import session
        from kitsune_mcp.transport import _process_pool

        pool_key, _ = _seed_connection()
        _process_pool.pop(pool_key)  # the process died with the last server run
        registry_lookup = AsyncMock(return_value=None)
        try:
            with patch.object(
                sys.modules["kitsune_mcp.tools._state"],
                "transport_for_exec",
                lambda sid, srv: (MagicMock(execute=AsyncMock(return_value="ok")), ""),
            ):
                used = await self._call_dev(registry_lookup)
        finally:
            session["connections"].pop(pool_key, None)

        registry_lookup.assert_awaited_once()
        assert used == []  # no transport built from the dead row's command

    async def test_live_connect_wins_over_mounted_form_with_same_name(self):
        from unittest.mock import AsyncMock

        from kitsune_mcp.session import session
        from kitsune_mcp.transport import _process_pool

        pool_key, _ = _seed_connection()
        other_key = json.dumps(["npx", "-y", "dev"], sort_keys=True)
        session["current_form"] = "dev"
        session["current_form_pool_key"] = other_key
        try:
            used = await self._call_dev(AsyncMock())
        finally:
            _process_pool.pop(pool_key, None)
            session["connections"].pop(pool_key, None)
            session["current_form"] = None
            session["current_form_pool_key"] = None

        assert used == [pool_key]
