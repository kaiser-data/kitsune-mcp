"""setup() gateway actions and auth() branches — the least-covered tool code.

Client configs, .env writes and the registry are all patched: no test touches
a real Claude config, ~/.kitsune, or the network.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kitsune_mcp import gateway
from kitsune_mcp.gateway import AbsorbedServer, ClientConfig
from kitsune_mcp.tools import _state, onboarding


def _configs():
    return [
        ClientConfig(
            client="claude-desktop",
            path=Path("/nonexistent/claude_desktop_config.json"),
            servers=[
                AbsorbedServer(id="kitsune", command="uvx"),
                AbsorbedServer(id="github", command="npx", env={"GITHUB_TOKEN": "ghp_secret"}),
                AbsorbedServer(id="fs", command="npx"),
            ],
        )
    ]


@pytest.fixture
def gw(monkeypatch):
    """Patch every gateway side effect; returns the mocks for assertions."""
    m = MagicMock()
    m.find.return_value = _configs()
    m.absorbed = []
    monkeypatch.setattr(gateway, "_find_mcp_configs", m.find)
    monkeypatch.setattr(gateway, "_load_absorbed_servers", lambda: list(m.absorbed))
    monkeypatch.setattr(gateway, "_save_absorbed_servers", m.save_absorbed)
    monkeypatch.setattr(gateway, "_write_exclusive_config", m.write_exclusive)
    monkeypatch.setattr(gateway, "_write_project_config", m.write_project)
    monkeypatch.setattr(gateway, "_restore_config", m.restore)
    monkeypatch.setattr(onboarding, "_save_to_env", m.save_env)
    m.save_env.return_value = True
    m.write_exclusive.return_value = Path("/backup/x.json")
    m.write_project.return_value = Path("/proj/.claude/mcp.json")
    monkeypatch.setattr(_state, "_registry", MagicMock())
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    return m


# ── setup() ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSetupGateway:
    async def test_wizard_previews_without_writing(self, gw):
        out = await onboarding.setup()
        assert "GATEWAY WIZARD" in out
        assert "github  [GITHUB_TOKEN]" in out
        assert "kitsune" not in out.split("GATEWAY WIZARD")[1].split("Next steps")[0]
        assert "ghp_secret" not in out
        gw.save_env.assert_not_called()
        gw.save_absorbed.assert_not_called()

    async def test_no_configs(self, gw):
        gw.find.return_value = []
        assert "No other MCP client configs found" in await onboarding.setup()

    async def test_harvest_saves_new_credentials_only(self, gw, monkeypatch):
        out = await onboarding.setup(action="harvest")
        gw.save_env.assert_called_once_with("GITHUB_TOKEN", "ghp_secret")
        assert "Harvested 1 new credential(s): GITHUB_TOKEN" in out

        gw.save_env.reset_mock()
        monkeypatch.setenv("GITHUB_TOKEN", "already-set")
        out = await onboarding.setup(action="harvest")
        gw.save_env.assert_not_called()
        assert "No new credentials" in out

    async def test_harvest_reports_failed_write(self, gw):
        gw.save_env.return_value = False
        out = await onboarding.setup(action="harvest")
        assert "Not written to .env (session only): GITHUB_TOKEN" in out

    async def test_absorb_registers_competing_servers(self, gw):
        out = await onboarding.setup(action="absorb")
        saved = gw.save_absorbed.call_args.args[0]
        assert {s.id for s in saved} == {"github", "fs"}
        assert all(s.absorbed_at for s in saved)
        assert "Absorbed 2 new server(s)" in out
        _state._registry.bust_cache.assert_called()

    async def test_absorb_skips_already_absorbed(self, gw):
        gw.absorbed = [
            AbsorbedServer(id="github", command="npx"),
            AbsorbedServer(id="fs", command="npx"),
        ]
        out = await onboarding.setup(action="absorb")
        gw.save_absorbed.assert_not_called()
        assert "No new servers" in out

    async def test_exclusive_needs_confirm(self, gw):
        out = await onboarding.setup(action="exclusive")
        assert "EXCLUSIVE MODE" in out and "confirm=True" in out
        gw.write_exclusive.assert_not_called()

    async def test_exclusive_confirmed_rewrites_with_keep(self, gw):
        out = await onboarding.setup(action="exclusive", confirm=True, keep=["fs"])
        gw.write_exclusive.assert_called_once_with("claude-desktop", ["fs"])
        assert "Exclusive mode applied" in out and "/backup/x.json" in out

    async def test_exclusive_reports_per_client_failure(self, gw):
        gw.write_exclusive.side_effect = PermissionError("read-only")
        out = await onboarding.setup(action="exclusive", confirm=True)
        assert "claude-desktop: failed (read-only)" in out

    async def test_restore(self, gw):
        gw.restore.return_value = True
        assert "Restored: claude-desktop" in await onboarding.setup(action="restore")
        gw.restore.return_value = False
        assert "No backups found" in await onboarding.setup(action="restore")
        gw.find.return_value = []
        assert "No client configs found" in await onboarding.setup(action="restore")

    async def test_project_config(self, gw):
        out = await onboarding.setup(project=True)
        assert "/proj/.claude/mcp.json" in out

    async def test_unknown_action(self, gw):
        assert "Unknown action 'nope'" in await onboarding.setup(action="nope")

    async def test_unknown_connection_name(self, gw, monkeypatch):
        monkeypatch.setitem(onboarding.session, "connections", {})
        assert "Use connect() first" in await onboarding.setup(name="dev")
        monkeypatch.setitem(onboarding.session, "connections", {"k": {"name": "other"}})
        assert "Connected: other" in await onboarding.setup(name="dev")


# ── auth() ───────────────────────────────────────────────────────────────────


def _srv(**kw):
    s = MagicMock()
    s.transport = kw.get("transport", "stdio")
    s.url = kw.get("url", "")
    s.credentials = kw.get("credentials", {})
    return s


@pytest.mark.asyncio
class TestAuth:
    async def test_server_id_with_value_is_rejected(self, gw):
        out = await onboarding.auth("@org/server", "abc")
        assert "looks like a server ID" in out
        gw.save_env.assert_not_called()

    async def test_logout_non_oauth_server(self, gw):
        _state._registry.get_server = AsyncMock(return_value=_srv())
        assert "not an OAuth server" in await onboarding.auth("my-server", "logout")

    async def test_logout_oauth_server(self, gw):
        _state._registry.get_server = AsyncMock(
            return_value=_srv(transport="http", url="https://x.example/mcp")
        )
        with patch("kitsune_mcp.oauth.logout", AsyncMock(return_value=(True, None))):
            out = await onboarding.auth("my-server", "logout")
        assert "OAuth tokens cleared" in out and "revoked at the identity provider" in out

    async def test_env_var_status(self, gw, monkeypatch):
        monkeypatch.delenv("NORMA_X_TOKEN", raising=False)
        assert "not set" in await onboarding.auth("NORMA_X_TOKEN")
        monkeypatch.setenv("NORMA_X_TOKEN", "abcdefghij")
        out = await onboarding.auth("NORMA_X_TOKEN")
        assert "(set)" in out and "abcdefghij" not in out

    async def test_unknown_server(self, gw):
        _state._registry.get_server = AsyncMock(return_value=None)
        assert "not found" in await onboarding.auth("ghost-server")

    async def test_stdio_no_credentials_needed(self, gw):
        _state._registry.get_server = AsyncMock(return_value=_srv())
        assert "no auth needed" in await onboarding.auth("time-server")

    async def test_stdio_missing_credentials_listed(self, gw, monkeypatch):
        _state._registry.get_server = AsyncMock(
            return_value=_srv(credentials={"apiKey": "Your API key"})
        )
        monkeypatch.setattr(
            _state, "_resolve_config", lambda c, x: ({}, {"apiKey": "Your API key"})
        )
        out = await onboarding.auth("svc")
        assert "needs credentials" in out and 'auth("API_KEY", "your-value")' in out

    async def test_http_without_url_is_blocked(self, gw):
        _state._registry.get_server = AsyncMock(return_value=_srv(transport="http"))
        assert "no URL configured" in await onboarding.auth("remote")

    async def test_http_no_oauth_metadata(self, gw):
        from kitsune_mcp import oauth

        _state._registry.get_server = AsyncMock(
            return_value=_srv(transport="http", url="https://x.example/mcp")
        )
        with patch.object(oauth, "ensure_token", AsyncMock(side_effect=oauth.NoAuthMetadata())):
            assert "no login is needed" in await onboarding.auth("remote")

    async def test_http_oauth_success_shows_only_token_prefix(self, gw):
        from kitsune_mcp import oauth

        _state._registry.get_server = AsyncMock(
            return_value=_srv(transport="http", url="https://x.example/mcp")
        )
        with patch.object(oauth, "ensure_token", AsyncMock(return_value="tok_1234567890abcdef")):
            out = await onboarding.auth("remote")
        assert "Authenticated 'remote'" in out
        assert "tok_1234..." in out and "abcdef" not in out
