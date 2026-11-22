"""Discovery fixes: tools/list pagination, shed only after tools are known,
PyPI resolution, and live official listings that are not curated."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import respx

import kitsune_mcp.credentials as _creds
import kitsune_mcp.official_registry as oreg
from kitsune_mcp.registry import MultiRegistry, PyPIRegistry
from kitsune_mcp.transport import (
    HTTPSSETransport,
    PersistentStdioTransport,
    _paginate_list,
    _PoolEntry,
    _process_pool,
)
from server import ServerInfo, _registry, session, shapeshift

from .conftest import make_mock_process, make_stdout_with_responses

ENDPOINT = "https://srv.example/mcp"


def _sse(payload: dict, session_id: str | None = None) -> httpx.Response:
    headers = {"content-type": "text/event-stream"}
    if session_id:
        headers["mcp-session-id"] = session_id
    return httpx.Response(200, text=f"data: {json.dumps(payload)}\n\n", headers=headers)


def _tool(name: str) -> dict:
    return {"name": name, "description": "", "inputSchema": {}}


# --- tools/list pagination ---------------------------------------------------


class TestPagination:
    async def test_http_list_tools_follows_next_cursor(self):
        seen_cursors = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content or b"{}")
            method = body.get("method", "")
            if method == "initialize":
                return _sse({"jsonrpc": "2.0", "id": body["id"], "result": {}}, "sid")
            if method.startswith("notifications/"):
                return httpx.Response(202)
            cursor = (body.get("params") or {}).get("cursor")
            seen_cursors.append(cursor)
            if cursor is None:
                result = {"tools": [_tool("a")], "nextCursor": "p2"}
            else:
                result = {"tools": [_tool("b")]}
            return _sse({"jsonrpc": "2.0", "id": body["id"], "result": result})

        t = HTTPSSETransport("org/server")
        with (
            patch.object(t, "_connect_endpoint", AsyncMock(return_value=(ENDPOINT, ""))),
            respx.mock,
        ):
            respx.post(ENDPOINT).mock(side_effect=handler)
            tools = await t.list_tools()
        assert [x["name"] for x in tools] == ["a", "b"]
        assert seen_cursors == [None, "p2"]

    async def test_stdio_list_tools_follows_next_cursor(self):
        t = PersistentStdioTransport(["paged-cmd"])
        proc = make_mock_process()
        proc.stdout = make_stdout_with_responses(
            [
                {"jsonrpc": "2.0", "id": 3, "result": {"tools": [_tool("a")], "nextCursor": "p2"}},
                {"jsonrpc": "2.0", "id": 4, "result": {"tools": [_tool("b")]}},
            ]
        )
        e = _PoolEntry(proc=proc, install_cmd=["paged-cmd"], started_at=time.monotonic())
        e.dotenv_revision = _creds._dotenv_revision
        _process_pool[t._pool_key] = e
        tools = await t.list_tools()
        assert [x["name"] for x in tools] == ["a", "b"]
        sent = [json.loads(c.args[0]) for c in proc.stdin.write.call_args_list]
        assert sent[1]["params"] == {"cursor": "p2"}

    async def test_repeated_cursor_stops(self):
        calls = []

        async def fetch(params: dict) -> dict:
            calls.append(params)
            return {"tools": [_tool(f"t{len(calls)}")], "nextCursor": "same"}

        tools = await _paginate_list(fetch, "tools")
        assert len(calls) == 2  # second page repeats the cursor: stop, don't loop
        assert len(tools) == 2


# --- shapeshift sheds only once the new tools are known ----------------------


def _srv() -> ServerInfo:
    return ServerInfo(
        id="org/empty-server",
        name="empty-server",
        description="",
        source="official",
        transport="stdio",
        url="",
        install_cmd=["npx", "-y", "empty-server"],
        credentials={},
        tools=[],
        token_cost=0,
    )


class TestShedAfterFetch:
    async def test_no_tools_keeps_current_form(self):
        shed = MagicMock(return_value=[])
        with (
            patch.object(_registry, "get_server", AsyncMock(return_value=_srv())),
            patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT,
            patch("kitsune_mcp.tools._state._do_shed", shed),
        ):
            MockT.return_value.list_tools = AsyncMock(return_value=[])
            result = await shapeshift("org/empty-server", MagicMock())
        assert result.startswith("❌") and "no tools found" in result.lower()
        shed.assert_not_called()

    async def test_pool_connection_without_tools_keeps_current_form(self):
        shed = MagicMock(return_value=[])
        session["connections"]["k"] = {"name": "bare", "command": "bare-cmd", "tools": []}
        try:
            with (
                patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT,
                patch("kitsune_mcp.tools._state._do_shed", shed),
            ):
                MockT.return_value.list_tools = AsyncMock(return_value=[])
                result = await shapeshift("bare", MagicMock())
        finally:
            session["connections"].pop("k", None)
        assert result.startswith("❌")
        shed.assert_not_called()


# --- PyPI ----------------------------------------------------------------------


class TestPyPI:
    def test_multi_registry_resolves_through_pypi(self):
        reg = MultiRegistry()
        assert any(isinstance(r, PyPIRegistry) for r in reg._registries)
        assert "pypi" in reg._reg_names

    async def test_search_falls_back_to_exact_names_when_html_has_no_links(self):
        with respx.mock:
            respx.get("https://pypi.org/search/").mock(
                return_value=httpx.Response(200, text="<html>challenge</html>")
            )
            respx.get("https://pypi.org/pypi/mcp-server-time/json").mock(
                return_value=httpx.Response(
                    200, json={"info": {"summary": "Time tools", "version": "1.0"}}
                )
            )
            respx.get(url__regex=r"https://pypi\.org/pypi/.+/json").mock(
                return_value=httpx.Response(404)
            )
            results = await PyPIRegistry().search("time", 5)
        assert [r.id for r in results] == ["mcp-server-time"]
        assert results[0].source == "pypi" and results[0].description == "Time tools"


# --- live official listing -----------------------------------------------------


class TestLiveOfficialTrust:
    async def test_uncurated_src_directory_is_not_official(self):
        oreg._live_cache.clear()
        try:
            with respx.mock:
                respx.get(oreg._GITHUB_SRC_API).mock(
                    return_value=httpx.Response(200, json=[{"name": "brand-new", "type": "dir"}])
                )
                servers = await oreg._fetch_live_servers()
        finally:
            oreg._live_cache.clear()
        new = [s for s in servers if s.id == "@modelcontextprotocol/server-brand-new"]
        assert new, "live directory should still be listed"
        assert new[0].source != "official"
        assert all(s.source == "official" for s in servers if s.id in oreg._SEED_BY_ID)


class TestPyPICandidates:
    def test_candidates(self):
        c = PyPIRegistry._exact_candidates
        assert c("time") == ["mcp-server-time", "time-mcp", "mcp-time"]
        assert c("github issues") == [
            "mcp-server-github-issues",
            "github-issues-mcp",
            "mcp-github-issues",
        ]
        assert c("mcp-server-time") == ["mcp-server-time"]
        assert c("mcp") == [] and c("") == [] and c("@scope/pkg") == []

    async def test_get_server_skips_names_pypi_cannot_have(self):
        with respx.mock(assert_all_called=False) as m:
            route = m.get(url__regex=r"https://pypi\.org/.*").mock(return_value=httpx.Response(500))
            for bad in ("@scope/pkg", "owner/repo", "https://x.example/mcp", "a b"):
                assert await PyPIRegistry().get_server(bad) is None
        assert not route.called
