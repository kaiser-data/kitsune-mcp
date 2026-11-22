"""Stdio servers get an answer to their requests, like HTTP servers do.

A server may ask the client something mid-call (ping, sampling/createMessage,
roots/list). Unanswered, it can wait forever before sending our result.
Kitsune answers ping and refuses the rest with "method not found".
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock

import kitsune_mcp.credentials as _creds
from kitsune_mcp.transport import (
    PersistentStdioTransport,
    _PoolEntry,
    _process_pool,
    _read_stdio_response,
)

from .conftest import make_mock_process, make_stdout_with_responses


def _writer():
    w = MagicMock()
    w.write = MagicMock()
    w.drain = AsyncMock()
    return w


def _sent(w):
    return [json.loads(c.args[0]) for c in w.write.call_args_list]


async def test_ping_and_sampling_are_answered_while_waiting():
    reader = make_stdout_with_responses(
        [
            {"jsonrpc": "2.0", "id": 7, "method": "ping"},
            {"jsonrpc": "2.0", "id": 8, "method": "sampling/createMessage", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "result": {"ok": True}},
        ]
    )
    w = _writer()
    msg = await _read_stdio_response(reader, 3, timeout=2, writer=w)
    assert msg == {"jsonrpc": "2.0", "id": 3, "result": {"ok": True}}
    replies = _sent(w)
    assert replies[0] == {"jsonrpc": "2.0", "id": 7, "result": {}}
    assert replies[1]["id"] == 8 and replies[1]["error"]["code"] == -32601
    assert len(replies) == 2  # notifications get no reply


async def test_without_a_writer_requests_are_skipped_as_before():
    reader = make_stdout_with_responses(
        [{"jsonrpc": "2.0", "id": 7, "method": "ping"}, {"jsonrpc": "2.0", "id": 3, "result": {}}]
    )
    assert await _read_stdio_response(reader, 3, timeout=2) == {
        "jsonrpc": "2.0",
        "id": 3,
        "result": {},
    }


async def test_a_broken_pipe_while_answering_does_not_raise():
    reader = make_stdout_with_responses(
        [{"jsonrpc": "2.0", "id": 7, "method": "ping"}, {"jsonrpc": "2.0", "id": 3, "result": {}}]
    )
    w = _writer()
    w.drain = AsyncMock(side_effect=BrokenPipeError())
    assert await _read_stdio_response(reader, 3, timeout=2, writer=w) is not None


async def test_persistent_call_answers_a_server_request_mid_call():
    t = PersistentStdioTransport(["asking-cmd"])
    proc = make_mock_process()
    proc.stdout = make_stdout_with_responses(
        [
            {"jsonrpc": "2.0", "id": 40, "method": "roots/list"},
            {"jsonrpc": "2.0", "id": 3, "result": {"content": [{"type": "text", "text": "done"}]}},
        ]
    )
    e = _PoolEntry(proc=proc, install_cmd=["asking-cmd"], started_at=time.monotonic())
    e.dotenv_revision = _creds._dotenv_revision
    _process_pool[t._pool_key] = e
    out = await t.execute("tool", {}, {})
    assert "done" in out
    sent = [json.loads(c.args[0]) for c in proc.stdin.write.call_args_list]
    assert sent[0]["method"] == "tools/call"
    assert sent[1] == {
        "jsonrpc": "2.0",
        "id": 40,
        "error": {"code": -32601, "message": "Method not supported: roots/list"},
    }
