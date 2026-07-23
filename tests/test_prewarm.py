"""Tests for issue #41 — public prewarm() warm-pool API.

prewarm(server_id) starts a registry server's subprocess and adds it to the
pool WITHOUT mounting its tools — so a later shapeshift(server_id) skips the
npx/uvx cold-install latency and benchmarks don't measure install time.
"""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.conftest import make_mock_process  # noqa: E402


def _srv(**kwargs):
    from kitsune_mcp.registry import ServerInfo
    defaults = dict(
        id="mcp-server-time", name="Time Server", description="time tools",
        source="official", transport="stdio", url="",
        install_cmd=["npx", "-y", "mcp-server-time"], credentials={}, tools=[],
        token_cost=0,
    )
    defaults.update(kwargs)
    return ServerInfo(**defaults)


def _fake_persistent_transport(cmd, tools=None):
    """Mock PersistentStdioTransport whose list_tools() also creates a real
    pool entry — mirroring what the real transport does on first spawn."""
    from kitsune_mcp.transport import _PoolEntry, _process_pool
    transport = MagicMock()
    pool_key = json.dumps(cmd, sort_keys=True)

    async def _list_tools(*a, **kw):
        _process_pool[pool_key] = _PoolEntry(
            proc=make_mock_process(), install_cmd=cmd, started_at=0.0,
        )
        return tools if tools is not None else [
            {"name": "get_time", "description": "", "inputSchema": {}}
        ]

    transport.list_tools = AsyncMock(side_effect=_list_tools)
    return transport, pool_key


class TestPrewarmProfile:
    def test_prewarm_in_forge_profile(self):
        from kitsune_mcp.tools._state import _BASE_TOOL_NAMES
        assert "prewarm" in _BASE_TOOL_NAMES

    def test_prewarm_not_in_lean_profile(self):
        from kitsune_mcp.tools._state import _LEAN_TOOL_NAMES
        assert "prewarm" not in _LEAN_TOOL_NAMES


class TestPrewarm:
    @pytest.mark.asyncio
    async def test_spawns_pool_entry_without_mounting_tools(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.session import session
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        srv = _srv()
        cmd = ["npx", "-y", "mcp-server-time"]
        transport, pool_key = _fake_persistent_transport(cmd)
        before_form = session.get("current_form")

        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch("kitsune_mcp.tools._state.PersistentStdioTransport", return_value=transport),
        ):
            out = await prewarm("mcp-server-time")

        assert pool_key in _process_pool
        assert _process_pool[pool_key].name == "mcp-server-time"
        # Nothing mounted: session untouched
        assert session.get("current_form") == before_form
        assert session.get("shapeshift_tools", []) == []
        assert "mcp-server-time" in out
        # Tell the agent the natural next step
        assert "shapeshift" in out

    @pytest.mark.asyncio
    async def test_community_source_requires_confirm(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        srv = _srv(source="npm")
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch.dict(os.environ, {"KITSUNE_TRUST": ""}),
        ):
            out = await prewarm("mcp-server-time")

        assert _process_pool == {}
        assert "confirm=True" in out

    @pytest.mark.asyncio
    async def test_community_source_confirm_proceeds(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        srv = _srv(source="npm")
        cmd = ["npx", "-y", "mcp-server-time"]
        transport, pool_key = _fake_persistent_transport(cmd)
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch("kitsune_mcp.tools._state.PersistentStdioTransport", return_value=transport),
            patch.dict(os.environ, {"KITSUNE_TRUST": ""}),
        ):
            out = await prewarm("mcp-server-time", confirm=True)

        assert pool_key in _process_pool
        assert "mcp-server-time" in out

    @pytest.mark.asyncio
    async def test_http_only_server_nothing_to_prewarm(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        srv = _srv(transport="http", url="https://mcp.example.com", install_cmd=[])
        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)):
            out = await prewarm("mcp-server-time")

        assert _process_pool == {}
        assert "http" in out.lower()

    @pytest.mark.asyncio
    async def test_missing_credentials_blocked(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        srv = _srv(credentials={"VERY_UNLIKELY_XYZ_API_KEY": "required key"})
        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)):
            out = await prewarm("mcp-server-time")

        assert _process_pool == {}
        assert "VERY_UNLIKELY_XYZ_API_KEY" in out

    @pytest.mark.asyncio
    async def test_unknown_server_reports_not_found(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm

        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=None)),
            patch("kitsune_mcp.tools._state._resolve_server_id", AsyncMock(return_value=(None, []))),
        ):
            out = await prewarm("no-such-server")

        assert "not found" in out.lower()

    @pytest.mark.asyncio
    async def test_already_warm_is_idempotent(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _PoolEntry, _process_pool

        srv = _srv()
        cmd = ["npx", "-y", "mcp-server-time"]
        pool_key = json.dumps(cmd, sort_keys=True)
        _process_pool[pool_key] = _PoolEntry(
            proc=make_mock_process(), install_cmd=cmd, started_at=0.0,
            name="mcp-server-time",
        )
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT,
        ):
            out = await prewarm("mcp-server-time")

        MockT.assert_not_called()
        assert "warm" in out.lower()

    @pytest.mark.asyncio
    async def test_community_prewarm_caged_by_default_with_docker(self, monkeypatch):
        """PR C: a prewarmed low-trust process cages by default when Docker is
        present, so a later shapeshift()/call() reuses a caged process."""
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        captured: list = []

        def factory(cmd, **kwargs):
            captured.append(cmd)
            from kitsune_mcp.transport import _PoolEntry
            t = MagicMock()

            async def _lt(*a, **k):
                _process_pool[json.dumps(cmd, sort_keys=True)] = _PoolEntry(
                    proc=make_mock_process(), install_cmd=cmd, started_at=0.0,
                )
                return [{"name": "x", "description": "", "inputSchema": {}}]

            t.list_tools = AsyncMock(side_effect=_lt)
            return t

        srv = _srv(source="npm")
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch.object(_state, "PersistentStdioTransport", factory),
            patch("kitsune_mcp.tools.shapeshift.shutil.which", return_value="/usr/local/bin/docker"),
        ):
            out = await prewarm("mcp-server-time", confirm=True)

        assert captured[0][0] == "docker"
        assert "Prewarmed" in out

    @pytest.mark.asyncio
    async def test_community_prewarm_sandbox_false_opts_out(self, monkeypatch):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm
        from kitsune_mcp.transport import _process_pool

        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        srv = _srv(source="npm")
        cmd = ["npx", "-y", "mcp-server-time"]
        transport, pool_key = _fake_persistent_transport(cmd)
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch("kitsune_mcp.tools._state.PersistentStdioTransport", return_value=transport),
            patch("kitsune_mcp.tools.shapeshift.shutil.which", return_value="/usr/local/bin/docker"),
        ):
            out = await prewarm("mcp-server-time", confirm=True, sandbox=False)

        assert pool_key in _process_pool  # unwrapped key → not caged
        assert "Prewarmed" in out

    @pytest.mark.asyncio
    async def test_release_cleans_up_prewarmed_entry(self):
        from kitsune_mcp.registry import _registry
        from kitsune_mcp.tools.shapeshift import prewarm, release
        from kitsune_mcp.transport import _process_pool

        srv = _srv()
        cmd = ["npx", "-y", "mcp-server-time"]
        transport, pool_key = _fake_persistent_transport(cmd)
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=srv)),
            patch("kitsune_mcp.tools._state.PersistentStdioTransport", return_value=transport),
        ):
            await prewarm("mcp-server-time")

        assert pool_key in _process_pool
        out = await release("mcp-server-time")
        assert pool_key not in _process_pool
        assert "Released" in out
