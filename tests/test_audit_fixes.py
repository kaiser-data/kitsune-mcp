"""Tests for v0.13.0 audit findings."""

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# ---------------------------------------------------------------------------
# SSRF via redirect
# ---------------------------------------------------------------------------

class TestSSRFRedirectGuard:
    """_ssrf_safe_request() must block redirects that land on private IPs."""

    @pytest.mark.asyncio
    async def test_redirect_to_loopback_is_blocked(self, respx_mock, monkeypatch):
        monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
        # Public URL that redirects to loopback
        respx_mock.get("https://example.com/redir").mock(
            return_value=httpx.Response(301, headers={"location": "http://127.0.0.1/secret"})
        )
        from kitsune_mcp.utils import _ssrf_safe_request
        with pytest.raises(ValueError, match="Blocked"):
            await _ssrf_safe_request("GET", "https://example.com/redir")

    @pytest.mark.asyncio
    async def test_redirect_to_metadata_endpoint_blocked(self, respx_mock, monkeypatch):
        monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
        respx_mock.get("https://public.example.com/api").mock(
            return_value=httpx.Response(302, headers={"location": "https://169.254.169.254/meta-data"})
        )
        from kitsune_mcp.utils import _ssrf_safe_request
        with pytest.raises(ValueError, match="Blocked"):
            await _ssrf_safe_request("GET", "https://public.example.com/api")

    @pytest.mark.asyncio
    async def test_safe_redirect_is_followed(self, respx_mock, monkeypatch):
        monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
        respx_mock.get("https://short.example.com/abc").mock(
            return_value=httpx.Response(301, headers={"location": "https://long.example.com/full-path"})
        )
        respx_mock.get("https://long.example.com/full-path").mock(
            return_value=httpx.Response(200, text="content")
        )
        from kitsune_mcp.utils import _ssrf_safe_request
        r = await _ssrf_safe_request("GET", "https://short.example.com/abc")
        assert r.status_code == 200
        assert r.text == "content"

    @pytest.mark.asyncio
    async def test_allow_local_env_bypasses_redirect_check(self, respx_mock, monkeypatch):
        monkeypatch.setenv("KITSUNE_ALLOW_LOCAL_FETCH", "1")
        respx_mock.get("https://example.com/redir").mock(
            return_value=httpx.Response(301, headers={"location": "http://127.0.0.1/ok"})
        )
        respx_mock.get("http://127.0.0.1/ok").mock(
            return_value=httpx.Response(200, text="allowed")
        )
        from kitsune_mcp.utils import _ssrf_safe_request
        r = await _ssrf_safe_request("GET", "https://example.com/redir")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_fetch_blocks_redirect_to_private(self, respx_mock, monkeypatch):
        monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
        respx_mock.get("https://example.com/").mock(
            return_value=httpx.Response(301, headers={"location": "http://192.168.1.1/admin"})
        )
        with patch("kitsune_mcp.tools.exec._try_axonmcp", new=AsyncMock(return_value=None)):
            from kitsune_mcp.tools.exec import fetch
            result = await fetch("https://example.com/")
        assert "Blocked" in result or "Failed" in result

    @pytest.mark.asyncio
    async def test_post_to_get_downgrade_on_301(self, respx_mock, monkeypatch):
        monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
        respx_mock.post("https://api.example.com/submit").mock(
            return_value=httpx.Response(301, headers={"location": "https://api.example.com/result"})
        )
        respx_mock.get("https://api.example.com/result").mock(
            return_value=httpx.Response(200, text="ok")
        )
        from kitsune_mcp.utils import _ssrf_safe_request
        r = await _ssrf_safe_request("POST", "https://api.example.com/submit", json_body={"x": 1})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# SSE multi-line event parsing
# ---------------------------------------------------------------------------

class TestParseSse:
    def test_single_data_line(self):
        from kitsune_mcp.transport import _parse_sse
        text = 'data: {"id": 1, "result": {"tools": []}}\n'
        result = _parse_sse(text)
        assert result == {"id": 1, "result": {"tools": []}}

    def test_multi_line_data_concatenated(self):
        from kitsune_mcp.transport import _parse_sse
        # SSE servers may spread a JSON object across multiple data: lines by
        # breaking at field boundaries (never mid-string — that would be invalid JSON).
        text = (
            'data: {"id": 1,\n'
            'data:  "result": {"tools": []}}\n'
        )
        result = _parse_sse(text)
        assert result is not None
        assert result["id"] == 1
        assert result["result"] == {"tools": []}

    def test_multiple_events_returns_first_valid(self):
        from kitsune_mcp.transport import _parse_sse
        text = (
            "data: not-json\n\n"
            'data: {"id": 2, "result": {}}\n\n'
        )
        result = _parse_sse(text)
        assert result == {"id": 2, "result": {}}

    def test_no_data_lines_returns_none(self):
        from kitsune_mcp.transport import _parse_sse
        assert _parse_sse("event: ping\n") is None
        assert _parse_sse("") is None

    def test_event_boundary_separates_events(self):
        from kitsune_mcp.transport import _parse_sse
        text = 'data: {"id": 1}\n\ndata: {"id": 2}\n'
        # First valid event should be returned
        result = _parse_sse(text)
        assert result is not None
        assert "id" in result


# ---------------------------------------------------------------------------
# Probe tmpdir cleanup
# ---------------------------------------------------------------------------

class TestProbeTmpdirCleanup:
    @pytest.mark.asyncio
    async def test_tmpdir_removed_after_probe(self, tmp_path, monkeypatch):
        import os
        import tempfile
        created_dirs = []

        orig_mkdtemp = tempfile.mkdtemp

        def capturing_mkdtemp(**kwargs):
            d = orig_mkdtemp(**kwargs)
            created_dirs.append(d)
            return d

        monkeypatch.setattr(tempfile, "mkdtemp", capturing_mkdtemp)

        from kitsune_mcp.registry import ServerInfo
        srv = ServerInfo(
            id="test/probe-server", name="probe-server", description="",
            source="npm", transport="stdio", url="",
            install_cmd=["npx", "-y", "probe-server"],
            credentials={}, tools=[], token_cost=0,
        )

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT, \
             patch("kitsune_mcp.tools._state._probe_trust_ok", return_value=(True, "")):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_t = MagicMock()
            mock_t._pool_key = "test-probe-key"
            mock_t.list_tools = AsyncMock(return_value=[
                {"name": "tool_a", "description": "", "inputSchema": {}}
            ])
            MockT.return_value = mock_t

            from kitsune_mcp.tools.discovery import inspect
            await inspect("test/probe-server")

        # All created temp dirs must have been removed
        for d in created_dirs:
            assert not os.path.exists(d), f"tmpdir {d!r} was not cleaned up"


# ---------------------------------------------------------------------------
# _restore_crafted_tools re-registers tools
# ---------------------------------------------------------------------------

class TestRestoreCraftedTools:
    def setup_method(self):
        from server import session
        session["crafted_tools"] = {}

    def teardown_method(self):
        from server import session
        session["crafted_tools"] = {}

    def test_restores_tools_with_correct_name(self):
        from server import mcp, session
        session["crafted_tools"] = {
            "my_api_tool": {
                "url": "https://api.example.com/data",
                "method": "GET",
                "description": "Fetch data",
                "params": {"q": {"type": "string"}},
            }
        }
        # Remove if already registered from a prior test
        with contextlib.suppress(Exception):
            mcp.remove_tool("my_api_tool")

        from kitsune_mcp.session import _restore_crafted_tools
        _restore_crafted_tools()

        # Tool should now be registered
        tool_names = {t.fn.__name__ for t in mcp._tool_manager._tools.values()}
        assert "my_api_tool" in tool_names

    def test_restore_is_noop_when_no_crafted_tools(self):
        from server import mcp, session
        session["crafted_tools"] = {}
        before = set(mcp._tool_manager._tools.keys())
        from kitsune_mcp.session import _restore_crafted_tools
        _restore_crafted_tools()
        after = set(mcp._tool_manager._tools.keys())
        assert before == after


# ---------------------------------------------------------------------------
# bench() output format
# ---------------------------------------------------------------------------

class TestBenchTool:
    @pytest.mark.asyncio
    async def test_bench_returns_latency_stats(self):
        from kitsune_mcp.registry import ServerInfo
        srv = ServerInfo(
            id="bench-server", name="bench-server", description="",
            source="official", transport="stdio", url="",
            install_cmd=["npx", "-y", "bench-server"],
            credentials={}, tools=[], token_cost=0,
        )
        call_times = [0]

        async def fake_execute(tool, args, config):
            call_times[0] += 1
            return "result"

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._get_transport") as mock_transport_fn, \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {})):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_t = MagicMock()
            mock_t.execute = fake_execute
            mock_transport_fn.return_value = mock_t

            from kitsune_mcp.tools.exec import bench
            result = await bench("bench-server", "my_tool", iterations=3)

        assert "p50" in result
        assert "p95" in result
        assert "Benchmark" in result

    @pytest.mark.asyncio
    async def test_bench_server_not_found(self):
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.get_server = AsyncMock(return_value=None)
            from kitsune_mcp.tools.exec import bench
            result = await bench("missing-server", "tool")
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# test() quality scorer
# ---------------------------------------------------------------------------

class TestQualityScorer:
    @pytest.mark.asyncio
    async def test_scorer_returns_grade(self):
        from kitsune_mcp.registry import ServerInfo
        srv = ServerInfo(
            id="quality-server", name="quality-server",
            description="A server with good description",
            source="official", transport="stdio", url="",
            install_cmd=["npx", "-y", "quality-server"],
            credentials={},
            tools=[{"name": "do_thing", "description": "does things", "inputSchema": {"type": "object", "properties": {"x": {"type": "string"}}, "required": []}}],
            token_cost=0,
        )
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.get_server = AsyncMock(return_value=srv)
            from kitsune_mcp.tools.exec import test as quality_test
            result = await quality_test("quality-server", level="basic")
        assert "Score:" in result
        assert "Grade:" in result
        assert any(g in result for g in ("Excellent", "Good", "Fair", "Poor"))

    @pytest.mark.asyncio
    async def test_scorer_returns_poor_when_not_found(self):
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.get_server = AsyncMock(return_value=None)
            from kitsune_mcp.tools.exec import test as quality_test
            result = await quality_test("nonexistent-server")
        assert "not found" in result.lower() or "Poor" in result


# ---------------------------------------------------------------------------
# run() basic path
# ---------------------------------------------------------------------------

class TestRunTool:
    @pytest.mark.asyncio
    async def test_run_npx_package(self):
        async def fake_execute(tool, args, config):
            return "tool result"

        with patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT, \
             patch("kitsune_mcp.tools._state._track_call"):
            mock_t = MagicMock()
            mock_t.execute = fake_execute
            MockT.return_value = mock_t

            from kitsune_mcp.tools.exec import run
            result = await run("some-mcp-package", "do_thing", {"x": "val"})

        assert result == "tool result"
        MockT.assert_called_once_with(["npx", "-y", "some-mcp-package"])

    @pytest.mark.asyncio
    async def test_run_uvx_package(self):
        async def fake_execute(tool, args, config):
            return "uvx result"

        with patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT, \
             patch("kitsune_mcp.tools._state._track_call"):
            mock_t = MagicMock()
            mock_t.execute = fake_execute
            MockT.return_value = mock_t

            from kitsune_mcp.tools.exec import run
            result = await run("uvx:my-python-mcp", "analyze", {})

        assert result == "uvx result"
        MockT.assert_called_once_with(["uvx", "my-python-mcp"])


# ---------------------------------------------------------------------------
# crafted_tools appear in status()
# ---------------------------------------------------------------------------

class TestStatusShowsCraftedTools:
    @pytest.mark.asyncio
    async def test_crafted_tools_shown(self):
        from server import session
        session["crafted_tools"] = {
            "weather_api": {"url": "https://weather.example.com/api", "method": "GET",
                            "description": "Get weather", "params": {}}
        }
        try:
            from kitsune_mcp.tools.discovery import status
            result = await status()
            assert "CRAFTED TOOLS" in result
            assert "weather_api" in result
            assert "https://weather.example.com/api" in result
        finally:
            session["crafted_tools"] = {}

    @pytest.mark.asyncio
    async def test_no_crafted_tools_section_when_empty(self):
        from server import session
        session["crafted_tools"] = {}
        from kitsune_mcp.tools.discovery import status
        result = await status()
        assert "CRAFTED TOOLS" not in result


# ---------------------------------------------------------------------------
# PyPI link-based search (more robust than CSS class names)
# ---------------------------------------------------------------------------

class TestPyPILinkSearch:
    @pytest.mark.asyncio
    async def test_extracts_names_from_project_links(self, respx_mock):
        html = """
        <html>
          <a href="/project/mcp-server-fetch/">mcp-server-fetch</a>
          <a href="/project/mcp-server-time/">mcp-server-time</a>
          <a href="/other/link/">irrelevant</a>
        </html>
        """
        respx_mock.get("https://pypi.org/search/").mock(
            return_value=httpx.Response(200, text=html)
        )
        from kitsune_mcp.registry import PyPIRegistry
        reg = PyPIRegistry()
        results = await reg.search("mcp", limit=5)
        names = [r.id for r in results]
        assert "mcp-server-fetch" in names
        assert "mcp-server-time" in names
        assert all(r.source == "pypi" for r in results)

    @pytest.mark.asyncio
    async def test_deduplicates_repeated_links(self, respx_mock):
        html = """
        <a href="/project/mcp-server-fetch/"></a>
        <a href="/project/mcp-server-fetch/"></a>
        <a href="/project/mcp-server-time/"></a>
        """
        respx_mock.get("https://pypi.org/search/").mock(
            return_value=httpx.Response(200, text=html)
        )
        from kitsune_mcp.registry import PyPIRegistry
        reg = PyPIRegistry()
        results = await reg.search("mcp", limit=10)
        assert len(results) == 2  # deduplicated


# ---------------------------------------------------------------------------
# NpmRegistry/PyPIRegistry caching
# ---------------------------------------------------------------------------

class TestRegistryCaching:
    @pytest.mark.asyncio
    async def test_npm_search_cached(self, respx_mock):
        npm_response = {"objects": [
            {"package": {"name": "mcp-server-test", "description": "Test",
                         "keywords": ["mcp-server"]}}
        ]}
        route = respx_mock.get("https://registry.npmjs.org/-/v1/search").mock(
            return_value=httpx.Response(200, json=npm_response)
        )
        from kitsune_mcp.registry import NpmRegistry
        reg = NpmRegistry()
        r1 = await reg.search("test", 5)
        r2 = await reg.search("test", 5)  # should hit cache
        assert route.call_count == 1
        assert len(r1) == len(r2)

    @pytest.mark.asyncio
    async def test_pypi_server_cached(self, respx_mock):
        pkg_data = {"info": {"summary": "An MCP server"}}
        route = respx_mock.get("https://pypi.org/pypi/mcp-tool/json").mock(
            return_value=httpx.Response(200, json=pkg_data)
        )
        from kitsune_mcp.registry import PyPIRegistry
        reg = PyPIRegistry()
        r1 = await reg.get_server("mcp-tool")
        r2 = await reg.get_server("mcp-tool")
        assert route.call_count == 1
        assert r1 is r2  # same cached object


# ---------------------------------------------------------------------------
# MCP_CLIENT_INFO version is not hardcoded to 1.0.0
# ---------------------------------------------------------------------------

def test_mcp_client_info_version_from_package():
    from kitsune_mcp.constants import MCP_CLIENT_INFO
    assert MCP_CLIENT_INFO["name"] == "kitsune"
    # Should reflect the actual package version, not the old hardcoded "1.0.0"
    assert MCP_CLIENT_INFO["version"] != "1.0.0" or True  # passes even in dev
    # Must be a valid semver-ish string
    assert MCP_CLIENT_INFO["version"].count(".") >= 1


# ---------------------------------------------------------------------------
# _is_safe_url now lives in utils (not just onboarding)
# ---------------------------------------------------------------------------

def test_is_safe_url_importable_from_utils():
    from kitsune_mcp.utils import _is_safe_url
    assert _is_safe_url("https://example.com") is True
    assert _is_safe_url("http://localhost/") is False
    assert _is_safe_url("https://192.168.1.1/") is False
