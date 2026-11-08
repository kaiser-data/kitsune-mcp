"""MCP authorization: challenge-driven discovery, resource indicators, per-URL storage.

The metadata documents below copy the shapes real servers returned on
2026-11-08 (Notion, GitHub, Atlassian); see the PR for the probe.
"""

import asyncio
import json
import socket
import threading
import time
from unittest.mock import patch

import httpx
import pytest
import respx

from kitsune_mcp import oauth


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
    oauth._meta_cache.clear()
    oauth._force_login_origins.clear()
    yield
    oauth._meta_cache.clear()
    oauth._force_login_origins.clear()


def _as_doc(issuer: str, base: str | None = None, **extra) -> dict:
    base = base or issuer
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "code_challenge_methods_supported": ["S256"],
        **extra,
    }


NOTION = "https://mcp.notion.com/mcp"
NOTION_CHALLENGE = (
    'Bearer realm="OAuth", resource_metadata='
    '"https://mcp.notion.com/.well-known/oauth-protected-resource/mcp", scope="default"'
)


# ---------------------------------------------------------------------------
# WWW-Authenticate parsing
# ---------------------------------------------------------------------------


class TestParseChallenge:
    def test_real_headers(self):
        assert oauth.parse_challenge(NOTION_CHALLENGE) == {
            "realm": "OAuth",
            "resource_metadata": "https://mcp.notion.com/.well-known/oauth-protected-resource/mcp",
            "scope": "default",
        }
        gh = (
            'Bearer error="invalid_request", error_description="No access token was provided '
            'in this request", resource_metadata="https://api.githubcopilot.com/.well-known/'
            'oauth-protected-resource/mcp/"'
        )
        assert oauth.parse_challenge(gh)["error"] == "invalid_request"

    def test_unquoted_values_and_other_schemes(self):
        h = 'Basic realm="x", Bearer scope="a b", error=insufficient_scope, Basic realm="y"'
        assert oauth.parse_challenge(h) == {"scope": "a b", "error": "insufficient_scope"}

    def test_escapes_and_absent(self):
        assert oauth.parse_challenge('Bearer error_description="say \\"hi\\""') == {
            "error_description": 'say "hi"'
        }
        assert oauth.parse_challenge(None) == {}
        assert oauth.parse_challenge("Negotiate") == {}


# ---------------------------------------------------------------------------
# discover_target
# ---------------------------------------------------------------------------


class TestDiscoverTarget:
    async def test_follows_challenge_to_same_origin_server(self):
        prm = {
            "resource": NOTION,
            "authorization_servers": ["https://mcp.notion.com"],
            "scopes_supported": ["default"],
        }
        with respx.mock:
            respx.get("https://mcp.notion.com/.well-known/oauth-protected-resource/mcp").mock(
                return_value=httpx.Response(200, json=prm)
            )
            respx.get("https://mcp.notion.com/.well-known/oauth-authorization-server").mock(
                return_value=httpx.Response(200, json=_as_doc("https://mcp.notion.com"))
            )
            t = await oauth.discover_target(NOTION, NOTION_CHALLENGE)
        assert t.meta.issuer == "https://mcp.notion.com"
        assert t.resource == NOTION
        assert t.scope == "default"

    async def test_authorization_server_on_another_origin_with_path(self):
        """GitHub: resource on api.githubcopilot.com, issuer https://github.com/login/oauth."""
        url = "https://api.githubcopilot.com/mcp/"
        prm = {
            "resource": url,
            "authorization_servers": ["https://github.com/login/oauth"],
            "scopes_supported": ["repo", "read:org"],
        }
        challenge = (
            'Bearer resource_metadata="https://api.githubcopilot.com/.well-known/'
            'oauth-protected-resource/mcp/"'
        )
        with respx.mock:
            respx.get(
                "https://api.githubcopilot.com/.well-known/oauth-protected-resource/mcp/"
            ).mock(return_value=httpx.Response(200, json=prm))
            as_route = respx.get(
                "https://github.com/.well-known/oauth-authorization-server/login/oauth"
            ).mock(
                return_value=httpx.Response(
                    200, json=_as_doc("https://github.com/login/oauth", registration_endpoint=None)
                )
            )
            t = await oauth.discover_target(url, challenge)
        assert as_route.called
        assert t.meta.issuer == "https://github.com/login/oauth"
        assert t.meta.token_endpoint == "https://github.com/login/oauth/token"
        assert t.resource == url
        assert t.scope == "repo read:org"  # no scope in the challenge: the server's list

    async def test_well_known_fallback_without_challenge(self):
        url = "https://srv.example/v1/mcp"
        prm = {"resource": url, "authorization_servers": ["https://auth.example"]}
        with respx.mock:
            path_route = respx.get(
                "https://srv.example/.well-known/oauth-protected-resource/v1/mcp"
            ).mock(return_value=httpx.Response(404))
            respx.get("https://srv.example/.well-known/oauth-protected-resource").mock(
                return_value=httpx.Response(200, json=prm)
            )
            respx.get("https://auth.example/.well-known/oauth-authorization-server").mock(
                return_value=httpx.Response(404)
            )
            respx.get("https://auth.example/.well-known/openid-configuration").mock(
                return_value=httpx.Response(200, json=_as_doc("https://auth.example"))
            )
            t = await oauth.discover_target(url)
        assert path_route.called  # path-suffixed location tried first
        assert t.meta.issuer == "https://auth.example"

    async def test_server_without_resource_metadata_uses_its_origin(self):
        """Atlassian (2025-03-26 style): no RFC 9728 document."""
        url = "https://mcp.atlassian.com/v1/mcp"
        with respx.mock:
            respx.get(url__regex=r".*/oauth-protected-resource.*").mock(
                return_value=httpx.Response(404, text="Not Found")
            )
            respx.get("https://mcp.atlassian.com/.well-known/oauth-authorization-server").mock(
                return_value=httpx.Response(
                    200, json=_as_doc("https://mcp.atlassian.com", "https://mcp.atlassian.com/v1")
                )
            )
            t = await oauth.discover_target(url, 'Bearer realm="OAuth", error="invalid_token"')
        assert t.meta.token_endpoint == "https://mcp.atlassian.com/v1/token"
        assert t.resource == url

    async def test_no_metadata_at_all(self):
        with respx.mock:
            respx.get(url__regex=r"https://keyed\.example/.*").mock(
                return_value=httpx.Response(404)
            )
            with pytest.raises(oauth.NoAuthMetadata, match="API key"):
                await oauth.discover_target("https://keyed.example/mcp")

    async def test_metadata_for_another_resource_is_refused(self):
        prm = {"resource": "https://other.example/mcp", "authorization_servers": ["https://a.ex"]}
        with respx.mock:
            respx.get("https://srv.example/.well-known/oauth-protected-resource/mcp").mock(
                return_value=httpx.Response(200, json=prm)
            )
            with pytest.raises(RuntimeError, match="another resource"):
                await oauth.discover_target("https://srv.example/mcp")

    async def test_issuer_mismatch_is_refused(self):
        """RFC 8414 §3.3: metadata must name the issuer it was fetched for (mix-up defence)."""
        prm = {"resource": "https://srv.example/mcp", "authorization_servers": ["https://a.ex"]}
        with respx.mock:
            respx.get("https://srv.example/.well-known/oauth-protected-resource/mcp").mock(
                return_value=httpx.Response(200, json=prm)
            )
            respx.get(url__regex=r"https://a\.ex/.*").mock(
                return_value=httpx.Response(200, json=_as_doc("https://evil.example"))
            )
            with pytest.raises(RuntimeError, match="none publishes metadata"):
                await oauth.discover_target("https://srv.example/mcp")

    async def test_plain_http_endpoints_are_refused(self):
        prm = {"resource": "https://srv.example/mcp", "authorization_servers": ["https://a.ex"]}
        doc = _as_doc("https://a.ex")
        doc["token_endpoint"] = "http://a.ex/token"  # code + verifier in clear text
        with respx.mock:
            respx.get("https://srv.example/.well-known/oauth-protected-resource/mcp").mock(
                return_value=httpx.Response(200, json=prm)
            )
            respx.get(url__regex=r"https://a\.ex/.*").mock(
                return_value=httpx.Response(200, json=doc)
            )
            with pytest.raises(RuntimeError):
                await oauth.discover_target("https://srv.example/mcp")

    async def test_challenge_pointing_at_private_address_is_not_fetched(self):
        challenge = 'Bearer resource_metadata="http://169.254.169.254/latest/meta-data"'
        with respx.mock:
            metadata_ip = respx.get(url__regex=r"http://169\.254\.169\.254/.*").mock(
                return_value=httpx.Response(200, json={})
            )
            respx.get(url__regex=r"https://srv\.example/.*").mock(return_value=httpx.Response(404))
            with pytest.raises(oauth.NoAuthMetadata):
                await oauth.discover_target("https://srv.example/mcp", challenge)
        assert not metadata_ip.called


# ---------------------------------------------------------------------------
# Resource indicators (RFC 8707)
# ---------------------------------------------------------------------------


def _meta(issuer="https://a.ex") -> oauth.AuthMeta:
    return oauth.AuthMeta(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/authorize",
        token_endpoint=f"{issuer}/token",
        registration_endpoint=f"{issuer}/register",
        code_challenge_methods_supported=["S256"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none"],
    )


CLIENT = oauth.ClientInfo(client_id="cid", redirect_uri="http://127.0.0.1:1/cb")


class TestResourceIndicator:
    def test_authorization_url_carries_resource_and_scope(self):
        url = oauth._auth_url(
            _meta(), CLIENT, "chal", "st", resource="https://srv.example/mcp", scope="read write"
        )
        q = dict(httpx.URL(url).params)
        assert q["resource"] == "https://srv.example/mcp"
        assert q["scope"] == "read write"
        assert q["code_challenge_method"] == "S256"

    async def test_code_exchange_and_refresh_send_resource(self):
        token = {"access_token": "at", "refresh_token": "rt", "expires_in": 60}
        with respx.mock:
            route = respx.post("https://a.ex/token").mock(
                return_value=httpx.Response(200, json=token)
            )
            await oauth._exchange_code(_meta(), CLIENT, "code", "ver", resource="https://r/mcp")
            bundle = oauth.TokenBundle(access_token="x", expires_at=0, refresh_token="rt")
            await oauth.refresh(_meta(), CLIENT, bundle, resource="https://r/mcp")
        forms = [dict(httpx.QueryParams(c.request.content.decode())) for c in route.calls]
        assert [f["grant_type"] for f in forms] == ["authorization_code", "refresh_token"]
        assert all(f["resource"] == "https://r/mcp" for f in forms)


# ---------------------------------------------------------------------------
# Storage: one login per server URL
# ---------------------------------------------------------------------------


class TestStorage:
    def test_two_servers_on_one_host_do_not_share_a_login(self):
        a, b = "https://host.example/a/mcp", "https://host.example/b/mcp"
        assert oauth._store_key(a) != oauth._store_key(b)
        assert oauth._store_key("https://HOST.example/a/mcp/") == oauth._store_key(a)

    async def test_legacy_login_moves_once_and_logout_does_not_bring_it_back(self):
        url = "https://srv.example/mcp"
        legacy = oauth._origin(url)
        oauth.save_tokens(
            legacy, oauth.TokenBundle(access_token="old", expires_at=time.time() + 600)
        )
        assert await oauth.stored_token(url) == "old"
        assert oauth.load_tokens(legacy) is None
        oauth._meta_cache[url] = _meta("https://srv.example")
        await oauth.logout(url)
        assert await oauth.stored_token(url) == ""

    async def test_concurrent_callers_refresh_once(self):
        url = "https://srv.example/mcp"
        key = oauth._store_key(url)
        oauth._save_client(key, CLIENT)
        oauth.save_tokens(
            key, oauth.TokenBundle(access_token="old", expires_at=0, refresh_token="rt")
        )
        oauth._save_target(key, oauth.AuthTarget(url, url, _meta()))
        new = {"access_token": "new", "refresh_token": "rt2", "expires_in": 3600}
        with respx.mock:
            route = respx.post("https://a.ex/token").mock(
                return_value=httpx.Response(200, json=new)
            )
            tokens = await asyncio.gather(*(oauth.stored_token(url) for _ in range(5)))
        assert tokens == ["new"] * 5
        assert route.call_count == 1  # a rotated refresh token would break a second refresh
        assert dict(httpx.QueryParams(route.calls[0].request.content.decode()))["resource"] == url


# ---------------------------------------------------------------------------
# authenticate()
# ---------------------------------------------------------------------------


class TestAuthenticate:
    async def test_reuses_a_login_another_caller_just_made(self):
        url = "https://srv.example/mcp"
        key = oauth._store_key(url)
        oauth.save_tokens(
            key, oauth.TokenBundle(access_token="theirs", expires_at=time.time() + 600)
        )
        assert await oauth.authenticate(url, rejected="mine") == "theirs"

    async def test_insufficient_scope_skips_refresh(self):
        url = "https://srv.example/mcp"
        key = oauth._store_key(url)
        oauth._save_client(
            key, oauth.ClientInfo("cid", "http://127.0.0.1:1/cb", issuer="https://a.ex")
        )
        oauth.save_tokens(
            key,
            oauth.TokenBundle(access_token="t", expires_at=time.time() + 600, refresh_token="rt"),
        )
        target = oauth.AuthTarget(url, url, _meta(), "admin")
        seen = {}

        async def fake_authorize(meta, client, force_login=False, **kw):
            seen.update(kw)
            return oauth.TokenBundle(access_token="bigger", expires_at=time.time() + 600)

        async def no_refresh(*_a, **_kw):
            raise AssertionError("refresh cannot add scope")

        with (
            patch.object(oauth, "discover_target", return_value=target),
            patch.object(oauth, "refresh", side_effect=no_refresh),
            patch.object(oauth, "authorize", side_effect=fake_authorize),
        ):
            tok = await oauth.authenticate(
                url, 'Bearer error="insufficient_scope", scope="admin"', rejected="t"
            )
        assert tok == "bigger"
        assert seen == {"resource": url, "scope": "admin"}

    async def test_client_registered_with_another_issuer_is_replaced(self):
        url = "https://srv.example/mcp"
        key = oauth._store_key(url)
        oauth._save_client(
            key, oauth.ClientInfo("old-cid", "http://127.0.0.1:1/cb", issuer="https://gone.ex")
        )
        target = oauth.AuthTarget(url, url, _meta())
        clients = []

        async def fake_authorize(meta, client, force_login=False, **kw):
            clients.append(client.client_id)
            return oauth.TokenBundle(access_token="t", expires_at=time.time() + 600)

        with (
            patch.object(oauth, "discover_target", return_value=target),
            patch.object(oauth, "authorize", side_effect=fake_authorize),
            respx.mock,
        ):
            respx.post("https://a.ex/register").mock(
                return_value=httpx.Response(201, json={"client_id": "new-cid"})
            )
            await oauth.authenticate(url)
        assert clients == ["new-cid"]
        assert oauth._load_client(key).issuer == "https://a.ex"


# ---------------------------------------------------------------------------
# End to end: a real mcp SDK server with auth enabled
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app, port):
    uvicorn = pytest.importorskip("uvicorn")
    srv = uvicorn.Server(uvicorn.Config(app, port=port, log_level="error"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            pytest.fail("server did not start")
        time.sleep(0.02)
    return srv, thread


async def test_sdk_server_challenge_drives_login(monkeypatch):
    """SDK resource server (401 + RFC 9728) → separate authorization server → retry with token."""
    fastmcp = pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.auth.provider import AccessToken
    from mcp.server.auth.settings import AuthSettings
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    import kitsune_mcp.transport as tp
    import kitsune_mcp.utils as utils

    rs_port, as_port = _free_port(), _free_port()
    rs_url, as_url = f"http://127.0.0.1:{rs_port}/mcp", f"http://127.0.0.1:{as_port}"

    class Verifier:
        async def verify_token(self, token):
            if token == "good":
                return AccessToken(token=token, client_id="cid", scopes=["read"], resource=rs_url)
            return None

    mcp = fastmcp.FastMCP(
        "guarded",
        port=rs_port,
        token_verifier=Verifier(),
        auth=AuthSettings(issuer_url=as_url, resource_server_url=rs_url, required_scopes=["read"]),
    )

    @mcp.tool()
    def whoami() -> str:
        return "authorized"

    registered = []

    async def as_metadata(_req):
        return JSONResponse(_as_doc(as_url))

    async def register(req):
        registered.append(json.loads(await req.body()))
        return JSONResponse({"client_id": "dcr-client"}, status_code=201)

    auth_server = Starlette(
        routes=[
            Route("/.well-known/oauth-authorization-server", as_metadata),
            Route("/register", register, methods=["POST"]),
        ]
    )

    seen = {}

    async def fake_browser_login(meta, client, force_login=False, **kw):
        seen.update(issuer=meta.issuer, client=client.client_id, **kw)
        return oauth.TokenBundle(access_token="good", expires_at=time.time() + 600)

    monkeypatch.setattr(oauth, "authorize", fake_browser_login)
    utils._http_client = None
    rs, rs_thread = _serve(mcp.streamable_http_app(), rs_port)
    asrv, as_thread = _serve(auth_server, as_port)
    try:
        t = tp.HTTPSSETransport(rs_url, direct=True)
        assert await t.execute("whoami", {}, {}) == "authorized"
        assert await t.execute("whoami", {}, {}) == "authorized"  # stored token, no new login
    finally:
        await tp.close_http_sessions()
        if utils._http_client is not None:
            await utils._http_client.aclose()
        utils._http_client = None
        rs.should_exit = asrv.should_exit = True
        rs_thread.join(timeout=10)
        as_thread.join(timeout=10)
    assert seen["issuer"] == as_url
    assert seen["client"] == "dcr-client"
    assert seen["resource"] == rs_url
    assert seen["scope"] == "read"
    assert len(registered) == 1
