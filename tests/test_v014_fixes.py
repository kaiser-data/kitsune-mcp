"""Tests for v0.14.0 — auto() NL routing, arg inference, status liveness."""

import pytest
from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# Fix A: _simple_search word-based matching
# ---------------------------------------------------------------------------

class TestSimpleSearch:
    def _servers(self):
        from kitsune_mcp.registry import ServerInfo
        return [
            ServerInfo(id="mcp-server-time", name="Time", description="Time queries and timezone conversions.",
                       source="official", transport="stdio", url="", install_cmd=[], credentials={}, tools=[], token_cost=0),
            ServerInfo(id="brave-search", name="Brave Search", description="Privacy-focused web search.",
                       source="smithery", transport="http", url="", install_cmd=[], credentials={}, tools=[], token_cost=0),
            ServerInfo(id="mcp-server-fetch", name="Fetch", description="Fetch web pages.",
                       source="official", transport="stdio", url="", install_cmd=[], credentials={}, tools=[], token_cost=0),
        ]

    def test_nl_query_finds_time_server(self):
        from kitsune_mcp.registry import _simple_search
        results = _simple_search(self._servers(), "what time is it in Tokyo", 5)
        ids = [r.id for r in results]
        assert "mcp-server-time" in ids, "mcp-server-time should match NL query containing 'time'"

    def test_single_keyword_still_works(self):
        from kitsune_mcp.registry import _simple_search
        results = _simple_search(self._servers(), "fetch", 5)
        ids = [r.id for r in results]
        assert "mcp-server-fetch" in ids

    def test_multi_word_query_any_word_matches(self):
        from kitsune_mcp.registry import _simple_search
        results = _simple_search(self._servers(), "brave privacy search", 5)
        ids = [r.id for r in results]
        assert "brave-search" in ids

    def test_empty_query_returns_all(self):
        from kitsune_mcp.registry import _simple_search
        servers = self._servers()
        results = _simple_search(servers, "", 10)
        assert len(results) == len(servers)

    def test_short_words_under_3_chars_skipped(self):
        from kitsune_mcp.registry import _simple_search
        # "is it in" are all ≤ 2 chars → stripped → no match on bare stop words alone
        results = _simple_search(self._servers(), "is it in", 5)
        # Should not error; may return empty or partial based on 3+ char words
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Fix B: _search_query_for keyword extraction
# ---------------------------------------------------------------------------

class TestSearchQueryFor:
    def test_strips_nl_filler_words(self):
        from kitsune_mcp.tools.onboarding import _search_query_for
        result = _search_query_for("what time is it in Tokyo")
        assert "time" in result
        assert "Tokyo" in result
        assert "what" not in result
        assert "is" not in result

    def test_preserves_search_content(self):
        from kitsune_mcp.tools.onboarding import _search_query_for
        result = _search_query_for("search for AI news")
        assert "news" in result

    def test_bare_query_unchanged(self):
        from kitsune_mcp.tools.onboarding import _search_query_for
        result = _search_query_for("brave search")
        assert "brave" in result
        assert "search" in result

    def test_fallback_when_all_stripped(self):
        from kitsune_mcp.tools.onboarding import _search_query_for
        # All words are stop words — should fall back to original task
        result = _search_query_for("what is it")
        assert result  # non-empty


# ---------------------------------------------------------------------------
# Fix C: _infer_args_from_task NL-aware filling
# ---------------------------------------------------------------------------

class TestInferArgsNLAware:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _infer_args_from_task
        return _infer_args_from_task

    def test_timezone_not_filled_with_nl_question(self):
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"timezone": {"type": "string"}},
                                  "required": ["timezone"]}}
        result = self._fn()(schema, "what time is it in Tokyo")
        assert result == {}, f"timezone must not get NL sentence, got {result}"

    def test_query_always_filled(self):
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"query": {"type": "string"}},
                                  "required": ["query"]}}
        result = self._fn()(schema, "what time is it in Tokyo")
        assert result == {"query": "what time is it in Tokyo"}

    def test_user_question_filled_with_nl(self):
        # user_question is in _SEARCH_PARAM_NAMES — QA tools should get the question
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"user_question": {"type": "string"},
                                                 "max_tokens": {"type": "integer"}},
                                  "required": ["user_question"]}}
        result = self._fn()(schema, "what is the capital of France?")
        assert result == {"user_question": "what is the capital of France?"}

    def test_bare_value_fills_single_param(self):
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"city": {"type": "string"}},
                                  "required": ["city"]}}
        result = self._fn()(schema, "Berlin")
        assert result == {"city": "Berlin"}

    def test_multi_required_strings_returns_empty(self):
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"text": {"type": "string"},
                                                 "target_language": {"type": "string"}},
                                  "required": ["text", "target_language"]}}
        result = self._fn()(schema, "hello world")
        assert result == {}

    def test_language_not_filled_with_nl_question(self):
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"language": {"type": "string"}},
                                  "required": ["language"]}}
        result = self._fn()(schema, "what language does Brazil speak")
        assert result == {}

    def test_currency_not_filled_with_nl_question(self):
        schema = {"inputSchema": {"type": "object",
                                  "properties": {"currency": {"type": "string"}},
                                  "required": ["currency"]}}
        result = self._fn()(schema, "what is the dollar worth")
        assert result == {}


# ---------------------------------------------------------------------------
# Fix D: auto() built-in guard
# ---------------------------------------------------------------------------

class TestAutoBuiltinGuard:
    @pytest.mark.asyncio
    async def test_onboard_redirects_to_direct_call(self):
        from kitsune_mcp.tools.onboarding import auto
        result = await auto("onboard")
        assert "built-in Kitsune tool" in result
        assert "onboard()" in result

    @pytest.mark.asyncio
    async def test_status_redirects_to_direct_call(self):
        from kitsune_mcp.tools.onboarding import auto
        result = await auto("status")
        assert "built-in Kitsune tool" in result

    @pytest.mark.asyncio
    async def test_search_redirects_to_direct_call(self):
        from kitsune_mcp.tools.onboarding import auto
        result = await auto("search")
        assert "built-in Kitsune tool" in result

    @pytest.mark.asyncio
    async def test_real_task_not_intercepted(self):
        # "time" is not a built-in name — should proceed to registry search
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[])
            from kitsune_mcp.tools.onboarding import auto
            result = await auto("time")
        assert "built-in" not in result


# ---------------------------------------------------------------------------
# Fix E: status() Smithery key liveness
# ---------------------------------------------------------------------------

class TestStatusSmitheryLiveness:
    @pytest.mark.asyncio
    async def test_valid_key_shows_verified(self, respx_mock, monkeypatch):
        import httpx
        import kitsune_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", "valid-key")
        monkeypatch.setenv("SMITHERY_API_KEY", "valid-key")
        respx_mock.get("https://registry.smithery.ai/servers").mock(
            return_value=httpx.Response(200, json={"servers": []})
        )
        from kitsune_mcp.tools.discovery import status
        result = await status()
        assert "verified" in result

    @pytest.mark.asyncio
    async def test_invalid_key_shows_invalid(self, respx_mock, monkeypatch):
        import httpx
        import kitsune_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", "bad-key")
        monkeypatch.setenv("SMITHERY_API_KEY", "bad-key")
        respx_mock.get("https://registry.smithery.ai/servers").mock(
            return_value=httpx.Response(401, text="Unauthorized")
        )
        from kitsune_mcp.tools.discovery import status
        result = await status()
        assert "INVALID" in result

    @pytest.mark.asyncio
    async def test_no_key_shows_onboard_hint(self, monkeypatch):
        import kitsune_mcp.credentials as creds
        monkeypatch.setattr(creds, "SMITHERY_API_KEY", None)
        monkeypatch.delenv("SMITHERY_API_KEY", raising=False)
        from kitsune_mcp.tools.discovery import status
        result = await status()
        assert "search(" in result or "auth(" in result or "no key" in result


# ---------------------------------------------------------------------------
# Fix E: _build_inference_hint — Issue #3 UX improvement
# Structured params that couldn't be inferred return a helpful retry message
# instead of letting the inner server emit an opaque validation error.
# ---------------------------------------------------------------------------

class TestBuildInferenceHint:
    def _make_schema(self, pname: str, ptype: str = "string", required: bool = True) -> dict:
        schema: dict = {
            "inputSchema": {
                "type": "object",
                "properties": {pname: {"type": ptype}},
                "required": [pname] if required else [],
            }
        }
        return schema

    def test_timezone_nl_task_returns_hint(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = self._make_schema("timezone")
        hint = _build_inference_hint(schema, "current time in Tokyo", "mcp-server-time", "get_current_time")
        assert hint is not None
        assert "timezone" in hint
        assert "mcp-server-time" in hint
        assert "arguments" in hint
        assert "Retry" in hint

    def test_hint_contains_example_value(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = self._make_schema("timezone")
        hint = _build_inference_hint(schema, "current time in Tokyo", "mcp-server-time", "get_current_time")
        assert "America/New_York" in hint  # canonical example from _PARAM_EXAMPLES

    def test_path_param_returns_hint(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = self._make_schema("path")
        hint = _build_inference_hint(schema, "web search for kitsune fox", "mcp-server-git", "search_files")
        assert hint is not None
        assert "path" in hint
        assert "filesystem path" in hint

    def test_no_required_params_returns_none(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = {"inputSchema": {"type": "object", "properties": {}, "required": []}}
        assert _build_inference_hint(schema, "get current time", "mcp-server-time", "get_current_time") is None

    def test_optional_only_params_returns_none(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = self._make_schema("timezone", required=False)
        assert _build_inference_hint(schema, "current time in Tokyo", "mcp-server-time", "get_current_time") is None

    def test_non_string_required_param_returns_none(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = self._make_schema("count", ptype="integer")
        assert _build_inference_hint(schema, "get 5 results", "some-server", "list_items") is None

    def test_multiple_required_strings_mentions_all(self):
        from kitsune_mcp.tools.onboarding import _build_inference_hint
        schema = {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "target_language": {"type": "string"},
                },
                "required": ["text", "target_language"],
            }
        }
        hint = _build_inference_hint(schema, "translate hello to Spanish", "mcp-translator", "translate")
        assert hint is not None
        assert "text" in hint
        assert "target_language" in hint
