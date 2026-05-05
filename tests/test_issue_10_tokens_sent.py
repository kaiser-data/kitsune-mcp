"""Tests for issue #10: tokens_sent counter was 0 for stdio/websocket transports."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kitsune_mcp.session import session


def _reset_stats():
    session["stats"] = {"total_calls": 0, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}


def _make_stdio_mock(responses: list[bytes]):
    """Build a mock asyncio subprocess that returns given byte responses from readline."""
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.pid = 12345
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock(return_value=0)
    # After the provided responses, return b"" (EOF)
    mock_proc.stdout.readline = AsyncMock(side_effect=responses + [b""] * 10)
    return mock_proc


# --- StdioTransport ---

@pytest.mark.asyncio
async def test_stdio_transport_increments_tokens_sent():
    _reset_stats()
    from kitsune_mcp.transport import StdioTransport

    init_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}).encode() + b"\n"
    call_resp = json.dumps({
        "jsonrpc": "2.0", "id": 2,
        "result": {"content": [{"type": "text", "text": "pong"}]},
    }).encode() + b"\n"

    mock_proc = _make_stdio_mock([init_resp, call_resp])

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        t = StdioTransport(["fake-cmd"])
        await t.execute("ping", {"msg": "hello"}, {})

    assert session["stats"]["tokens_sent"] > 0, \
        f"tokens_sent should be > 0 after StdioTransport call, got {session['stats']['tokens_sent']}"


# --- PersistentStdioTransport ---

@pytest.mark.asyncio
async def test_persistent_stdio_transport_increments_tokens_sent():
    _reset_stats()
    from kitsune_mcp.transport import PersistentStdioTransport

    init_resp = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}).encode() + b"\n"
    call_resp = json.dumps({
        "jsonrpc": "2.0", "id": 3,
        "result": {"content": [{"type": "text", "text": "result text"}]},
    }).encode() + b"\n"

    mock_proc = _make_stdio_mock([init_resp, call_resp])

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        t = PersistentStdioTransport(["fake-cmd"])
        await t.execute("my_tool", {"param": "value"}, {})

    assert session["stats"]["tokens_sent"] > 0, \
        f"tokens_sent should be > 0 after PersistentStdioTransport call, got {session['stats']['tokens_sent']}"


# --- WebSocketTransport ---

@pytest.mark.asyncio
async def test_websocket_transport_increments_tokens_sent():
    _reset_stats()
    from kitsune_mcp.transport import WebSocketTransport

    call_resp = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "text", "text": "ws result"}]},
    })

    mock_ws = AsyncMock()
    mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
    mock_ws.__aexit__ = AsyncMock(return_value=False)
    mock_ws.send = AsyncMock()
    mock_ws.recv = AsyncMock(return_value=call_resp)

    with patch("websockets.connect", return_value=mock_ws):
        t = WebSocketTransport("ws://localhost:9999")
        await t.execute("ws_tool", {"x": 1}, {})

    assert session["stats"]["tokens_sent"] > 0, \
        f"tokens_sent should be > 0 after WebSocketTransport call, got {session['stats']['tokens_sent']}"
