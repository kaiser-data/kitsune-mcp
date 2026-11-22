"""HTTP hardening: redirect credential stripping, SSRF hostname checks, OAuth redirects.

Findings from the 2026-11-22 external review (Codex): #6, #7, #8, #9.
"""

import httpx
import pytest

from kitsune_mcp import oauth, utils

# --- #9: credentials must not follow a redirect to another origin ------------


async def test_cross_origin_redirect_drops_credentials(respx_mock):
    respx_mock.get("https://api.example.com/x").mock(
        return_value=httpx.Response(302, headers={"Location": "https://other.example.net/y"})
    )
    hop = respx_mock.get("https://other.example.net/y").mock(return_value=httpx.Response(200))

    await utils._ssrf_safe_request(
        "GET",
        "https://api.example.com/x",
        headers={"Authorization": "Bearer SECRET", "Cookie": "s=1", "X-Trace": "keep"},
    )

    sent = hop.calls.last.request.headers
    assert "authorization" not in sent
    assert "cookie" not in sent
    # Unknown headers may hold secrets too (X-API-Key): only a safe list crosses.
    assert "x-trace" not in sent


async def test_same_origin_redirect_keeps_credentials(respx_mock):
    respx_mock.get("https://api.example.com/x").mock(
        return_value=httpx.Response(302, headers={"Location": "https://api.example.com/y"})
    )
    hop = respx_mock.get("https://api.example.com/y").mock(return_value=httpx.Response(200))

    await utils._ssrf_safe_request(
        "GET", "https://api.example.com/x", headers={"Authorization": "Bearer SECRET"}
    )

    assert hop.calls.last.request.headers["authorization"] == "Bearer SECRET"


# --- #6: private destinations spelled as hostnames ---------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost./",
        "https://LOCALHOST/",
        "https://app.localhost/",
        "https://127.1/",
        "https://2130706433/",
        "https://0x7f.0.0.1/",
    ],
)
def test_is_safe_url_blocks_alternate_loopback_spellings(url):
    assert not utils._is_safe_url(url)


async def test_request_blocked_when_hostname_resolves_private(monkeypatch, respx_mock):
    async def _private(host):
        return ["10.0.0.5"]

    monkeypatch.setattr(utils, "_resolve_host", _private)
    route = respx_mock.get("https://internal.corp.example/admin").mock(
        return_value=httpx.Response(200)
    )

    with pytest.raises(ValueError, match="private"):
        await utils._ssrf_safe_request("GET", "https://internal.corp.example/admin")
    assert not route.called


async def test_request_allowed_when_local_fetch_enabled(monkeypatch, respx_mock):
    async def _private(host):
        return ["10.0.0.5"]

    monkeypatch.setattr(utils, "_resolve_host", _private)
    monkeypatch.setenv("KITSUNE_ALLOW_LOCAL_FETCH", "1")
    respx_mock.get("https://internal.corp.example/").mock(return_value=httpx.Response(200))

    r = await utils._ssrf_safe_request("GET", "https://internal.corp.example/")
    assert r.status_code == 200


# --- #7: OAuth metadata redirects must stay within what we may fetch ---------


async def test_oauth_metadata_redirect_to_private_address_not_followed(respx_mock):
    respx_mock.get("https://mcp.example.com/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1:8080/internal"})
    )
    internal = respx_mock.get("http://127.0.0.1:8080/internal").mock(
        return_value=httpx.Response(200, json={"issuer": "x"})
    )

    assert await oauth.discover("https://mcp.example.com/mcp") is None
    assert not internal.called


# --- #8: legacy discovery must reject plaintext endpoints ---------------------


async def test_legacy_discovery_rejects_plaintext_token_endpoint(respx_mock):
    oauth._meta_cache.clear()
    respx_mock.get("https://legacy.example.com/.well-known/oauth-protected-resource/mcp").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://legacy.example.com/.well-known/oauth-protected-resource").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://legacy.example.com/.well-known/oauth-authorization-server").mock(
        return_value=httpx.Response(
            200,
            json={
                "issuer": "https://legacy.example.com",
                "authorization_endpoint": "https://legacy.example.com/authorize",
                "token_endpoint": "http://legacy.example.com/token",
            },
        )
    )

    with pytest.raises(RuntimeError, match="secure"):
        await oauth.discover_target("https://legacy.example.com/mcp")


async def test_fetch_blocks_internal_hostname_before_any_fetcher(monkeypatch):
    # fetch() may hand the URL to an external fetcher (axonmcp) before the
    # httpx fallback, so the DNS check must run before either.
    from kitsune_mcp.tools import exec as exec_tools

    async def _private(host):
        return ["10.1.2.3"]

    async def _axon(url, intent):
        raise AssertionError("external fetcher must not be reached")

    monkeypatch.setattr(utils, "_resolve_host", _private)
    monkeypatch.setattr(exec_tools, "_try_axonmcp", _axon)

    result = await exec_tools.fetch("https://wiki.corp.example/page")
    assert result.startswith("Blocked")


async def test_first_url_is_checked_not_only_redirects(respx_mock):
    # Crafted tools restored from state.json call _ssrf_safe_request directly,
    # without craft()'s up-front _is_safe_url check.
    route = respx_mock.get("http://169.254.169.254/latest/meta-data/").mock(
        return_value=httpx.Response(200)
    )
    with pytest.raises(ValueError, match="private"):
        await utils._ssrf_safe_request("GET", "http://169.254.169.254/latest/meta-data/")
    assert not route.called
