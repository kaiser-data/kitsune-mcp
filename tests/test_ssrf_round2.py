"""SSRF and redirect gaps from the second Grok review (#6, #7, #8, #9, #10)."""

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from kitsune_mcp import oauth, utils
from kitsune_mcp.transport import HTTPSSETransport


async def _private(host):
    return ["10.0.0.5"]


async def _unresolvable(host):
    return []


# --- #7: a name that does not resolve is not treated as public ---------------


async def test_unresolvable_host_is_refused(monkeypatch, respx_mock):
    monkeypatch.setattr(utils, "_resolve_host", _unresolvable)
    route = respx_mock.get("https://rebind.example/").mock(return_value=httpx.Response(200))
    with pytest.raises(ValueError):
        await utils._ssrf_safe_request("GET", "https://rebind.example/")
    assert not route.called


# --- #10: multicast is not public ----------------------------------------------


@pytest.mark.parametrize("url", ["https://224.0.0.1/", "https://[ff02::1]/"])
def test_multicast_literal_is_not_safe(url):
    assert not utils._is_safe_url(url)


async def test_name_resolving_to_multicast_is_refused(monkeypatch, respx_mock):
    async def _multicast(host):
        return ["224.0.0.251"]

    monkeypatch.setattr(utils, "_resolve_host", _multicast)
    with pytest.raises(ValueError):
        await utils._ssrf_safe_request("GET", "https://mdns.example/")


# --- #8: a body is never replayed to another origin --------------------------


async def test_cross_origin_307_with_body_is_refused(respx_mock):
    respx_mock.post("https://api.example.com/hook").mock(
        return_value=httpx.Response(307, headers={"Location": "https://evil.example/collect"})
    )
    evil = respx_mock.post("https://evil.example/collect").mock(return_value=httpx.Response(200))
    with pytest.raises(ValueError):
        await utils._ssrf_safe_request(
            "POST", "https://api.example.com/hook", json_body={"secret": "body"}
        )
    assert not evil.called


async def test_same_origin_307_with_body_is_followed(respx_mock):
    respx_mock.post("https://api.example.com/hook").mock(
        return_value=httpx.Response(307, headers={"Location": "https://api.example.com/hook/"})
    )
    final = respx_mock.post("https://api.example.com/hook/").mock(return_value=httpx.Response(200))
    r = await utils._ssrf_safe_request("POST", "https://api.example.com/hook", json_body={"a": 1})
    assert r.status_code == 200 and json.loads(final.calls.last.request.content) == {"a": 1}


# --- #9: OAuth metadata hops resolve the hostname -------------------------------


async def test_oauth_metadata_hop_to_private_name_not_fetched(monkeypatch, respx_mock):
    resolved = {"meta.example": ["93.184.215.14"], "internal.example": ["10.0.0.5"]}

    async def _dns(host):
        return resolved.get(host, ["93.184.215.14"])

    monkeypatch.setattr(utils, "_resolve_host", _dns)
    respx_mock.get("https://meta.example/.well-known/x").mock(
        return_value=httpx.Response(302, headers={"Location": "https://internal.example/meta"})
    )
    internal = respx_mock.get("https://internal.example/meta").mock(
        return_value=httpx.Response(200, json={"issuer": "x"})
    )
    assert await oauth._get_json("https://meta.example/.well-known/x") is None
    assert not internal.called


async def test_oauth_hinted_url_resolving_private_is_not_followed(monkeypatch):
    monkeypatch.setattr(utils, "_resolve_host", _private)
    assert not await oauth._may_fetch("https://internal.example/meta", "https://srv.example/mcp")
    # The server's own origin stays allowed (a local dev server is fine).
    assert await oauth._may_fetch("https://srv.example/meta", "https://srv.example/mcp")


# --- #6: MCP HTTP requests follow same-origin redirects only ----------------


def _mcp_handler(redirect_to: str, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if str(request.url) == "https://srv.example/mcp":
            return httpx.Response(307, headers={"Location": redirect_to})
        body = json.loads(request.content or b"{}")
        method = body.get("method", "")
        if method == "initialize":
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "id": body["id"], "result": {}},
                headers={"mcp-session-id": "sid"},
            )
        if method.startswith("notifications/"):
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {"content": [{"type": "text", "text": "ok"}]},
            },
        )

    return handler


async def test_mcp_post_follows_same_origin_redirect(respx_mock):
    seen: list = []
    respx_mock.route(host="srv.example").mock(
        side_effect=_mcp_handler("https://srv.example/mcp/", seen)
    )
    t = HTTPSSETransport("https://srv.example/mcp")
    with patch.object(
        t, "_connect_endpoint", AsyncMock(return_value=("https://srv.example/mcp", ""))
    ):
        out = await t.execute("echo", {}, {})
    assert "ok" in out


async def test_mcp_post_does_not_follow_cross_origin_redirect(respx_mock):
    seen: list = []
    respx_mock.route(host="srv.example").mock(
        side_effect=_mcp_handler("https://evil.example/c", seen)
    )
    evil = respx_mock.route(host="evil.example").mock(return_value=httpx.Response(200, json={}))
    t = HTTPSSETransport("https://srv.example/mcp")
    with patch.object(
        t, "_connect_endpoint", AsyncMock(return_value=("https://srv.example/mcp", ""))
    ):
        await t.execute("echo", {"secret": "arg"}, {})
    assert not evil.called
