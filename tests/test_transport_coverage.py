"""Targeted tests for previously uncovered transport.py paths.

Covers: _SmitheryAuth namespace/token caching, _ensure_smithery_connection
(incl. 409 recreate), pure URL/conn-id helpers, HTTPSSETransport.list_tools,
HTTP execute error paths (init error, empty response, auth-failure credentials
guide), stdio error paths, persistent-transport reconnect branches
(broken pipe mid-write, death while waiting, .env-revision respawn),
prompts/list + prompts/get, pool atexit cleanup, and _ping on a dead entry.
"""
import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import kitsune_mcp.transport as tp
from kitsune_mcp.transport import (
    HTTPSSETransport,
    PersistentStdioTransport,
    StdioTransport,
    WebSocketTransport,
    _build_mcp_url,
    _ensure_smithery_connection,
    _kill_all_pool_processes,
    _ping,
    _PoolEntry,
    _process_pool,
    _smithery_auth,
    _smithery_conn_id,
)

from .conftest import make_mock_process, make_stdout_with_responses


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Isolate Smithery auth cache, process pool, and evict debounce per test."""
    _smithery_auth.reset()
    _process_pool.clear()
    monkeypatch.setattr(tp, "_last_evict_at", 0.0)
    yield
    _smithery_auth.reset()
    _process_pool.clear()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestSmitheryConnId:
    def test_sanitizes_and_prefixes(self):
        assert _smithery_conn_id("Test-Org/My Server") == "kitsune-test-org-my-server"

    def test_truncates_to_64_chars(self):
        cid = _smithery_conn_id("x" * 100)
        assert len(cid) == 64
        assert cid.startswith("kitsune-")


class TestBuildMcpUrl:
    def test_no_config_returns_url_unchanged(self):
        assert _build_mcp_url("https://x.example/mcp", {}) == "https://x.example/mcp"

    def test_none_values_are_dropped(self):
        assert _build_mcp_url("https://x.example", {"a": None}) == "https://x.example"

    def test_appends_query_string(self):
        assert _build_mcp_url("https://x.example", {"k": "v"}) == "https://x.example?k=v"

    def test_uses_ampersand_when_query_present(self):
        assert _build_mcp_url("https://x.example?a=1", {"k": "v"}) == "https://x.example?a=1&k=v"


# ---------------------------------------------------------------------------
# _SmitheryAuth
# ---------------------------------------------------------------------------

class TestSmitheryAuthNamespace:
    async def test_no_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        monkeypatch.setattr(tp, "SMITHERY_API_KEY", "")
        assert await _smithery_auth.get_namespace() is None

    async def test_fetches_first_namespace_and_caches(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            route = respx.get("https://api.smithery.ai/namespaces").mock(
                return_value=httpx.Response(200, json={"namespaces": [{"name": "myns"}]})
            )
            assert await _smithery_auth.get_namespace() == "myns"
            # second call served from cache — no extra HTTP call
            assert await _smithery_auth.get_namespace() == "myns"
            assert route.call_count == 1

    async def test_http_error_returns_none(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            respx.get("https://api.smithery.ai/namespaces").mock(
                return_value=httpx.Response(500)
            )
            assert await _smithery_auth.get_namespace() is None

    async def test_empty_namespace_list_returns_none(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            respx.get("https://api.smithery.ai/namespaces").mock(
                return_value=httpx.Response(200, json={"namespaces": []})
            )
            assert await _smithery_auth.get_namespace() is None


class TestSmitheryAuthToken:
    async def test_no_api_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        monkeypatch.setattr(tp, "SMITHERY_API_KEY", "")
        assert await _smithery_auth.get_token() == ""

    async def test_fetches_token_and_caches(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            route = respx.post("https://api.smithery.ai/tokens").mock(
                return_value=httpx.Response(
                    200,
                    json={"token": "svc-tok", "expiresAt": "2099-01-01T00:00:00Z"},
                )
            )
            assert await _smithery_auth.get_token() == "svc-tok"
            assert await _smithery_auth.get_token() == "svc-tok"
            assert route.call_count == 1

    async def test_http_error_returns_empty(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            respx.post("https://api.smithery.ai/tokens").mock(
                return_value=httpx.Response(403)
            )
            assert await _smithery_auth.get_token() == ""

    def test_reset_clears_all_state(self):
        _smithery_auth.namespace = "ns"
        _smithery_auth.service_token = "tok"
        _smithery_auth.token_expires = time.monotonic() + 1000
        _smithery_auth.connections["c"] = "u"
        _smithery_auth.reset()
        assert _smithery_auth.namespace is None
        assert _smithery_auth.service_token == ""
        assert _smithery_auth.token_expires == 0.0
        assert _smithery_auth.connections == {}


# ---------------------------------------------------------------------------
# _ensure_smithery_connection
# ---------------------------------------------------------------------------

class TestEnsureSmitheryConnection:
    URL = "https://api.smithery.ai/connect/ns/kitsune-x"

    async def test_put_success_records_connection(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            respx.put(self.URL).mock(return_value=httpx.Response(200, json={}))
            ok = await _ensure_smithery_connection("ns", "kitsune-x", "https://srv/mcp")
        assert ok is True
        assert _smithery_auth.connections["kitsune-x"] == "https://srv/mcp"

    async def test_cached_connection_skips_http(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        _smithery_auth.connections["kitsune-x"] = "https://srv/mcp"
        with respx.mock:  # no routes registered — any HTTP call would error
            ok = await _ensure_smithery_connection("ns", "kitsune-x", "https://srv/mcp")
        assert ok is True

    async def test_409_deletes_and_recreates(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            put_route = respx.put(self.URL).mock(
                side_effect=[httpx.Response(409), httpx.Response(200, json={})]
            )
            delete_route = respx.delete(self.URL).mock(return_value=httpx.Response(204))
            ok = await _ensure_smithery_connection("ns", "kitsune-x", "https://srv/mcp")
        assert ok is True
        assert put_route.call_count == 2
        assert delete_route.call_count == 1

    async def test_http_failure_returns_false(self, monkeypatch):
        monkeypatch.setenv("SMITHERY_API_KEY", "test-key")
        with respx.mock:
            respx.put(self.URL).mock(return_value=httpx.Response(500))
            ok = await _ensure_smithery_connection("ns", "kitsune-x", "https://srv/mcp")
        assert ok is False


# ---------------------------------------------------------------------------
# HTTPSSETransport._connect_endpoint (Smithery-mediated path)
# ---------------------------------------------------------------------------

class TestConnectEndpointSmithery:
    def _transport(self):
        return HTTPSSETransport("org/server", deployment_url="https://srv.example/mcp")

    async def test_no_namespace_returns_none_and_failure_message(self):
        t = self._transport()
        with patch.object(tp, "_smithery_namespace", AsyncMock(return_value=None)):
            assert await t._connect_endpoint({}) is None
            result = await t.execute("tool", {}, {})
        assert "Smithery Connect" in result
        assert "SMITHERY_API_KEY" in result

    async def test_no_token_returns_none(self):
        t = self._transport()
        with (
            patch.object(tp, "_smithery_namespace", AsyncMock(return_value="ns")),
            patch.object(tp, "_smithery_service_token", AsyncMock(return_value="")),
        ):
            assert await t._connect_endpoint({}) is None

    async def test_connection_failure_returns_none(self):
        t = self._transport()
        with (
            patch.object(tp, "_smithery_namespace", AsyncMock(return_value="ns")),
            patch.object(tp, "_smithery_service_token", AsyncMock(return_value="tok")),
            patch.object(tp, "_ensure_smithery_connection", AsyncMock(return_value=False)),
        ):
            assert await t._connect_endpoint({}) is None

    async def test_success_returns_endpoint_and_token(self):
        t = self._transport()
        with (
            patch.object(tp, "_smithery_namespace", AsyncMock(return_value="ns")),
            patch.object(tp, "_smithery_service_token", AsyncMock(return_value="tok")),
            patch.object(tp, "_ensure_smithery_connection", AsyncMock(return_value=True)),
        ):
            endpoint, token = await t._connect_endpoint({"k": "v"})
        assert endpoint == "https://api.smithery.ai/connect/ns/kitsune-org-server/mcp"
        assert token == "tok"


# ---------------------------------------------------------------------------
# HTTPSSETransport.execute error paths
# ---------------------------------------------------------------------------

ENDPOINT = "https://api.smithery.ai/connect/ns/kitsune-org-server/mcp"


def _sse(payload: dict, session_id: str | None = None) -> httpx.Response:
    headers = {"mcp-session-id": session_id} if session_id else {}
    return httpx.Response(200, text=f"data: {json.dumps(payload)}\n", headers=headers)


def _patched_transport():
    t = HTTPSSETransport("org/server")
    patcher = patch.object(t, "_connect_endpoint", AsyncMock(return_value=(ENDPOINT, "tok")))
    return t, patcher


class TestHTTPExecuteErrorPaths:
    async def test_initialize_error_payload_fails_gracefully(self):
        t, patcher = _patched_transport()
        init_err = {"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": "bad init"}}
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(return_value=_sse(init_err))
            result = await t.execute("tool", {}, {})
        assert "Failed to connect" in result
        assert "bad init" in result

    async def test_empty_tool_response_fails_gracefully(self):
        t, patcher = _patched_transport()
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {}}
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(
                side_effect=[_sse(init_ok, "sid"), httpx.Response(202), httpx.Response(200, text="")]
            )
            result = await t.execute("tool", {}, {})
        assert "Empty response" in result

    async def test_error_in_tool_response_is_reported(self):
        t, patcher = _patched_transport()
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tool_err = {"jsonrpc": "2.0", "id": 2, "error": {"code": -2, "message": "boom"}}
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(
                side_effect=[_sse(init_ok, "sid"), httpx.Response(202), _sse(tool_err)]
            )
            result = await t.execute("tool", {}, {})
        assert "Error from org/server/tool" in result
        assert "boom" in result

    async def test_401_with_missing_credentials_returns_guide(self):
        t, patcher = _patched_transport()
        srv = MagicMock()
        srv.credentials = [{"key": "apiKey", "description": "Your API key"}]
        registry = MagicMock()
        registry.get_server = AsyncMock(return_value=srv)
        with (
            patcher,
            respx.mock,
            patch.object(tp, "SmitheryRegistry", MagicMock(return_value=registry)),
            patch.object(
                tp, "_resolve_config", MagicMock(return_value=({}, ["apiKey"]))
            ),
            patch.object(
                tp, "_credentials_guide", MagicMock(return_value="NEEDS apiKey")
            ) as guide,
        ):
            respx.post(ENDPOINT).mock(return_value=httpx.Response(401))
            result = await t.execute("tool", {}, {})
        assert result == "NEEDS apiKey"
        guide.assert_called_once()

    async def test_401_without_server_info_returns_auth_failed(self):
        t, patcher = _patched_transport()
        registry = MagicMock()
        registry.get_server = AsyncMock(return_value=None)
        with (
            patcher,
            respx.mock,
            patch.object(tp, "SmitheryRegistry", MagicMock(return_value=registry)),
        ):
            respx.post(ENDPOINT).mock(return_value=httpx.Response(401))
            result = await t.execute("tool", {}, {})
        assert "Auth failed for org/server" in result


# ---------------------------------------------------------------------------
# HTTPSSETransport.list_tools
# ---------------------------------------------------------------------------

class TestHTTPListTools:
    async def test_connect_failure_returns_empty(self):
        t = HTTPSSETransport("org/server")
        with patch.object(t, "_connect_endpoint", AsyncMock(return_value=None)):
            assert await t.list_tools() == []

    async def test_success_returns_tool_list(self):
        t, patcher = _patched_transport()
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tools = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "a"}, {"name": "b"}]}}
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(
                side_effect=[_sse(init_ok, "sid"), httpx.Response(202), _sse(tools)]
            )
            result = await t.list_tools()
        assert [x["name"] for x in result] == ["a", "b"]

    async def test_non_result_payload_returns_empty(self):
        t, patcher = _patched_transport()
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {}}
        err = {"jsonrpc": "2.0", "id": 2, "error": {"message": "nope"}}
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(
                side_effect=[_sse(init_ok, "sid"), httpx.Response(202), _sse(err)]
            )
            assert await t.list_tools() == []

    async def test_401_smithery_mode_returns_empty(self):
        t, patcher = _patched_transport()
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(return_value=httpx.Response(401))
            assert await t.list_tools() == []

    async def test_401_direct_mode_retries_with_fresh_token(self):
        url = "https://direct.example/mcp"
        t = HTTPSSETransport(url, direct=True)
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {}}
        tools = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "fresh"}]}}
        with (
            patch.object(t, "_connect_endpoint", AsyncMock(return_value=(url, "stale"))),
            patch.object(tp.oauth, "delete_tokens", MagicMock()) as deleter,
            patch.object(tp.oauth, "ensure_token", AsyncMock(return_value="fresh-tok")),
            respx.mock,
        ):
            respx.post(url).mock(
                side_effect=[
                    httpx.Response(401),               # first init → PermissionError
                    _sse(init_ok, "sid"),              # retry init
                    httpx.Response(202),               # initialized notify
                    _sse(tools),                       # tools/list
                ]
            )
            result = await t.list_tools()
        assert [x["name"] for x in result] == ["fresh"]
        deleter.assert_called_once()

    async def test_401_direct_mode_failed_retry_returns_empty(self):
        url = "https://direct.example/mcp"
        t = HTTPSSETransport(url, direct=True)
        with (
            patch.object(t, "_connect_endpoint", AsyncMock(return_value=(url, "stale"))),
            patch.object(tp.oauth, "delete_tokens", MagicMock()),
            patch.object(tp.oauth, "ensure_token", AsyncMock(side_effect=RuntimeError("no auth"))),
            respx.mock,
        ):
            respx.post(url).mock(return_value=httpx.Response(401))
            assert await t.list_tools() == []

    async def test_generic_exception_returns_empty(self):
        t, patcher = _patched_transport()
        with patcher, respx.mock:
            respx.post(ENDPOINT).mock(side_effect=httpx.ConnectError("down"))
            assert await t.list_tools() == []

    async def test_direct_failure_message_mentions_oauth(self):
        t = HTTPSSETransport("https://direct.example/mcp", direct=True)
        msg = t._connect_failure_message()
        assert "OAuth 2.1" in msg


# ---------------------------------------------------------------------------
# StdioTransport error paths
# ---------------------------------------------------------------------------

class TestStdioErrorPaths:
    async def test_generic_spawn_exception(self):
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=RuntimeError("ulimit"))):
            result = await StdioTransport(["mycmd"]).execute("tool", {}, {})
        assert "Failed to start mycmd" in result

    async def test_initialize_error_response(self):
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 1, "error": {"message": "init broken"}}]
        )
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await StdioTransport(["mycmd"]).execute("tool", {}, {})
        assert "Initialize error" in result

    async def test_no_tool_response_after_init(self):
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 1, "result": {}}]  # then EOF
        )
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await StdioTransport(["mycmd"]).execute("tool", {}, {})
        assert "No response from mycmd" in result

    async def test_tool_error_response(self):
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses([
            {"jsonrpc": "2.0", "id": 1, "result": {}},
            {"jsonrpc": "2.0", "id": 2, "error": {"message": "tool exploded"}},
        ])
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await StdioTransport(["mycmd"]).execute("tool", {}, {})
        assert "Tool error: tool exploded" in result

    async def test_mid_call_exception_reported(self):
        proc = make_mock_process()
        proc.stdin.drain = AsyncMock(side_effect=ValueError("pipe gone"))
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await StdioTransport(["mycmd"]).execute("tool", {}, {})
        assert "Stdio transport error" in result


# ---------------------------------------------------------------------------
# PersistentStdioTransport reconnect + error paths
# ---------------------------------------------------------------------------

def _make_entry(proc=None) -> _PoolEntry:
    return _PoolEntry(
        proc=proc or make_mock_process(),
        install_cmd=["mycmd"],
        started_at=time.monotonic(),
    )


TOOL_OK = {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "ok!"}]}}


class TestPersistentStartProcessErrors:
    async def test_generic_spawn_exception_raises_runtime_error(self):
        t = PersistentStdioTransport(["mycmd"])
        with patch("asyncio.create_subprocess_exec", AsyncMock(side_effect=ValueError("bad fd"))):
            result = await t.execute("tool", {}, {})
        assert "Failed to start mycmd" in result

    async def test_initialize_error_kills_process(self):
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 1, "error": {"message": "nope"}}]
        )
        t = PersistentStdioTransport(["mycmd"])
        with (
            patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)),
            patch.object(tp, "_kill_process_tree", MagicMock()) as killer,
        ):
            result = await t.execute("tool", {}, {})
        assert "Initialize error" in result
        killer.assert_called()


class TestDotenvRevisionRespawn:
    async def test_env_change_kills_and_respawns(self, monkeypatch):
        t = PersistentStdioTransport(["mycmd"])
        stale = _make_entry()
        stale.dotenv_revision = 0
        _process_pool[t._pool_key] = stale
        monkeypatch.setattr(tp._creds, "_dotenv_revision", 1)

        fresh = _make_entry()
        with (
            patch.object(t, "_start_process", AsyncMock(return_value=fresh)) as starter,
            patch.object(tp, "_kill_process_tree", MagicMock()) as killer,
        ):
            entry = await t._get_or_start()
        assert entry is fresh
        killer.assert_called_once_with(stale.proc)
        starter.assert_called_once()


class TestPersistentExecuteRetries:
    async def test_dead_entry_at_loop_start_reconnects(self):
        t = PersistentStdioTransport(["mycmd"])
        dead = _make_entry(make_mock_process(returncode=1))
        good = _make_entry()
        good.proc.stdout = make_stdout_with_responses([TOOL_OK])
        with (
            patch.object(t, "_get_or_start", AsyncMock(return_value=dead)),
            patch.object(t, "_start_process", AsyncMock(return_value=good)),
        ):
            result = await t.execute("tool", {}, {})
        assert "ok!" in result

    async def test_dead_entry_reconnect_failure_reported(self):
        t = PersistentStdioTransport(["mycmd"])
        dead = _make_entry(make_mock_process(returncode=1))
        with (
            patch.object(t, "_get_or_start", AsyncMock(return_value=dead)),
            patch.object(t, "_start_process", AsyncMock(side_effect=RuntimeError("gone"))),
        ):
            result = await t.execute("tool", {}, {})
        assert "Reconnect failed: gone" in result

    async def test_broken_pipe_mid_write_retries_once(self):
        t = PersistentStdioTransport(["mycmd"])
        flaky = _make_entry()
        flaky.proc.stdin.write = MagicMock(side_effect=BrokenPipeError)
        good = _make_entry()
        good.proc.stdout = make_stdout_with_responses([TOOL_OK])
        with (
            patch.object(t, "_get_or_start", AsyncMock(return_value=flaky)),
            patch.object(t, "_start_process", AsyncMock(return_value=good)),
            patch.object(tp, "_kill_process_tree", MagicMock()),
        ):
            result = await t.execute("tool", {}, {})
        assert "ok!" in result

    async def test_broken_pipe_twice_gives_up(self):
        t = PersistentStdioTransport(["mycmd"])
        flaky1 = _make_entry()
        flaky1.proc.stdin.write = MagicMock(side_effect=BrokenPipeError)
        flaky2 = _make_entry()
        flaky2.proc.stdin.write = MagicMock(side_effect=BrokenPipeError)
        with (
            patch.object(t, "_get_or_start", AsyncMock(return_value=flaky1)),
            patch.object(t, "_start_process", AsyncMock(return_value=flaky2)),
            patch.object(tp, "_kill_process_tree", MagicMock()),
        ):
            result = await t.execute("tool", {}, {})
        assert "after reconnect" in result

    async def test_broken_pipe_then_reconnect_failure(self):
        t = PersistentStdioTransport(["mycmd"])
        flaky = _make_entry()
        flaky.proc.stdin.write = MagicMock(side_effect=ConnectionResetError)
        with (
            patch.object(t, "_get_or_start", AsyncMock(return_value=flaky)),
            patch.object(t, "_start_process", AsyncMock(side_effect=RuntimeError("spawn fail"))),
            patch.object(tp, "_kill_process_tree", MagicMock()),
        ):
            result = await t.execute("tool", {}, {})
        assert "Reconnect failed: spawn fail" in result

    async def test_unexpected_write_exception_reported(self):
        t = PersistentStdioTransport(["mycmd"])
        entry = _make_entry()
        entry.proc.stdin.write = MagicMock(side_effect=ValueError("weird"))
        with patch.object(t, "_get_or_start", AsyncMock(return_value=entry)):
            result = await t.execute("tool", {}, {})
        assert "Failed to send to mycmd: weird" in result

    async def test_death_while_waiting_for_response_retries(self):
        t = PersistentStdioTransport(["mycmd"])
        dying = _make_entry()
        dying.proc.stdout = make_stdout_with_responses([])  # EOF right away

        def _mark_dead(_data):
            dying.proc.returncode = 1  # dies after the write lands

        dying.proc.stdin.write = MagicMock(side_effect=_mark_dead)
        good = _make_entry()
        good.proc.stdout = make_stdout_with_responses([TOOL_OK])
        with (
            patch.object(t, "_get_or_start", AsyncMock(return_value=dying)),
            patch.object(t, "_start_process", AsyncMock(return_value=good)),
        ):
            result = await t.execute("tool", {}, {})
        assert "ok!" in result

    async def test_no_response_while_alive_reports_tool_name(self):
        t = PersistentStdioTransport(["mycmd"])
        silent = _make_entry()
        silent.proc.stdout = make_stdout_with_responses([])  # EOF, but stays alive
        with patch.object(t, "_get_or_start", AsyncMock(return_value=silent)):
            result = await t.execute("mytool", {}, {})
        assert "No response from mycmd for tool 'mytool'" in result

    async def test_tool_error_response_reported(self):
        t = PersistentStdioTransport(["mycmd"])
        entry = _make_entry()
        entry.proc.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 3, "error": {"message": "kaboom"}}]
        )
        with patch.object(t, "_get_or_start", AsyncMock(return_value=entry)):
            result = await t.execute("tool", {}, {})
        assert "Tool error: kaboom" in result


class TestPersistentPromptMethods:
    async def test_list_prompts_unwraps_result(self):
        t = PersistentStdioTransport(["mycmd"])
        with patch.object(
            t, "_send_request", AsyncMock(return_value={"prompts": [{"name": "p1"}]})
        ):
            assert await t.list_prompts() == [{"name": "p1"}]

    async def test_get_prompt_unwraps_messages(self):
        t = PersistentStdioTransport(["mycmd"])
        msgs = [{"role": "user", "content": {"type": "text", "text": "hi"}}]
        with patch.object(t, "_send_request", AsyncMock(return_value={"messages": msgs})) as sender:
            assert await t.get_prompt("p1", {"a": 1}) == msgs
        sender.assert_called_once_with(
            "prompts/get", {"name": "p1", "arguments": {"a": 1}}, tp.TIMEOUT_PROMPT_LIST
        )


# ---------------------------------------------------------------------------
# Pool lifecycle helpers
# ---------------------------------------------------------------------------

class TestKillAllPoolProcesses:
    def test_kills_every_entry_and_clears_pool(self):
        e1, e2 = _make_entry(), _make_entry()
        _process_pool["a"] = e1
        _process_pool["b"] = e2
        with (
            patch.object(tp, "_save_state", MagicMock()) as saver,
            patch.object(tp, "_kill_process_tree", MagicMock()) as killer,
        ):
            _kill_all_pool_processes()
        assert _process_pool == {}
        assert killer.call_count == 2
        saver.assert_called_once()


class TestPing:
    async def test_dead_entry_returns_false(self):
        entry = _make_entry(make_mock_process(returncode=1))
        assert await _ping(entry) is False

    async def test_live_entry_with_valid_response_returns_true(self):
        entry = _make_entry()
        entry.proc.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 3, "result": {"tools": []}}]
        )
        assert await _ping(entry) is True

    async def test_error_response_returns_false(self):
        entry = _make_entry()
        entry.proc.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 3, "error": {"message": "x"}}]
        )
        assert await _ping(entry) is False


# ---------------------------------------------------------------------------
# Protocol version negotiation (MCP-Protocol-Version header)
# ---------------------------------------------------------------------------

class TestProtocolVersionNegotiation:
    def test_negotiated_version_extracted_from_init_response(self):
        msg = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}
        assert tp._negotiated_version(msg) == "2024-11-05"

    def test_missing_version_falls_back_to_ours(self):
        assert tp._negotiated_version(None) == tp.MCP_PROTOCOL_VERSION
        assert tp._negotiated_version({"result": {}}) == tp.MCP_PROTOCOL_VERSION

    async def test_execute_echoes_server_version_in_header(self):
        t, patcher = _patched_transport()
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-03-26"}}
        tool_ok = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "hi"}]}}
        with patcher, respx.mock:
            route = respx.post(ENDPOINT).mock(
                side_effect=[_sse(init_ok, "sid"), httpx.Response(202), _sse(tool_ok)]
            )
            result = await t.execute("tool", {}, {})
        assert "hi" in result
        init_req, notify_req, call_req = (c.request for c in route.calls)
        assert "MCP-Protocol-Version" not in init_req.headers
        assert notify_req.headers["MCP-Protocol-Version"] == "2025-03-26"
        assert call_req.headers["MCP-Protocol-Version"] == "2025-03-26"

    async def test_list_tools_sends_negotiated_header(self):
        t, patcher = _patched_transport()
        init_ok = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}
        tools = {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "a"}]}}
        with patcher, respx.mock:
            route = respx.post(ENDPOINT).mock(
                side_effect=[_sse(init_ok, "sid"), httpx.Response(202), _sse(tools)]
            )
            result = await t.list_tools()
        assert result == [{"name": "a"}]
        assert route.calls[2].request.headers["MCP-Protocol-Version"] == "2025-06-18"

    def test_initialize_request_advertises_current_spec(self):
        req = tp._initialize_request()
        assert req["params"]["protocolVersion"] == "2025-06-18"


# ---------------------------------------------------------------------------
# WebSocketTransport — non-JSON reply
# ---------------------------------------------------------------------------

class TestWebSocketNonJson:
    async def test_non_json_reply_returned_as_string(self):
        ws = AsyncMock()
        init_reply = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
        ws.recv = AsyncMock(side_effect=[init_reply, "plain text, not json"])
        ws.send = AsyncMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)
        ws_module = MagicMock()
        ws_module.connect = MagicMock(return_value=cm)

        t = WebSocketTransport("ws://localhost:1")
        with patch.dict(sys.modules, {"websockets": ws_module}):
            result = await t.execute("tool", {}, {})
        assert result == "plain text, not json"
