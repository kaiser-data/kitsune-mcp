"""fetch() reports a blocked or failed request as a tool error (isError), not as content."""

from unittest.mock import AsyncMock, patch

import anyio
import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.memory import create_client_server_memory_streams

from kitsune_mcp.tools.exec import fetch


@pytest.fixture(autouse=True)
def _no_external_fetcher(monkeypatch):
    monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
    with patch("kitsune_mcp.tools.exec._try_axonmcp", new=AsyncMock(return_value=None)):
        yield


async def _call_over_mcp(url: str):
    srv = MCPServer("t")
    srv.add_tool(fetch)
    server = srv._lowlevel_server
    async with create_client_server_memory_streams() as (cs, ss):
        async with anyio.create_task_group() as tg:
            tg.start_soon(server.run, *ss, server.create_initialization_options())
            async with ClientSession(*cs) as client:
                await client.initialize()
                r = await client.call_tool("fetch", {"url": url})
            tg.cancel_scope.cancel()
    return r.is_error, "".join(getattr(b, "text", "") for b in r.content)


async def test_blocked_url_is_a_tool_error_over_mcp():
    is_error, text = await _call_over_mcp("http://169.254.169.254/latest/meta-data/")
    assert is_error is True
    assert "Blocked" in text


async def test_failed_fetch_is_a_tool_error_over_mcp(respx_mock):
    respx_mock.get("https://example.com/").mock(return_value=httpx.Response(503))
    is_error, text = await _call_over_mcp("https://example.com/")
    assert is_error is True
    assert "Failed to fetch" in text and "503" in text


async def test_successful_fetch_is_content(respx_mock):
    respx_mock.get("https://example.com/").mock(return_value=httpx.Response(200, text="hello"))
    is_error, text = await _call_over_mcp("https://example.com/")
    assert is_error is False
    assert "hello" in text


async def test_direct_call_raises_tool_error():
    with pytest.raises(ToolError, match="Blocked"):
        await fetch("http://127.0.0.1/")
