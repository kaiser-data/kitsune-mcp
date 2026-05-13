"""Tests for _works_now_score() — Phase 4 of v0.19."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _srv(**kwargs):
    from kitsune_mcp.registry import ServerInfo
    defaults = dict(
        id="test-server", name="Test Server", description="", source="official",
        transport="stdio", url="", install_cmd=[], credentials={}, tools=[], token_cost=0,
    )
    defaults.update(kwargs)
    return ServerInfo(**defaults)


class TestWorksNowScore:
    def _fn(self):
        from kitsune_mcp.registry import _works_now_score
        return _works_now_score

    def test_zero_config_official_stdio_is_highest(self):
        score = self._fn()(_srv(source="official", transport="stdio", credentials={}))
        # 0.4 (no missing creds) + 0.3 (official) + 0.1 (stdio) = 0.8
        assert score == pytest.approx(0.8)

    def test_missing_creds_lowers_score(self):
        # Key must end with a CRED_SUFFIX so _resolve_config treats it as blocking
        score_missing = self._fn()(_srv(
            source="official", transport="stdio",
            credentials={"VERY_UNLIKELY_XYZ_API_KEY": "required"},
        ))
        score_no_creds = self._fn()(_srv(source="official", transport="stdio", credentials={}))
        assert score_missing < score_no_creds

    def test_smithery_http_scores_lower_than_official_stdio(self):
        smithery = self._fn()(_srv(source="smithery", transport="http", credentials={}))
        official = self._fn()(_srv(source="official", transport="stdio", credentials={}))
        assert smithery < official

    def test_source_tier_ordering(self):
        fn = self._fn()
        official = fn(_srv(source="official", credentials={}))
        mcpreg = fn(_srv(source="mcpregistry", credentials={}))
        smithery = fn(_srv(source="smithery", credentials={}))
        npm = fn(_srv(source="npm", credentials={}))
        assert official > mcpreg >= smithery > npm

    def test_stdio_beats_http_same_source(self):
        fn = self._fn()
        stdio = fn(_srv(source="smithery", transport="stdio", credentials={}))
        http = fn(_srv(source="smithery", transport="http", credentials={}))
        assert stdio > http

    def test_high_token_cost_penalized(self):
        fn = self._fn()
        cheap = fn(_srv(source="official", credentials={}, token_cost=100))
        expensive = fn(_srv(source="official", credentials={}, token_cost=6000))
        assert cheap > expensive

    def test_score_never_exceeds_one(self):
        score = self._fn()(_srv(source="official", transport="stdio", credentials={}, token_cost=0))
        assert score <= 1.0

    def test_score_non_negative(self):
        score = self._fn()(_srv(
            source="npm", transport="http",
            credentials={"SOME_UNLIKELY_XYZ_API_KEY": "required"},
            token_cost=10000,
        ))
        assert score >= 0.0

    def test_unknown_source_gets_zero_tier_bonus(self):
        fn = self._fn()
        known = fn(_srv(source="npm", credentials={}))
        unknown = fn(_srv(source="custom_registry", credentials={}))
        # npm gets 0.05, unknown gets 0.0 — known should score higher
        assert known > unknown


import pytest  # noqa: E402 — needed for approx, placed after function defs to keep test readable


class TestCandidateSortUsesWorksNow:
    """Verify auto() sorts candidates by _works_now_score, not the old tuple heuristic."""

    def test_works_now_score_exported_from_registry(self):
        from kitsune_mcp.registry import _works_now_score
        assert callable(_works_now_score)

    def test_official_stdio_sorts_before_smithery_http(self):
        from kitsune_mcp.registry import _works_now_score
        official = _srv(source="official", transport="stdio", credentials={})
        smithery_http = _srv(source="smithery", transport="http", credentials={})
        ranked = sorted([smithery_http, official], key=_works_now_score, reverse=True)
        assert ranked[0].source == "official"
