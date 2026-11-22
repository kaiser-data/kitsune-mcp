"""The address that passed the SSRF check is the address we connect to (review 2: Codex #10, Grok #7).

These tests do not use respx: respx replaces the connection layer that this
fix lives in.
"""

from unittest.mock import AsyncMock, MagicMock

import httpcore
import pytest

from kitsune_mcp import utils


def _dns(*answers):
    """Successive _resolve_host answers: a rebinding resolver."""
    seq = list(answers)

    async def resolve(host):
        return seq.pop(0) if len(seq) > 1 else seq[0]

    return resolve


def _backend():
    inner = MagicMock()
    inner.connect_tcp = AsyncMock(return_value="stream")
    return utils._PublicOnlyBackend(inner), inner


async def test_connect_goes_to_the_checked_public_address(monkeypatch):
    monkeypatch.setattr(utils, "_resolve_host", _dns(["93.184.215.14"]))
    backend, inner = _backend()
    assert await backend.connect_tcp("example.com", 443) == "stream"
    assert inner.connect_tcp.await_args.args[:2] == ("93.184.215.14", 443)


async def test_connect_refuses_a_private_answer(monkeypatch):
    monkeypatch.setattr(utils, "_resolve_host", _dns(["169.254.169.254"]))
    backend, inner = _backend()
    with pytest.raises(httpcore.ConnectError, match="not a public address"):
        await backend.connect_tcp("rebind.example", 443)
    inner.connect_tcp.assert_not_called()


@pytest.mark.parametrize("answers", [[], ["93.184.215.14", "10.0.0.1"]])
async def test_connect_refuses_no_answer_or_any_private_answer(monkeypatch, answers):
    monkeypatch.setattr(utils, "_resolve_host", _dns(answers))
    backend, inner = _backend()
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("mixed.example", 443)
    inner.connect_tcp.assert_not_called()


async def test_literal_private_ip_refused_without_dns(monkeypatch):
    monkeypatch.setattr(utils, "_resolve_host", AsyncMock(side_effect=AssertionError("no DNS")))
    backend, inner = _backend()
    with pytest.raises(httpcore.ConnectError):
        await backend.connect_tcp("127.0.0.1", 443)


async def test_allow_local_fetch_opts_out(monkeypatch):
    monkeypatch.setenv("KITSUNE_ALLOW_LOCAL_FETCH", "1")
    backend, inner = _backend()
    await backend.connect_tcp("localhost", 8000)
    assert inner.connect_tcp.await_args.args[:2] == ("localhost", 8000)


async def test_configured_proxy_host_is_not_pinned(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp.internal:3128")
    backend, inner = _backend()
    await backend.connect_tcp("proxy.corp.internal", 3128)
    assert inner.connect_tcp.await_args.args[:2] == ("proxy.corp.internal", 3128)


async def test_rebinding_between_check_and_connect_is_blocked(monkeypatch):
    """First lookup (the pre-check) says public, the connect-time lookup says private."""
    monkeypatch.setattr(utils, "_resolve_host", _dns(["93.184.215.14"], ["127.0.0.1"]))
    with pytest.raises(Exception, match="not a public address"):
        await utils._ssrf_safe_request("GET", "https://rebind.example/")


def test_guarded_client_uses_the_pinning_backend():
    client = utils._get_guarded_client()
    pool = client._transport._pool
    assert isinstance(pool._network_backend, utils._PublicOnlyBackend)
    assert client is utils._get_guarded_client()  # shared, like the main client
