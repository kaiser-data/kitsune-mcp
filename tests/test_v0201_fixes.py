"""Tests for v0.20.1 — auth() server-ID guard and auto() composite ranking."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestAuthServerIdGuard:
    """auth() must not write server IDs as env var names."""

    async def _call(self, name, value=""):
        from kitsune_mcp.tools.onboarding import auth
        return await auth(name, value)

    async def test_server_id_with_value_returns_error(self):
        result = await self._call("notion-hosted", "sk-abc")
        assert "looks like a server ID" in result
        assert "NOTION_HOSTED" not in result or "Saved" not in result

    async def test_server_id_with_value_does_not_write_env(self):
        original = os.environ.get("NOTION_HOSTED")
        await self._call("notion-hosted", "some-garbage")
        assert os.environ.get("NOTION_HOSTED") == original

    async def test_server_id_logout_does_not_write_env(self):
        original = os.environ.get("NOTION_HOSTED")
        result = await self._call("notion-hosted", "logout")
        assert os.environ.get("NOTION_HOSTED") == original
        # Response should NOT say "Saved"
        assert "Saved" not in result

    async def test_plain_env_var_all_caps_still_saves(self, tmp_path, monkeypatch):
        from unittest.mock import patch
        with patch("kitsune_mcp.credentials._KITSUNE_HOME", tmp_path):
            (tmp_path / ".env").touch()
            result = await self._call("MY_API_KEY", "test-value")
        assert "Saved" in result or "MY_API_KEY" in result

    def test_env_var_no_hyphen_passes_guard(self):
        import re
        # The guard fires on re.search(r'[-/@]', name)
        assert not re.search(r'[-/@]', "BRAVE_API_KEY")
        assert not re.search(r'[-/@]', "MY_TOKEN")
        assert re.search(r'[-/@]', "notion-hosted")
        assert re.search(r'[-/@]', "@scope/server")


class TestAutoCompositeRank:
    """Composite rank = _relevance_score × 10 + _works_now_score."""

    def _score(self, srv, query):
        from kitsune_mcp.registry import _relevance_score, _works_now_score
        return _relevance_score(srv, query) * 10.0 + _works_now_score(srv)

    def _srv(self, **kwargs):
        from kitsune_mcp.registry import ServerInfo
        defaults = dict(
            id="test", name="Test", description="",
            source="official", transport="stdio",
            credentials={}, tools=[], token_cost=0, url="", install_cmd=[],
        )
        defaults.update(kwargs)
        return ServerInfo(**defaults)

    def test_relevant_beats_merely_operable(self):
        # High-relevance server with creds needed
        relevant = self._srv(
            id="brave-search", name="Brave Web Search",
            description="search the web",
            source="smithery", credentials={"BRAVE_API_KEY": "required"},
        )
        # High-operability server with unrelated purpose
        operable = self._srv(
            id="simulate-research", name="Simulate Research Query",
            description="simulation tasks",
            source="official", credentials={},
        )
        assert self._score(relevant, "search the web") > self._score(operable, "search the web")

    def test_works_now_breaks_ties_among_equally_relevant(self):
        # Same name/description, different operability
        no_creds = self._srv(name="Time Server", description="time queries", credentials={})
        with_creds = self._srv(
            name="Time Server", description="time queries",
            credentials={"TIME_KEY": "required"},
        )
        assert self._score(no_creds, "time") > self._score(with_creds, "time")

    def test_exact_name_match_dominates(self):
        exact = self._srv(id="exa", name="exa", description="web search")
        partial = self._srv(id="exa-2", name="exa web search extended", description="searches")
        # Both relevant to "exa" but exact match should win
        assert self._score(exact, "exa") > self._score(partial, "exa")
