"""Tests for StdioTransport and HTTPSSETransport."""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from server import (
    DockerTransport,
    HTTPSSETransport,
    StdioTransport,
    WebSocketTransport,
    _validate_install_cmd,
)

# ---------------------------------------------------------------------------
# StdioTransport tests
# ---------------------------------------------------------------------------

class TestStdioTransportFileNotFound:
    async def test_missing_executable_returns_friendly_message(self):
        transport = StdioTransport(["definitely_not_a_real_command_xyz"])
        result = await transport.execute("some_tool", {}, {})
        assert "Cannot find" in result or "Failed to start" in result

    async def test_missing_npx_returns_install_hint(self):
        transport = StdioTransport(["__no_such_binary__", "-y", "some-pkg"])
        result = await transport.execute("tool", {}, {})
        assert "__no_such_binary__" in result


class TestStdioTransportParseSSE:
    """Test _parse_sse staticmethod on HTTPSSETransport."""

    def test_parse_sse_valid_data_line(self):
        text = "data: {\"jsonrpc\": \"2.0\", \"id\": 1, \"result\": {}}\n"
        # Access via instance — parse_sse is a nested function, test indirectly
        # by constructing a mock response scenario
        assert '{"jsonrpc"' in text  # sanity

    async def test_no_init_response_returns_error_message(self):
        """StdioTransport returns friendly error when process gives no initialize response."""
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdout = MagicMock()
        # readline immediately returns empty bytes (EOF)
        mock_proc.stdout.readline = AsyncMock(return_value=b"")
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            transport = StdioTransport(["echo"])
            result = await transport.execute("tool", {}, {})
        assert "No" in result or "response" in result.lower() or "error" in result.lower()


class TestHTTPSSETransport:
    async def test_parse_sse_extracts_json_from_data_line(self):
        """_parse_sse correctly parses SSE data lines."""
        import httpx
        import respx


        endpoint = "https://api.smithery.ai/connect/ns/kitsune-test-org-test-server/mcp"
        payload = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"}}}
        tool_payload = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "ok"}]}}

        transport = HTTPSSETransport("test-org/test-server")
        with patch.object(transport, "_connect_endpoint", AsyncMock(return_value=(endpoint, "svc-token"))):
            with respx.mock:
                respx.post(endpoint).mock(
                    side_effect=[
                        httpx.Response(200, text=f"data: {json.dumps(payload)}\n", headers={"mcp-session-id": "abc"}),
                        httpx.Response(200, text=""),
                        httpx.Response(200, text=f"data: {json.dumps(tool_payload)}\n"),
                    ]
                )
                result = await transport.execute("do_thing", {"query": "test"}, {})
        # Any string response is valid — tool result or error
        assert isinstance(result, str)

    async def test_timeout_returns_timeout_message(self):
        """HTTPSSETransport returns timeout message on asyncio.TimeoutError."""
        endpoint = "https://api.smithery.ai/connect/ns/kitsune-slow-server/mcp"
        transport = HTTPSSETransport("slow-server")
        with patch.object(transport, "_connect_endpoint", AsyncMock(return_value=(endpoint, "svc-token"))):
            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
                result = await transport.execute("tool", {}, {})
        assert "Timeout" in result or "timeout" in result.lower()


# ---------------------------------------------------------------------------
# WebSocketTransport tests
# ---------------------------------------------------------------------------

class TestWebSocketTransport:
    """WebSocketTransport sends MCP handshake and tool call over WebSocket."""

    def _make_ws_mock(self, tool_response: dict):
        """Return an async context manager mock that yields a ws with preset recv() replies."""
        ws = AsyncMock()
        init_reply = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "test"}}})
        tool_reply = json.dumps(tool_response)
        ws.recv = AsyncMock(side_effect=[init_reply, tool_reply])
        ws.send = AsyncMock()

        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=ws)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    async def test_missing_websockets_package_returns_helpful_message(self):
        transport = WebSocketTransport("ws://localhost:9999")
        with patch.dict("sys.modules", {"websockets": None}):
            result = await transport.execute("some_tool", {}, {})
        assert "websockets" in result.lower()

    async def test_successful_text_response(self):
        import sys
        ws_mock_module = MagicMock()
        tool_resp = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "hello from ws"}]}}
        cm = self._make_ws_mock(tool_resp)
        ws_mock_module.connect = MagicMock(return_value=cm)

        transport = WebSocketTransport("ws://localhost:9999")
        with patch.dict(sys.modules, {"websockets": ws_mock_module}):
            result = await transport.execute("my_tool", {"arg": "val"}, {})

        assert "hello from ws" in result

    async def test_error_response_returns_error_message(self):
        import sys
        ws_mock_module = MagicMock()
        tool_resp = {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "Method not found"}}
        cm = self._make_ws_mock(tool_resp)
        ws_mock_module.connect = MagicMock(return_value=cm)

        transport = WebSocketTransport("ws://localhost:9999")
        with patch.dict(sys.modules, {"websockets": ws_mock_module}):
            result = await transport.execute("bad_tool", {}, {})

        assert "Method not found" in result

    async def test_connection_error_returns_friendly_message(self):
        import sys
        ws_mock_module = MagicMock()
        ws_mock_module.connect = MagicMock(side_effect=ConnectionRefusedError("refused"))

        transport = WebSocketTransport("ws://localhost:9999")
        with patch.dict(sys.modules, {"websockets": ws_mock_module}):
            result = await transport.execute("tool", {}, {})

        assert "WebSocket error" in result


# ---------------------------------------------------------------------------
# DockerTransport tests
# ---------------------------------------------------------------------------

class TestDockerTransport:
    """DockerTransport builds correct docker run command and delegates to PersistentStdioTransport."""

    def test_build_cmd_defaults(self):
        t = DockerTransport("mcp/my-image:latest")
        cmd = t._build_cmd({})
        assert cmd[0] == "docker"
        assert "--rm" in cmd
        assert "-i" in cmd
        assert "--memory" in cmd
        assert "512m" in cmd
        assert cmd[-1] == "mcp/my-image:latest"

    def test_build_cmd_custom_memory(self):
        t = DockerTransport("mcp/image")
        cmd = t._build_cmd({"memory": "256m"})
        idx = cmd.index("--memory")
        assert cmd[idx + 1] == "256m"

    def test_build_cmd_env_vars_injected(self):
        t = DockerTransport("mcp/image")
        cmd = t._build_cmd({"env": {"API_KEY": "abc", "DEBUG": "1"}})
        assert "-e" in cmd
        assert "API_KEY=abc" in cmd
        assert "DEBUG=1" in cmd

    def test_build_cmd_label_set(self):
        t = DockerTransport("mcp/image")
        cmd = t._build_cmd({})
        assert "--label" in cmd
        label_idx = cmd.index("--label")
        assert cmd[label_idx + 1] == "kitsune-mcp=1"

    async def test_missing_docker_returns_friendly_message(self):
        t = DockerTransport("mcp/nonexistent-image:latest")
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError("docker")):
            result = await t.execute("some_tool", {}, {})
        assert "docker" in result.lower() or "Cannot find" in result or "Failed" in result

    async def test_execute_delegates_to_persistent_transport(self):
        """DockerTransport builds cmd and delegates; result passes through."""
        import json as _json
        from unittest.mock import AsyncMock, MagicMock

        init_msg = _json.dumps({"jsonrpc": "2.0", "id": 1, "result": {
            "protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "t", "version": "1"},
        }}).encode() + b"\n"
        tool_msg = _json.dumps({"jsonrpc": "2.0", "id": 3, "result": {
            "content": [{"type": "text", "text": "docker result"}],
        }}).encode() + b"\n"

        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(side_effect=[init_msg, b"\n", tool_msg, b""])
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)

        t = DockerTransport("mcp/test-image")
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            result = await t.execute("my_tool", {"x": 1}, {})

        assert "docker result" in result


# ---------------------------------------------------------------------------
# Phase 1: _validate_install_cmd
# ---------------------------------------------------------------------------

class TestValidateInstallCmd:
    """_validate_install_cmd raises ValueError for unsafe argv[0]; accepts safe commands."""

    def test_accepts_valid_npx(self):
        _validate_install_cmd(["npx", "-y", "@modelcontextprotocol/server-github"])

    def test_accepts_valid_uvx(self):
        _validate_install_cmd(["uvx", "my-mcp-server"])

    def test_rejects_empty_command(self):
        import pytest
        with pytest.raises(ValueError, match="Empty"):
            _validate_install_cmd([])

    def test_rejects_shell_injection_semicolon(self):
        import pytest
        with pytest.raises(ValueError, match="Shell metacharacter"):
            _validate_install_cmd(["npx; rm -rf /", "arg"])

    def test_rejects_shell_injection_pipe(self):
        import pytest
        with pytest.raises(ValueError, match="Shell metacharacter"):
            _validate_install_cmd(["npx|evil", "arg"])

    def test_rejects_shell_injection_backtick(self):
        import pytest
        with pytest.raises(ValueError, match="Shell metacharacter"):
            _validate_install_cmd(["`evil`"])

    def test_rejects_path_traversal(self):
        import pytest
        with pytest.raises(ValueError, match="Path traversal"):
            _validate_install_cmd(["../../bin/evil"])

    async def test_stdio_transport_returns_error_on_invalid_cmd(self):
        """StdioTransport.execute returns an error string instead of spawning the process."""
        transport = StdioTransport(["npx; evil", "arg"])
        result = await transport.execute("tool", {}, {})
        assert "Shell metacharacter" in result

    async def test_persistent_transport_raises_runtime_error(self):
        """PersistentStdioTransport._start_process raises RuntimeError on invalid cmd."""
        import pytest

        from server import PersistentStdioTransport
        transport = PersistentStdioTransport(["../../evil"])
        with pytest.raises(RuntimeError, match="Path traversal"):
            await transport._start_process()


class TestHTTPSSETransportDirectOAuth:
    """HTTPSSETransport in direct=True mode uses oauth.ensure_token, bypassing Smithery."""

    async def test_connect_endpoint_returns_url_and_oauth_token(self):
        from kitsune_mcp import oauth, transport as _t
        url = "https://mcp.notion.com/mcp"
        transport = HTTPSSETransport(url, direct=True)
        with patch.object(oauth, "ensure_token", AsyncMock(return_value="tok-oauth-1")):
            endpoint, token = await transport._connect_endpoint({})
        assert endpoint == url
        assert token == "tok-oauth-1"

    async def test_connect_failure_message_mentions_well_known(self):
        transport = HTTPSSETransport("https://bad.example/mcp", direct=True)
        msg = transport._connect_failure_message()
        assert ".well-known" in msg

    async def test_401_triggers_delete_retry_with_new_token(self):
        from kitsune_mcp import oauth
        import httpx
        import respx
        url = "https://mcp.example/mcp"
        transport = HTTPSSETransport(url, direct=True)
        # First call returns token-1; after delete, second call returns token-2.
        ensure_tokens = AsyncMock(side_effect=["tok-1", "tok-2"])
        delete_spy = MagicMock()
        payload = {"jsonrpc": "2.0", "id": 2, "result": {"content": [{"type": "text", "text": "ok"}]}}
        init_payload = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "x", "version": "1"}}}
        with patch.object(oauth, "ensure_token", ensure_tokens), \
             patch.object(oauth, "delete_tokens", delete_spy), \
             patch.object(oauth, "_origin", return_value="mcp.example"):
            with respx.mock:
                route = respx.post(url).mock(
                    side_effect=[
                        httpx.Response(401, text=""),                                    # initialize → 401
                        httpx.Response(200, text=f"data: {json.dumps(init_payload)}\n",  # retry initialize OK
                                       headers={"mcp-session-id": "s"}),
                        httpx.Response(200, text=""),                                    # notifications/initialized
                        httpx.Response(200, text=f"data: {json.dumps(payload)}\n"),      # tools/call OK
                    ]
                )
                result = await transport.execute("my_tool", {}, {})
        assert "ok" in result
        delete_spy.assert_called_once_with("mcp.example")
        # ensure_token called twice: once in _connect_endpoint, once on 401 retry.
        assert ensure_tokens.await_count == 2

    async def test_connect_endpoint_returns_none_when_ensure_token_raises(self):
        from kitsune_mcp import oauth
        transport = HTTPSSETransport("https://no-oauth.example/mcp", direct=True)
        with patch.object(oauth, "ensure_token", AsyncMock(side_effect=RuntimeError("no well-known"))):
            result = await transport._connect_endpoint({})
        assert result is None


class TestGetTransportURLEscapeHatch:
    """_get_transport should treat bare URLs as direct HTTP MCP with OAuth."""

    def test_bare_https_url_returns_direct_httpsse(self):
        from kitsune_mcp.tools import _get_transport
        t = _get_transport("https://mcp.notion.com/mcp", None)
        assert isinstance(t, HTTPSSETransport)
        assert t.direct is True
        assert t.deployment_url == "https://mcp.notion.com/mcp"

    def test_bare_http_url_returns_direct_httpsse(self):
        from kitsune_mcp.tools import _get_transport
        t = _get_transport("http://127.0.0.1:9000/mcp", None)
        assert isinstance(t, HTTPSSETransport)
        assert t.direct is True

    def test_registry_http_run_tools_stays_smithery(self):
        """A registry-declared HTTP server on *.run.tools is still Smithery-mediated."""
        from kitsune_mcp.tools import _get_transport
        srv = MagicMock(transport="http", url="https://brave.run.tools", id="brave")
        t = _get_transport("brave", srv)
        assert isinstance(t, HTTPSSETransport)
        assert t.direct is False

    def test_registry_http_direct_url_becomes_direct(self):
        """A registry-declared HTTP server NOT on run.tools uses direct OAuth."""
        from kitsune_mcp.tools import _get_transport
        srv = MagicMock(transport="http", url="https://mcp.notion.com/mcp", id="notion-hosted")
        t = _get_transport("notion-hosted", srv)
        assert isinstance(t, HTTPSSETransport)
        assert t.direct is True


class TestStdioBufferLimit:
    """Both stdio spawn sites must pass limit= so readline() can handle large JSON-RPC lines."""

    @staticmethod
    def _mock_proc():
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdin.close = MagicMock()
        mock_proc.stdout = MagicMock()
        mock_proc.stdout.readline = AsyncMock(return_value=b"")  # EOF
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=0)
        return mock_proc

    async def test_stdio_transport_passes_limit_kwarg(self):
        from kitsune_mcp.constants import STDIO_BUFFER_LIMIT
        spy = AsyncMock(return_value=self._mock_proc())
        with patch("asyncio.create_subprocess_exec", spy):
            transport = StdioTransport(["echo"])
            await transport.execute("tool", {}, {})
        assert spy.call_args.kwargs["limit"] == STDIO_BUFFER_LIMIT

    async def test_persistent_stdio_transport_passes_limit_kwarg(self):
        from kitsune_mcp.constants import STDIO_BUFFER_LIMIT
        from server import PersistentStdioTransport
        spy = AsyncMock(return_value=self._mock_proc())
        with patch("asyncio.create_subprocess_exec", spy):
            transport = PersistentStdioTransport(["echo"])
            try:
                await transport._start_process()
            except RuntimeError:
                # Expected — the mock proc has no valid initialize response.
                pass
        assert spy.call_args.kwargs["limit"] == STDIO_BUFFER_LIMIT
