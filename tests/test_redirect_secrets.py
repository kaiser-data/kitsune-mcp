"""Secrets and policy across redirects (review 2: Codex #7, #8, #9)."""

import sys

import httpx
import pytest

import kitsune_mcp.tools.shapeshift  # noqa: F401  (package re-exports a function of that name)
from kitsune_mcp import oauth, utils

ss = sys.modules["kitsune_mcp.tools.shapeshift"]


# --- #7: only known-safe headers cross origins; params are not replayed -----


async def test_cross_origin_redirect_drops_unknown_headers(respx_mock):
    respx_mock.get("https://api.example.com/x").mock(
        return_value=httpx.Response(307, headers={"Location": "https://other.example.net/y"})
    )
    hop = respx_mock.get("https://other.example.net/y").mock(return_value=httpx.Response(200))
    await utils._ssrf_safe_request(
        "GET",
        "https://api.example.com/x",
        headers={"X-API-Key": "SECRET", "Api-Token": "SECRET2", "Accept": "application/json"},
    )
    sent = hop.calls.last.request.headers
    assert "x-api-key" not in sent and "api-token" not in sent
    assert sent["accept"] == "application/json"


@pytest.mark.parametrize("target", ["https://other.example.net/y", "https://api.example.com/y"])
async def test_initial_params_are_not_sent_to_the_redirect_target(respx_mock, target):
    respx_mock.get("https://api.example.com/x").mock(
        return_value=httpx.Response(302, headers={"Location": target + "?page=2"})
    )
    hop = respx_mock.get(target).mock(return_value=httpx.Response(200))
    await utils._ssrf_safe_request(
        "GET", "https://api.example.com/x", params={"api_key": "SECRET", "q": "a"}
    )
    query = dict(hop.calls.last.request.url.params)
    assert query == {"page": "2"}


# --- #9: a crafted tool's redirect is checked against the guard -------------


async def test_crafted_tool_redirect_rechecked_by_guard(monkeypatch, respx_mock):
    checked = []

    async def _guard(server_id, tool, args):
        checked.append(args["url"])
        if "outside.example" in args["url"]:
            return "⛔ Blocked by Kitsune guard: host outside.example is not in network.allow"
        return None

    monkeypatch.setattr(ss, "guard_call", _guard)
    respx_mock.post("https://allowed.example/hook").mock(
        return_value=httpx.Response(307, headers={"Location": "https://outside.example/steal"})
    )
    outside = respx_mock.post("https://outside.example/steal").mock(
        return_value=httpx.Response(200)
    )
    proxy = ss._make_endpoint_proxy("hook", "https://allowed.example/hook", "POST", {}, {})
    result = await proxy(text="secret body")
    assert "Blocked" in result
    assert not outside.called
    assert checked == ["https://allowed.example/hook", "https://outside.example/steal"]


# --- #8: OAuth secrets are never POSTed to a redirect target ----------------


def _meta():
    return oauth.AuthMeta(
        issuer="https://auth.example",
        authorization_endpoint="https://auth.example/authorize",
        token_endpoint="https://auth.example/token",
        registration_endpoint="https://auth.example/register",
        code_challenge_methods_supported=["S256"],
        grant_types_supported=["authorization_code", "refresh_token"],
        token_endpoint_auth_methods_supported=["none"],
        revocation_endpoint="https://auth.example/revoke",
    )


async def test_refresh_does_not_follow_redirect(respx_mock):
    respx_mock.post("https://auth.example/token").mock(
        return_value=httpx.Response(307, headers={"Location": "https://evil.example/token"})
    )
    evil = respx_mock.post("https://evil.example/token").mock(
        return_value=httpx.Response(200, json={"access_token": "x"})
    )
    client = oauth.ClientInfo(
        client_id="cid", redirect_uri="http://127.0.0.1:1/cb", client_secret="CLIENT_SECRET"
    )
    bundle = oauth.TokenBundle(access_token="old", expires_at=0, refresh_token="REFRESH_TOKEN")
    with pytest.raises(Exception):  # noqa: B017  (any failure; the point is no hop)
        await oauth.refresh(_meta(), client, bundle)
    assert not evil.called


async def test_registration_does_not_follow_redirect(respx_mock):
    respx_mock.post("https://auth.example/register").mock(
        return_value=httpx.Response(308, headers={"Location": "https://evil.example/register"})
    )
    evil = respx_mock.post("https://evil.example/register").mock(
        return_value=httpx.Response(201, json={"client_id": "x"})
    )
    with pytest.raises(Exception):  # noqa: B017
        await oauth.register_client(_meta(), "https://srv.example", "http://127.0.0.1:1/cb")
    assert not evil.called
