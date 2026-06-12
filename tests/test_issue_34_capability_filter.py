"""Tests for issue #34 — auto() capability filter.

Without server_hint, the ranker routed web-search tasks to fetch tools,
chat-forwarders, and simulation servers. Three-part fix:
1. Generic intent verbs ("search", "web", …) are stripped from registry queries.
2. Candidates that don't advertise a tool matching the task's intent verb
   are dropped before ranking.
3. If no candidate matches, auto() returns a search()/server_hint suggestion
   instead of silently picking a wrong server.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _srv(**kwargs):
    from kitsune_mcp.registry import ServerInfo
    defaults = dict(
        id="test-server", name="Test Server", description="", source="official",
        transport="stdio", url="", install_cmd=["npx", "-y", "test-server"],
        credentials={}, tools=[], token_cost=0,
    )
    defaults.update(kwargs)
    return ServerInfo(**defaults)


# ---------------------------------------------------------------------------
# Part 1 — _search_query_for strips generic intent verbs
# ---------------------------------------------------------------------------

class TestQueryStripsIntentVerbs:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _search_query_for
        return _search_query_for

    def test_issue_repro_query(self):
        # The exact failing task from #34
        result = self._fn()("search the web for latest mcp server releases")
        assert "search" not in result.lower()
        assert "web" not in result.lower()
        assert "mcp" in result and "releases" in result

    def test_browse_and_lookup_stripped(self):
        result = self._fn()("browse documentation lookup tables")
        for verb in ("browse", "lookup"):
            assert verb not in result.lower()
        assert "documentation" in result

    def test_all_generic_falls_back_to_raw_task(self):
        # Nothing left after stripping → raw task, never empty
        assert self._fn()("web search") == "web search"


# ---------------------------------------------------------------------------
# Part 2 — _intent_verb / _matches_intent
# ---------------------------------------------------------------------------

class TestIntentVerb:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _intent_verb
        return _intent_verb

    def test_detects_search(self):
        assert self._fn()("search the web for news") == "search"

    def test_detects_fetch(self):
        assert self._fn()("fetch the contents of example.com") == "fetch"

    def test_no_verb_returns_empty(self):
        assert self._fn()("what time is it in Tokyo") == ""
        assert self._fn()("list issues on acme/api") == ""

    def test_word_boundary_not_substring(self):
        # "research" contains "search" but is not an intent verb
        assert self._fn()("summarize research papers") == ""


class TestMatchesIntent:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _matches_intent
        return _matches_intent

    def test_matches_on_description(self):
        srv = _srv(id="exa", name="Exa", description="Fast web search and crawling")
        assert self._fn()(srv, "search") is True

    def test_matches_on_tool_name(self):
        srv = _srv(tools=[{"name": "web_search", "inputSchema": {}}])
        assert self._fn()(srv, "search") is True

    def test_fetch_server_does_not_match_search(self):
        srv = _srv(
            id="fetch", name="Fetch",
            description="Web content fetching and conversion",
            tools=[{"name": "fetch", "inputSchema": {}}],
        )
        assert self._fn()(srv, "search") is False

    def test_find_maps_to_search_capability(self):
        srv = _srv(description="Search engine for developer docs")
        assert self._fn()(srv, "find") is True

    def test_crawl_matches_scrape_family(self):
        srv = _srv(tools=[{"name": "scrape_page", "inputSchema": {}}])
        assert self._fn()(srv, "crawl") is True


# ---------------------------------------------------------------------------
# Part 3 — auto() end-to-end: filter, rank, refuse
# ---------------------------------------------------------------------------

_SEARCH_TOOL = {
    "name": "web_search",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


class TestAutoCapabilityFilter:
    @pytest.mark.asyncio
    async def test_search_capable_server_beats_higher_ranked_fetch(self):
        """The #34 failure: official+stdio fetch tool outranked the actual
        search server. The capability filter must drop the fetch server."""
        fetcher = _srv(
            id="fetch", name="Fetch", source="official", transport="stdio",
            description="Web content fetching and markdown conversion",
            tools=[{"name": "fetch", "inputSchema": {
                "type": "object", "properties": {"url": {"type": "string"}},
                "required": ["url"]}}],
        )
        searcher = _srv(
            id="exa", name="Exa", source="smithery", transport="http",
            description="Fast, intelligent web search", tools=[_SEARCH_TOOL],
        )
        called: dict = {}

        async def fake_execute(tool, args, config):
            called["tool"] = tool
            return '{"results": ["ok"]}'

        transport = MagicMock()
        transport.execute = fake_execute

        with patch("kitsune_mcp.tools._state._registry") as reg, \
             patch("kitsune_mcp.tools._state._get_transport", return_value=transport):
            reg.search = AsyncMock(return_value=[fetcher, searcher])
            reg.get_server = AsyncMock(return_value=searcher)
            from kitsune_mcp.tools import auto
            result = await auto(task="search the web for latest mcp server releases")

        # The fetch server must never be chosen for a search task
        assert called.get("tool") == "web_search"
        assert "ok" in result

    @pytest.mark.asyncio
    async def test_no_matching_candidate_refuses_with_suggestion(self):
        """No search-capable candidate → guidance, not a random server."""
        fetcher = _srv(
            id="fetch", name="Fetch",
            description="Web content fetching",
            tools=[{"name": "fetch", "inputSchema": {}}],
        )
        git = _srv(id="git", name="Git", description="Git repository operations")

        transport = MagicMock()
        transport.execute = AsyncMock(return_value="should never run")

        with patch("kitsune_mcp.tools._state._registry") as reg, \
             patch("kitsune_mcp.tools._state._get_transport", return_value=transport):
            reg.search = AsyncMock(return_value=[fetcher, git])
            reg.get_server = AsyncMock(return_value=None)
            from kitsune_mcp.tools import auto
            result = await auto(task="search for python frameworks")

        assert "Blocked" in result
        assert "server_hint" in result
        assert "search(" in result
        transport.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_intent_verb_skips_filter(self):
        """Tasks without an intent verb keep the old behavior untouched."""
        clock = _srv(
            id="time-server", name="Time", description="Timezone conversions",
            tools=[{"name": "get_time", "inputSchema": {
                "type": "object", "properties": {"timezone": {"type": "string"}},
                "required": ["timezone"]}}],
        )
        transport = MagicMock()
        transport.execute = AsyncMock(return_value='{"time": "12:00"}')

        with patch("kitsune_mcp.tools._state._registry") as reg, \
             patch("kitsune_mcp.tools._state._get_transport", return_value=transport):
            reg.search = AsyncMock(return_value=[clock])
            reg.get_server = AsyncMock(return_value=clock)
            from kitsune_mcp.tools import auto
            result = await auto(task="what time is it in Tokyo", arguments={"timezone": "Asia/Tokyo"})

        assert "12:00" in result

    @pytest.mark.asyncio
    async def test_server_hint_bypasses_filter(self):
        """A pinned server is the caller's explicit choice — never filtered."""
        fetcher = _srv(
            id="fetch", name="Fetch", description="Web content fetching",
            tools=[{"name": "fetch", "inputSchema": {
                "type": "object", "properties": {"url": {"type": "string"}},
                "required": ["url"]}}],
        )
        transport = MagicMock()
        transport.execute = AsyncMock(return_value="fetched")

        with patch("kitsune_mcp.tools._state._registry") as reg, \
             patch("kitsune_mcp.tools._state._get_transport", return_value=transport):
            reg.search = AsyncMock(return_value=[])
            reg.get_server = AsyncMock(return_value=fetcher)
            from kitsune_mcp.tools import auto
            result = await auto(
                task="search the web", server_hint="fetch",
                arguments={"url": "https://example.com"},
            )

        assert "fetched" in result
