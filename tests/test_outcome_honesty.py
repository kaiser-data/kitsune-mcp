"""A call that was sent but got no reply may have run: say so, never "try again".

Also: only a JSON-RPC *response* answers a request. A server-to-client request
that happens to reuse our id is not the result of our call.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock, patch

import httpx
import respx

import kitsune_mcp.credentials as _creds
import kitsune_mcp.transport as tp
from kitsune_mcp.transport import (
    HTTPSSETransport,
    PersistentStdioTransport,
    StdioTransport,
    _PoolEntry,
    _process_pool,
    _read_stdio_response,
)

from .conftest import make_mock_process, make_stdout_with_responses

ENDPOINT = "https://srv.example/mcp"
INIT_OK = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18"}}


def _sse(payload: dict, session_id: str | None = None) -> httpx.Response:
    headers = {"content-type": "text/event-stream"}
    if session_id:
        headers["mcp-session-id"] = session_id
    return httpx.Response(200, text=f"data: {json.dumps(payload)}\n\n", headers=headers)


class TestReaderAcceptsOnlyResponses:
    async def test_server_request_with_our_id_is_not_our_result(self):
        reader = make_stdout_with_responses(
            [
                {"jsonrpc": "2.0", "id": 3, "method": "sampling/createMessage", "params": {}},
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {"content": [{"type": "text", "text": "real"}]},
                },
            ]
        )
        msg = await _read_stdio_response(reader, 3, timeout=1)
        assert msg is not None and "result" in msg and "method" not in msg

    async def test_message_without_result_or_error_is_skipped(self):
        reader = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 3}, {"jsonrpc": "2.0", "id": 3, "error": {"message": "x"}}]
        )
        msg = await _read_stdio_response(reader, 3, timeout=1)
        assert msg == {"jsonrpc": "2.0", "id": 3, "error": {"message": "x"}}


class TestStdioNoReplyAfterSend:
    async def test_persistent_alive_but_silent_is_outcome_unknown(self):
        t = PersistentStdioTransport(["quiet-cmd"])
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses([])  # nothing, process stays alive
        e = _PoolEntry(proc=proc, install_cmd=["quiet-cmd"], started_at=time.monotonic())
        e.dotenv_revision = _creds._dotenv_revision
        _process_pool[t._pool_key] = e
        result = await t.execute("write_file", {}, {})
        assert "outcome unknown" in result and "may have run" in result
        assert "write_file" in result

    async def test_one_shot_stdio_silent_is_outcome_unknown(self):
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses([INIT_OK])
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
            result = await StdioTransport(["one-cmd"]).execute("write_file", {}, {})
        assert "outcome unknown" in result and "write_file" in result


def _http_route(slow_method: str):
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        method = body.get("method", "")
        if method == slow_method:
            await asyncio.sleep(5)
        if method == "initialize":
            return _sse(INIT_OK, "sid")
        if method.startswith("notifications/"):
            return httpx.Response(202)
        return _sse({"jsonrpc": "2.0", "id": body.get("id"), "result": {}})

    return handler


class TestHTTPTimeout:
    async def test_timeout_after_call_sent_is_outcome_unknown(self, monkeypatch):
        monkeypatch.setattr(tp, "TIMEOUT_HTTP_TOOL", 0.3)
        t = HTTPSSETransport("org/server")
        with (
            patch.object(t, "_connect_endpoint", AsyncMock(return_value=(ENDPOINT, ""))),
            respx.mock,
        ):
            respx.post(ENDPOINT).mock(side_effect=_http_route("tools/call"))
            result = await t.execute("send_email", {}, {})
        assert "outcome unknown" in result and "send_email" in result
        assert "try again" not in result

    async def test_timeout_before_call_sent_suggests_retry(self, monkeypatch):
        monkeypatch.setattr(tp, "TIMEOUT_HTTP_TOOL", 0.3)
        t = HTTPSSETransport("org/server")
        with (
            patch.object(t, "_connect_endpoint", AsyncMock(return_value=(ENDPOINT, ""))),
            respx.mock,
        ):
            respx.post(ENDPOINT).mock(side_effect=_http_route("initialize"))
            result = await t.execute("send_email", {}, {})
        assert "try again" in result
        assert "outcome unknown" not in result
