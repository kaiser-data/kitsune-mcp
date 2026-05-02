"""Tests for fuzzy server-id resolution: _normalize_for_match, _resolve_server_id,
and the shapeshift() auto-recovery path.

Driven by GitHub issue #6 — agent submitted `@modelcontextprotocol/server-time`
which doesn't exist; the canonical id is `mcp-server-time`. Auto-resolution
should turn that into a successful shapeshift on the first call, no second turn
required.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# _normalize_for_match: pure string normalization
# ---------------------------------------------------------------------------

class TestNormalizeForMatch:
    def _fn(self):
        from kitsune_mcp.tools._state import _normalize_for_match
        return _normalize_for_match

    def test_strips_at_scope_prefix(self):
        assert self._fn()("@modelcontextprotocol/server-time") == "time"

    def test_strips_mcp_server_prefix(self):
        assert self._fn()("mcp-server-time") == "time"

    def test_strips_server_mcp_prefix(self):
        assert self._fn()("server-mcp-fetch") == "fetch"

    def test_strips_mcp_dash_prefix(self):
        assert self._fn()("mcp-fetch") == "fetch"

    def test_strips_mcp_server_suffix(self):
        assert self._fn()("foo-mcp-server") == "foo"

    def test_strips_mcp_suffix(self):
        assert self._fn()("foo-bar-mcp") == "foobar"

    def test_lowercases_and_strips_punctuation(self):
        assert self._fn()("FOO_BAR.baz") == "foobarbaz"

    def test_empty_input_returns_empty(self):
        assert self._fn()("") == ""

    def test_none_safe(self):
        assert self._fn()(None) == ""

    def test_at_scope_and_suffix_combined(self):
        # @scope/foo-mcp → after @scope/ strip: "foo-mcp" → after -mcp suffix: "foo"
        assert self._fn()("@scope/foo-mcp") == "foo"

    def test_canonical_and_typo_match(self):
        # The exact failure mode reported in issue #6.
        fn = self._fn()
        assert fn("@modelcontextprotocol/server-time") == fn("mcp-server-time")


# ---------------------------------------------------------------------------
# _resolve_server_id: registry-backed fuzzy lookup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestResolveServerId:
    @staticmethod
    def _srv(server_id: str, source: str = "official"):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id=server_id, name=server_id.rsplit("/", 1)[-1],
            description="", source=source, transport="stdio",
        )

    async def test_returns_none_when_input_normalizes_empty(self):
        from kitsune_mcp.tools._state import _resolve_server_id
        # All-punctuation input normalizes to "" — short-circuit, no registry call
        rid, cands = await _resolve_server_id("---")
        assert rid is None
        assert cands == []

    async def test_single_exact_match_returns_canonical_id(self):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools._state import _resolve_server_id

        time_srv = self._srv("mcp-server-time")
        unrelated = self._srv("timely")  # normalizes to "timely", not "time"

        with patch.object(_state, "_registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[time_srv, unrelated])
            rid, cands = await _resolve_server_id("@modelcontextprotocol/server-time")
        assert rid == "mcp-server-time"
        assert cands == ["mcp-server-time"]

    async def test_duplicate_ids_from_search_are_deduped(self):
        """If search() ever returns the same canonical id twice (defensive — should
        not happen in practice since MultiRegistry already dedupes by name), the
        resolver still returns a single match instead of treating it as ambiguous."""
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools._state import _resolve_server_id

        official = self._srv("mcp-server-time", source="official")
        npm_dup = self._srv("mcp-server-time", source="npm")

        with patch.object(_state, "_registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[npm_dup, official])
            rid, cands = await _resolve_server_id("server-time")
        assert rid == "mcp-server-time"
        assert cands == ["mcp-server-time"]

    async def test_no_exact_multiple_substring_returns_none_with_candidates(self):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools._state import _resolve_server_id

        # Searching "time" matches multiple substrings, no single exact normalize match
        candidates = [
            self._srv("timely"),       # "timely" contains "time" substring
            self._srv("wakatime"),     # "wakatime" contains "time" substring
            self._srv("timetracker"),  # "timetracker" contains "time" substring
        ]
        with patch.object(_state, "_registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=candidates)
            rid, cands = await _resolve_server_id("time")
        assert rid is None  # don't auto-pick when ambiguous
        assert "timely" in cands
        assert len(cands) <= 3  # capped to 3 suggestions

    async def test_no_match_returns_empty(self):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools._state import _resolve_server_id
        with patch.object(_state, "_registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[])
            rid, cands = await _resolve_server_id("totally-bogus-name-xyz")
        assert rid is None
        assert cands == []

    async def test_search_exception_returns_none(self):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools._state import _resolve_server_id
        with patch.object(_state, "_registry") as mock_reg:
            mock_reg.search = AsyncMock(side_effect=RuntimeError("network down"))
            rid, cands = await _resolve_server_id("anything")
        assert rid is None
        assert cands == []


# ---------------------------------------------------------------------------
# shapeshift() auto-recovery integration: end-to-end on the failure path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestShapeshiftAutoResolve:
    @staticmethod
    def _make_ctx():
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()
        return ctx

    @staticmethod
    def _srv(server_id: str):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id=server_id, name=server_id, description="time tools",
            source="official", transport="stdio",
            install_cmd=["uvx", "mcp-server-time"], credentials={}, tools=[],
        )

    async def test_typo_auto_resolves_to_canonical_id(self):
        """The exact issue #6 scenario: wrong namespace silently recovers."""
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        # Mock state: first lookup fails, search returns the canonical, second lookup succeeds.
        canonical = self._srv("mcp-server-time")

        async def get_server(server_id, source_preference=None):
            return canonical if server_id == "mcp-server-time" else None

        with patch.object(_registry, "get_server", AsyncMock(side_effect=get_server)), \
             patch.object(_registry, "search", AsyncMock(return_value=[canonical])), \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as MockT, \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={"missing_env": []}):
            mt = MagicMock()
            mt.list_tools = AsyncMock(return_value=[
                {"name": "get_current_time", "description": "now", "inputSchema": {"type": "object", "properties": {}}}
            ])
            mt.list_resources = AsyncMock(return_value=[])
            mt.list_prompts = AsyncMock(return_value=[])
            MockT.return_value = mt
            result = await shapeshift("@modelcontextprotocol/server-time", self._make_ctx())

        assert result.startswith("Shapeshifted into 'mcp-server-time'")
        assert "Auto-resolved from '@modelcontextprotocol/server-time'" in result

    async def test_no_match_returns_failure_marker(self):
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        with patch.object(_registry, "get_server", AsyncMock(return_value=None)), \
             patch.object(_registry, "search", AsyncMock(return_value=[])):
            result = await shapeshift("totally-bogus-name-xyz", self._make_ctx())

        assert result.startswith("❌ shapeshift failed:")
        assert "not found" in result.lower()

    async def test_multiple_candidates_lists_suggestions(self):
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        # Three substring matches, none exact-equal — caller gets a "did you mean" list
        from kitsune_mcp.registry import ServerInfo
        candidates = [
            ServerInfo(id="timely", name="timely", description="", source="npm", transport="stdio"),
            ServerInfo(id="wakatime", name="wakatime", description="", source="npm", transport="stdio"),
            ServerInfo(id="timetracker", name="timetracker", description="", source="npm", transport="stdio"),
        ]

        with patch.object(_registry, "get_server", AsyncMock(return_value=None)), \
             patch.object(_registry, "search", AsyncMock(return_value=candidates)):
            result = await shapeshift("time", self._make_ctx())

        assert result.startswith("❌ shapeshift failed:")
        assert "Did you mean" in result
        assert "timely" in result

    async def test_failure_messages_are_machine_detectable(self):
        """All shapeshift failure paths return strings starting with ❌."""
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        # Smithery-required-but-missing-key path
        with patch("kitsune_mcp.tools._state._smithery_available", return_value=False):
            result = await shapeshift("anything", self._make_ctx(), source="smithery")
        assert result.startswith("❌")

        # Server-not-found path (no candidates either)
        with patch.object(_registry, "get_server", AsyncMock(return_value=None)), \
             patch.object(_registry, "search", AsyncMock(return_value=[])):
            result = await shapeshift("totally-bogus-zzz", self._make_ctx())
        assert result.startswith("❌")
