"""Tests for kitsune_mcp.oauth — OAuth 2.1 + DCR + PKCE client.

Covers deterministic pieces (no live browser):
- PKCE verifier/challenge generation (S256 round-trip)
- State CSRF token generation
- Origin sanitization and path helpers
- Discovery parsing (well-known metadata)
- Dynamic Client Registration payload
- Token file round-trip + 0600 permissions
- Refresh on expiry
- invalid_grant → re-auth flow
- _bundle_from_response parsing
"""
import asyncio
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kitsune_mcp import oauth


# ---------------------------------------------------------------------------
# PKCE + state
# ---------------------------------------------------------------------------


class TestPKCE:
    def test_pkce_pair_returns_verifier_and_challenge(self):
        verifier, challenge = oauth._pkce_pair()
        assert verifier and challenge
        assert verifier != challenge

    def test_pkce_challenge_is_s256_of_verifier(self):
        verifier, challenge = oauth._pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()
        ).rstrip(b"=").decode()
        assert challenge == expected

    def test_pkce_no_padding_in_challenge(self):
        for _ in range(20):
            _, challenge = oauth._pkce_pair()
            assert "=" not in challenge

    def test_verifier_entropy_is_sufficient(self):
        seen = {oauth._pkce_pair()[0] for _ in range(50)}
        assert len(seen) == 50

    def test_make_state_is_url_safe_and_unique(self):
        states = {oauth._make_state() for _ in range(30)}
        assert len(states) == 30
        for s in states:
            # token_urlsafe → only [-_A-Za-z0-9]
            assert all(c.isalnum() or c in "-_" for c in s)


# ---------------------------------------------------------------------------
# Origin + paths
# ---------------------------------------------------------------------------


class TestOriginAndPaths:
    def test_origin_extracts_netloc(self):
        assert oauth._origin("https://mcp.notion.com/mcp") == "mcp.notion.com"

    def test_origin_sanitizes_port(self):
        assert oauth._origin("http://localhost:8080/mcp") == "localhost_8080"

    def test_origin_no_path_traversal(self):
        o = oauth._origin("https://../../etc/passwd")
        assert "/" not in o and "\\" not in o

    def test_paths_scoped_under_kitsune_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        base, client, tokens = oauth._paths("example.com")
        assert base == tmp_path / "oauth" / "example.com"
        assert client.name == "client.json"
        assert tokens.name == "tokens.json"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_discover_parses_full_metadata(self):
        fake_resp = MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "issuer": "https://mcp.notion.com",
            "authorization_endpoint": "https://mcp.notion.com/authorize",
            "token_endpoint": "https://mcp.notion.com/token",
            "registration_endpoint": "https://mcp.notion.com/register",
            "code_challenge_methods_supported": ["S256", "plain"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value=fake_resp)
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            meta = asyncio.run(oauth.discover("https://mcp.notion.com/mcp"))
        assert meta is not None
        assert meta.issuer == "https://mcp.notion.com"
        assert meta.token_endpoint == "https://mcp.notion.com/token"
        assert "S256" in meta.code_challenge_methods_supported
        fake_client.get.assert_awaited_once()
        called_url = fake_client.get.call_args[0][0]
        assert called_url == "https://mcp.notion.com/.well-known/oauth-authorization-server"

    def test_discover_returns_none_on_404(self):
        fake_resp = MagicMock(status_code=404)
        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value=fake_resp)
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            meta = asyncio.run(oauth.discover("https://example.com"))
        assert meta is None

    def test_discover_returns_none_on_missing_fields(self):
        fake_resp = MagicMock(status_code=200)
        fake_resp.json.return_value = {"issuer": "https://x"}  # missing endpoints
        fake_client = MagicMock()
        fake_client.get = AsyncMock(return_value=fake_resp)
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            meta = asyncio.run(oauth.discover("https://x"))
        assert meta is None

    def test_discover_returns_none_on_network_error(self):
        fake_client = MagicMock()
        fake_client.get = AsyncMock(side_effect=Exception("boom"))
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            meta = asyncio.run(oauth.discover("https://x"))
        assert meta is None


# ---------------------------------------------------------------------------
# Dynamic Client Registration
# ---------------------------------------------------------------------------


class TestRegisterClient:
    def _meta(self, **overrides):
        base = dict(
            issuer="https://mcp.notion.com",
            authorization_endpoint="https://mcp.notion.com/authorize",
            token_endpoint="https://mcp.notion.com/token",
            registration_endpoint="https://mcp.notion.com/register",
            code_challenge_methods_supported=["S256"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none"],
        )
        base.update(overrides)
        return oauth.AuthMeta(**base)

    def test_registration_uses_none_auth_method_when_supported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"client_id": "cid-123"}
        fake_client = MagicMock()
        fake_client.post = AsyncMock(return_value=fake_resp)
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            client = asyncio.run(
                oauth.register_client(
                    self._meta(),
                    "mcp.notion.com",
                    "http://127.0.0.1:5555/callback",
                )
            )
        body = fake_client.post.call_args.kwargs["json"]
        assert body["token_endpoint_auth_method"] == "none"
        assert body["client_name"] == oauth._CLIENT_NAME
        assert body["redirect_uris"] == ["http://127.0.0.1:5555/callback"]
        assert body["grant_types"] == ["authorization_code", "refresh_token"]
        assert body["response_types"] == ["code"]
        assert client.client_id == "cid-123"
        assert client.client_secret is None

    def test_registration_persists_client_info(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        fake_resp = MagicMock()
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"client_id": "cid-xyz", "client_secret": "shh"}
        fake_client = MagicMock()
        fake_client.post = AsyncMock(return_value=fake_resp)
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            asyncio.run(
                oauth.register_client(
                    self._meta(token_endpoint_auth_methods_supported=["client_secret_basic"]),
                    "mcp.notion.com",
                    "http://127.0.0.1:5555/callback",
                )
            )
        loaded = oauth._load_client("mcp.notion.com")
        assert loaded is not None
        assert loaded.client_id == "cid-xyz"
        assert loaded.client_secret == "shh"

    def test_registration_raises_without_endpoint(self):
        meta = self._meta(registration_endpoint=None)
        with pytest.raises(RuntimeError, match="Dynamic Client Registration"):
            asyncio.run(oauth.register_client(meta, "x.com", "http://127.0.0.1:1/cb"))


# ---------------------------------------------------------------------------
# Token storage (round-trip + 0600)
# ---------------------------------------------------------------------------


class TestTokenStorage:
    def test_roundtrip_tokens(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        bundle = oauth.TokenBundle(
            access_token="at-1",
            expires_at=123456.0,
            refresh_token="rt-1",
            scope="read",
        )
        oauth.save_tokens("example.com", bundle)
        loaded = oauth.load_tokens("example.com")
        assert loaded == bundle

    def test_tokens_written_with_0600(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        bundle = oauth.TokenBundle(access_token="x", expires_at=0)
        oauth.save_tokens("example.com", bundle)
        _, _, tok_path = oauth._paths("example.com")
        mode = stat.S_IMODE(tok_path.stat().st_mode)
        assert mode == 0o600

    def test_load_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        assert oauth.load_tokens("nowhere.invalid") is None

    def test_delete_tokens_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        oauth.delete_tokens("never-existed.example")  # no raise
        oauth.save_tokens("x", oauth.TokenBundle(access_token="a", expires_at=0))
        oauth.delete_tokens("x")
        assert oauth.load_tokens("x") is None


# ---------------------------------------------------------------------------
# _bundle_from_response
# ---------------------------------------------------------------------------


class TestBundleFromResponse:
    def test_parses_full_payload(self):
        import time
        before = time.time()
        b = oauth._bundle_from_response({
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "token_type": "Bearer",
            "scope": "read write",
        })
        after = time.time()
        assert b.access_token == "at"
        assert b.refresh_token == "rt"
        assert b.scope == "read write"
        assert before + 3599 <= b.expires_at <= after + 3601

    def test_defaults_expires_in_when_missing(self):
        b = oauth._bundle_from_response({"access_token": "at"})
        assert b.refresh_token is None
        # default 3600
        import time
        assert b.expires_at - time.time() > 3500


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def _client(self):
        return oauth.ClientInfo(client_id="cid", redirect_uri="http://127.0.0.1:1/cb")

    def _meta(self):
        return oauth.AuthMeta(
            issuer="https://x",
            authorization_endpoint="https://x/a",
            token_endpoint="https://x/t",
            registration_endpoint="https://x/r",
            code_challenge_methods_supported=["S256"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none"],
        )

    def test_refresh_sends_refresh_grant(self):
        fake_resp = MagicMock(status_code=200)
        fake_resp.raise_for_status = MagicMock()
        fake_resp.json.return_value = {"access_token": "new", "expires_in": 60}
        fake_client = MagicMock()
        fake_client.post = AsyncMock(return_value=fake_resp)
        old = oauth.TokenBundle(access_token="old", expires_at=0, refresh_token="rt")
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            new = asyncio.run(oauth.refresh(self._meta(), self._client(), old))
        sent = fake_client.post.call_args.kwargs["data"]
        assert sent["grant_type"] == "refresh_token"
        assert sent["refresh_token"] == "rt"
        assert sent["client_id"] == "cid"
        assert new.access_token == "new"
        # Old refresh token preserved when server doesn't rotate.
        assert new.refresh_token == "rt"

    def test_refresh_raises_without_refresh_token(self):
        old = oauth.TokenBundle(access_token="old", expires_at=0, refresh_token=None)
        with pytest.raises(RuntimeError):
            asyncio.run(oauth.refresh(self._meta(), self._client(), old))

    def test_refresh_invalid_grant_raises_permission_error(self):
        fake_resp = MagicMock(status_code=400)
        fake_resp.json.return_value = {"error": "invalid_grant"}
        fake_resp.raise_for_status = MagicMock(side_effect=Exception("should not reach"))
        fake_client = MagicMock()
        fake_client.post = AsyncMock(return_value=fake_resp)
        old = oauth.TokenBundle(access_token="old", expires_at=0, refresh_token="rt")
        with patch.object(oauth, "_get_http_client", return_value=fake_client):
            with pytest.raises(PermissionError):
                asyncio.run(oauth.refresh(self._meta(), self._client(), old))


# ---------------------------------------------------------------------------
# ensure_token — orchestration
# ---------------------------------------------------------------------------


class TestEnsureToken:
    def test_ensure_token_returns_cached_when_valid(self, tmp_path, monkeypatch):
        import time
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        meta = oauth.AuthMeta(
            issuer="https://x",
            authorization_endpoint="https://x/a",
            token_endpoint="https://x/t",
            registration_endpoint="https://x/r",
            code_challenge_methods_supported=["S256"],
            grant_types_supported=["authorization_code"],
            token_endpoint_auth_methods_supported=["none"],
        )
        # Pre-seed metadata cache so discover isn't called.
        oauth._meta_cache["https://x/mcp"] = meta
        origin = oauth._origin("https://x/mcp")
        oauth.save_tokens(origin, oauth.TokenBundle(
            access_token="cached", expires_at=time.time() + 600,
        ))
        token = asyncio.run(oauth.ensure_token("https://x/mcp"))
        assert token == "cached"
        # Clean up shared cache.
        oauth._meta_cache.pop("https://x/mcp", None)

    def test_ensure_token_refreshes_when_expired(self, tmp_path, monkeypatch):
        import time
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        meta = oauth.AuthMeta(
            issuer="https://y",
            authorization_endpoint="https://y/a",
            token_endpoint="https://y/t",
            registration_endpoint="https://y/r",
            code_challenge_methods_supported=["S256"],
            grant_types_supported=["refresh_token"],
            token_endpoint_auth_methods_supported=["none"],
        )
        oauth._meta_cache["https://y/mcp"] = meta
        origin = oauth._origin("https://y/mcp")
        oauth._save_client(origin, oauth.ClientInfo(
            client_id="cid", redirect_uri="http://127.0.0.1:5/cb",
        ))
        oauth.save_tokens(origin, oauth.TokenBundle(
            access_token="old", expires_at=time.time() - 10, refresh_token="rt",
        ))

        async def fake_refresh(_m, _c, _b):
            return oauth.TokenBundle(access_token="new-access", expires_at=time.time() + 3600)

        with patch.object(oauth, "refresh", side_effect=fake_refresh):
            token = asyncio.run(oauth.ensure_token("https://y/mcp"))
        assert token == "new-access"
        assert oauth.load_tokens(origin).access_token == "new-access"
        oauth._meta_cache.pop("https://y/mcp", None)

    def test_ensure_token_reauthorizes_on_invalid_grant(self, tmp_path, monkeypatch):
        import time
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        meta = oauth.AuthMeta(
            issuer="https://z",
            authorization_endpoint="https://z/a",
            token_endpoint="https://z/t",
            registration_endpoint="https://z/r",
            code_challenge_methods_supported=["S256"],
            grant_types_supported=["authorization_code", "refresh_token"],
            token_endpoint_auth_methods_supported=["none"],
        )
        oauth._meta_cache["https://z/mcp"] = meta
        origin = oauth._origin("https://z/mcp")
        oauth._save_client(origin, oauth.ClientInfo(
            client_id="cid", redirect_uri="http://127.0.0.1:5/cb",
        ))
        oauth.save_tokens(origin, oauth.TokenBundle(
            access_token="old", expires_at=time.time() - 10, refresh_token="rt-bad",
        ))

        async def bad_refresh(*_a, **_kw):
            raise PermissionError("invalid_grant")

        async def fake_authorize(_m, _c):
            return oauth.TokenBundle(access_token="fresh", expires_at=time.time() + 3600)

        with patch.object(oauth, "refresh", side_effect=bad_refresh), \
             patch.object(oauth, "authorize", side_effect=fake_authorize):
            token = asyncio.run(oauth.ensure_token("https://z/mcp"))
        assert token == "fresh"
        oauth._meta_cache.pop("https://z/mcp", None)

    def test_ensure_token_fails_without_well_known(self, tmp_path, monkeypatch):
        monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
        oauth._meta_cache.pop("https://nope/mcp", None)

        async def no_meta(_u):
            return None

        with patch.object(oauth, "discover", side_effect=no_meta):
            with pytest.raises(RuntimeError, match="well-known"):
                asyncio.run(oauth.ensure_token("https://nope/mcp"))
