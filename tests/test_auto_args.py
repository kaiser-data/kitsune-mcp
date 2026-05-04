"""Tests for auto() argument inference (v0.11.0 commit 2 — issue #8 fix).

Reproduces and fixes the failure mode: auto() with empty arguments would
auto-select a tool and call it with {}, causing the inner server to reject
with "query: undefined". Auto-fills the primary string param from `task`.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestInferArgsFromTask:
    """Pure function: schema + task → inferred arguments."""

    def _fn(self):
        from kitsune_mcp.tools.onboarding import _infer_args_from_task
        return _infer_args_from_task

    def test_picks_query_param_when_required_and_string(self):
        schema = {
            "name": "search",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "num_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        }
        assert self._fn()(schema, "kitsune mcp") == {"query": "kitsune mcp"}

    def test_picks_q_alias(self):
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        }
        assert self._fn()(schema, "test") == {"q": "test"}

    def test_picks_prompt_alias(self):
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {"prompt": {"type": "string"}},
                "required": ["prompt"],
            },
        }
        assert self._fn()(schema, "make a poem") == {"prompt": "make a poem"}

    def test_picks_single_required_string_when_no_common_name(self):
        # Custom param name (e.g. "user_question") — falls back to "single
        # required string" heuristic.
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_question": {"type": "string"},
                    "max_tokens": {"type": "integer"},
                },
                "required": ["user_question"],
            },
        }
        assert self._fn()(schema, "what is X?") == {"user_question": "what is X?"}

    def test_returns_empty_when_multiple_required_strings(self):
        # Ambiguous — don't guess. Better to let inner schema validation
        # surface the missing args than to silently fill the wrong one.
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["from", "to"],
            },
        }
        assert self._fn()(schema, "convert this") == {}

    def test_returns_empty_when_no_required(self):
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": [],
            },
        }
        assert self._fn()(schema, "anything") == {}

    def test_returns_empty_when_no_string_required(self):
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {"count": {"type": "integer"}},
                "required": ["count"],
            },
        }
        assert self._fn()(schema, "anything") == {}

    def test_handles_missing_inputschema(self):
        assert self._fn()({"name": "x"}, "task") == {}

    def test_handles_completely_empty_schema(self):
        assert self._fn()({}, "task") == {}


@pytest.mark.asyncio
class TestAutoFillsArgs:
    """Integration: auto() with empty arguments fills from task."""

    async def test_auto_fills_query_when_arguments_empty(self):
        from unittest.mock import AsyncMock, patch

        from kitsune_mcp.registry import ServerInfo

        srv = ServerInfo(
            id="example-search", name="Example Search", description="search server",
            source="official", transport="stdio",
            install_cmd=["npx", "-y", "example-search"], credentials={},
            tools=[{
                "name": "search",
                "description": "Search the web",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }],
        )

        captured: dict = {}

        async def fake_execute(tool, args, config):
            captured["tool"] = tool
            captured["args"] = args
            return '{"results": []}'

        fake_transport = AsyncMock()
        fake_transport.execute = fake_execute

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._get_transport", return_value=fake_transport):
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_reg.get_server = AsyncMock(return_value=srv)
            from kitsune_mcp.tools import auto
            await auto(task="kitsune mcp")

        assert captured["tool"] == "search"
        # The KEY fix: query was filled from task, not left as undefined
        assert captured["args"] == {"query": "kitsune mcp"}

    async def test_auto_falls_back_to_next_provider_on_auth_failure(self):
        """v0.11.0 commit 5: when the chosen provider returns an auth-failure
        response and no server_hint was supplied, try the next candidate."""
        from unittest.mock import AsyncMock, patch

        from kitsune_mcp.registry import ServerInfo

        srv_a = ServerInfo(
            id="provider-a", name="provider-a", description="",
            source="smithery", transport="http",
            install_cmd=[], credentials={},
            tools=[{
                "name": "search",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }],
        )
        srv_b = ServerInfo(
            id="provider-b", name="provider-b", description="",
            source="npm", transport="stdio",
            install_cmd=["npx", "-y", "provider-b"], credentials={},
            tools=[{
                "name": "search",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }],
        )

        # Track which server was tried in which order
        call_log: list[str] = []

        async def fake_execute_factory(server_id):
            async def fake_execute(tool, args, config):
                call_log.append(server_id)
                if server_id == "provider-a":
                    return "Auth failed: SMITHERY_API_KEY invalid"
                return '{"results": ["ok"]}'
            return fake_execute

        async def get_transport_side_effect(server_id, srv):
            transport = AsyncMock()
            transport.execute = await fake_execute_factory(server_id)
            return transport

        async def get_server_side_effect(server_id, source_preference=None):
            return {"provider-a": srv_a, "provider-b": srv_b}.get(server_id)

        # Wrap _get_transport to set execute properly per call (test scaffolding)
        async def _gt(server_id, srv):
            t = AsyncMock()
            async def _exec(tool, args, config):
                call_log.append(server_id)
                if server_id == "provider-a":
                    return "Auth failed: SMITHERY_API_KEY invalid"
                return '{"results": ["ok"]}'
            t.execute = _exec
            return t

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._get_transport", side_effect=lambda sid, s: _gt(sid, s)) as _:
            mock_reg.search = AsyncMock(return_value=[srv_a, srv_b])
            mock_reg.get_server = AsyncMock(side_effect=get_server_side_effect)

            from kitsune_mcp.tools import auto
            # Need to await get_transport — current implementation uses sync return
            # so test against the actual auto() flow with a different mocking strategy

        # Simpler retest: actually patch the transport returned to be a coroutine
        from unittest.mock import MagicMock

        results_per_id = {
            "provider-a": "Auth failed for SMITHERY_API_KEY",
            "provider-b": '{"results": ["fallback success"]}',
        }

        async def execute_dispatcher(server_id):
            async def _exec(tool, args, config):
                call_log.append(server_id)
                return results_per_id[server_id]
            return _exec

        def make_transport(server_id, srv):
            t = MagicMock()
            async def _exec(tool, args, config):
                call_log.append(server_id)
                return results_per_id[server_id]
            t.execute = _exec
            return t

        call_log.clear()
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._get_transport", side_effect=make_transport):
            mock_reg.search = AsyncMock(return_value=[srv_a, srv_b])
            mock_reg.get_server = AsyncMock(side_effect=get_server_side_effect)
            from kitsune_mcp.tools import auto
            result = await auto(task="web search", arguments={"query": "x"})

        assert call_log == ["provider-a", "provider-b"]
        assert "fallback success" in result

    async def test_auto_does_not_fallback_when_server_hint_pinned(self):
        """When the caller pinned via server_hint, an auth failure surfaces
        directly — they asked for THAT provider specifically."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from kitsune_mcp.registry import ServerInfo

        srv = ServerInfo(
            id="pinned", name="pinned", description="",
            source="smithery", transport="http",
            install_cmd=[], credentials={},
            tools=[{
                "name": "search",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }],
        )
        call_log: list[str] = []

        def make_transport(server_id, s):
            t = MagicMock()
            async def _exec(tool, args, config):
                call_log.append(server_id)
                return "Auth failed"
            t.execute = _exec
            return t

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._get_transport", side_effect=make_transport):
            mock_reg.get_server = AsyncMock(return_value=srv)
            from kitsune_mcp.tools import auto
            result = await auto(task="x", tool_name="search", arguments={"query": "x"}, server_hint="pinned")

        # Only one call — no fallback when pinned
        assert call_log == ["pinned"]
        assert "Auth failed" in result

    async def test_auto_preserves_explicit_arguments(self):
        from unittest.mock import AsyncMock, patch

        from kitsune_mcp.registry import ServerInfo

        srv = ServerInfo(
            id="example-search", name="Example", description="",
            source="official", transport="stdio",
            install_cmd=["npx", "-y", "x"], credentials={},
            tools=[{
                "name": "search",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["query"],
                },
            }],
        )
        captured: dict = {}

        async def fake_execute(tool, args, config):
            captured["args"] = args
            return "ok"

        fake_transport = AsyncMock()
        fake_transport.execute = fake_execute

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._get_transport", return_value=fake_transport):
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_reg.get_server = AsyncMock(return_value=srv)
            from kitsune_mcp.tools import auto
            # Caller supplied explicit args — must NOT be overridden by inference
            await auto(task="search the web", arguments={"query": "explicit", "limit": 10})

        assert captured["args"] == {"query": "explicit", "limit": 10}
