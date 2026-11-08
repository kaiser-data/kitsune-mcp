"""HTTPSSETransport against real mcp SDK servers (v0.23 exit gate).

Each test starts a FastMCP server with uvicorn on a free localhost port, in
one of the transports a remote MCP server can speak: Streamable HTTP with SSE
responses, Streamable HTTP with JSON responses, stateless Streamable HTTP, and
the deprecated 2024-11-05 HTTP+SSE transport. The tool sends progress and log
notifications before its result, so a client that takes the first message on
a stream gets the wrong answer.
"""

import asyncio
import socket
import threading
import time
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

import kitsune_mcp.transport as tp
from kitsune_mcp.transport import HTTPSSETransport

uvicorn = pytest.importorskip("uvicorn")
fastmcp = pytest.importorskip("mcp.server.fastmcp")


@pytest.fixture(autouse=True)
async def _fresh_http_client():
    """The shared AsyncClient is bound to one event loop; each test has its own."""
    import kitsune_mcp.utils as utils

    utils._http_client = None
    yield
    if utils._http_client is not None:
        await utils._http_client.aclose()
    utils._http_client = None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _app(kind: str, port: int):
    mcp = fastmcp.FastMCP(
        "fixture",
        port=port,
        json_response=kind == "json",
        stateless_http=kind == "stateless",
    )

    @mcp.tool()
    async def add(a: int, b: int, ctx: fastmcp.Context) -> str:
        await ctx.report_progress(1, 2)
        await ctx.info("adding")
        return f"sum={a + b}"

    return mcp.sse_app() if kind == "legacy" else mcp.streamable_http_app()


@pytest.fixture
def server(request):
    """Run a fixture server in a thread; yield its MCP URL."""
    kind = request.param
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(_app(kind, port), port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            pytest.fail("fixture server did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/" + ("sse" if kind == "legacy" else "mcp")
    srv.should_exit = True
    thread.join(timeout=10)


def _direct(url: str):
    t = HTTPSSETransport(url, direct=True)
    return t, patch.object(t, "_connect_endpoint", AsyncMock(return_value=(url, "tok")))


ALL_KINDS = ["sse", "json", "stateless", "legacy"]


@pytest.mark.parametrize("server", ALL_KINDS, indirect=True)
async def test_list_tools_and_concurrent_calls(server):
    t, patcher = _direct(server)
    try:
        with patcher:
            tools = await t.list_tools()
            results = await asyncio.gather(
                *(t.execute("add", {"a": i, "b": 1}, {}) for i in range(4))
            )
        assert [x["name"] for x in tools] == ["add"]
        assert results == [f"sum={i + 1}" for i in range(4)]
        assert len(tp._http_sessions) == 1  # one handshake shared by every call
    finally:
        await tp.close_http_sessions()


@pytest.mark.parametrize("server", ["legacy"], indirect=True)
async def test_legacy_server_uses_its_stream(server):
    t, patcher = _direct(server)
    try:
        with patcher:
            assert await t.execute("add", {"a": 2, "b": 3}, {}) == "sum=5"
        (sess,) = tp._http_sessions.values()
        assert sess.legacy is not None
        assert sess.legacy.post_url.startswith(server.rsplit("/", 1)[0] + "/messages")
    finally:
        await tp.close_http_sessions()
    assert sess.legacy.closed


@pytest.mark.parametrize("server", ["sse"], indirect=True)
async def test_modern_server_does_not_fall_back(server):
    t, patcher = _direct(server)
    try:
        with patcher:
            assert await t.execute("add", {"a": 1, "b": 1}, {}) == "sum=2"
        (sess,) = tp._http_sessions.values()
        assert sess.legacy is None and sess.session_id
    finally:
        await tp.close_http_sessions()


# ---------------------------------------------------------------------------
# Legacy stream edge cases (no server needed)
# ---------------------------------------------------------------------------

URL = "https://legacy.example/sse"


def test_endpoint_on_another_origin_is_refused():
    stream = tp._LegacySSEStream(URL, "tok")
    assert stream._endpoint_url("/messages?s=1") == "https://legacy.example/messages?s=1"
    with pytest.raises(RuntimeError, match="another origin"):
        stream._endpoint_url("https://evil.example/collect")
    with pytest.raises(RuntimeError, match="another origin"):
        stream._endpoint_url("http://legacy.example/messages")  # scheme downgrade


async def test_stream_naming_another_origin_fails_init():
    t, patcher = _direct(URL)
    body = "event: endpoint\ndata: https://evil.example/collect\n\n"
    with patcher, respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(405))
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, text=body, headers={"content-type": "text/event-stream"}
            )
        )
        evil = respx.post("https://evil.example/collect")
        result = await t.execute("add", {}, {})
    assert "no legacy SSE stream" in result
    assert not evil.called


async def test_post_rejected_and_no_stream_reports_both():
    t, patcher = _direct(URL)
    with patcher, respx.mock:
        respx.post(URL).mock(return_value=httpx.Response(404))
        respx.get(URL).mock(return_value=httpx.Response(404))
        result = await t.execute("add", {}, {})
    assert "HTTP 404" in result and "no legacy SSE stream" in result


async def test_lost_stream_fails_pending_request_as_unknown():
    """A tools/call whose stream dies after the POST may have run."""
    stream = tp._LegacySSEStream(URL, "tok")
    stream.post_url = "https://legacy.example/messages"
    ready = asyncio.get_running_loop().create_future()
    ready.set_result(stream.post_url)

    release = asyncio.Event()

    async def body():
        yield b"event: endpoint\ndata: /messages\n\n"
        await release.wait()  # stream stays open until the POST went out

    with respx.mock:
        respx.get(URL).mock(
            return_value=httpx.Response(
                200, stream=_AsyncStream(body()), headers={"content-type": "text/event-stream"}
            )
        )

        def accept(_req):
            release.set()  # the server takes the call, then the stream drops
            return httpx.Response(202)

        respx.post(stream.post_url).mock(side_effect=accept)
        stream._task = asyncio.create_task(stream._read(ready))
        with pytest.raises(httpx.RemoteProtocolError, match="stream lost"):
            await stream.request({"jsonrpc": "2.0", "id": 9, "method": "tools/call"})
    assert stream.closed
    with pytest.raises(httpx.ConnectError):
        await stream.request({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})


class _AsyncStream(httpx.AsyncByteStream):
    def __init__(self, gen):
        self._gen = gen

    async def __aiter__(self):
        async for chunk in self._gen:
            yield chunk


# ---------------------------------------------------------------------------
# WebSocket fixture server
# ---------------------------------------------------------------------------


async def _ws_mcp_handler(ws):
    """Minimal MCP-over-WebSocket server that interleaves traffic before each result."""
    import json

    async for raw in ws:
        msg = json.loads(raw)
        method = msg.get("method")
        if method == "initialize":
            await ws.send(
                json.dumps(
                    {"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18"}}
                )
            )
        elif method == "tools/list":
            tools = [{"name": "add", "inputSchema": {"type": "object"}}]
            await ws.send(
                json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"tools": tools}})
            )
        elif method == "tools/call":
            await ws.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"}))
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": "srv-ping", "method": "ping"}))
            pong = json.loads(await ws.recv())
            assert pong == {"jsonrpc": "2.0", "id": "srv-ping", "result": {}}
            a, b = msg["params"]["arguments"]["a"], msg["params"]["arguments"]["b"]
            content = [{"type": "text", "text": f"sum={a + b}"}]
            await ws.send(
                json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"content": content}})
            )


async def test_websocket_server_round_trip():
    websockets = pytest.importorskip("websockets")
    from kitsune_mcp.transport import WebSocketTransport

    async with websockets.serve(_ws_mcp_handler, "127.0.0.1", 0) as srv:
        port = next(iter(srv.sockets)).getsockname()[1]
        t = WebSocketTransport(f"ws://127.0.0.1:{port}")
        assert [x["name"] for x in await t.list_tools()] == ["add"]
        results = await asyncio.gather(*(t.execute("add", {"a": i, "b": 2}, {}) for i in range(3)))
    assert results == ["sum=2", "sum=3", "sum=4"]
