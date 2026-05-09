"""SSRF protection tests for fetch() and craft()."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- _is_safe_url unit tests ---


def test_is_safe_url_blocks_loopback():
    from kitsune_mcp.tools.onboarding import _is_safe_url
    assert not _is_safe_url("http://127.0.0.1/")
    assert not _is_safe_url("https://127.0.0.1/")
    assert not _is_safe_url("http://localhost/")
    assert not _is_safe_url("https://localhost/api")


def test_is_safe_url_blocks_private():
    from kitsune_mcp.tools.onboarding import _is_safe_url
    assert not _is_safe_url("https://192.168.1.1/")
    assert not _is_safe_url("https://10.0.0.1/api")
    assert not _is_safe_url("https://172.16.0.1/")


def test_is_safe_url_blocks_link_local():
    from kitsune_mcp.tools.onboarding import _is_safe_url
    assert not _is_safe_url("https://169.254.169.254/latest/meta-data/")


def test_is_safe_url_blocks_http_scheme():
    from kitsune_mcp.tools.onboarding import _is_safe_url
    assert not _is_safe_url("http://example.com/")


def test_is_safe_url_passes_public_https():
    from kitsune_mcp.tools.onboarding import _is_safe_url
    assert _is_safe_url("https://example.com")
    assert _is_safe_url("https://api.example.com/v1/data")


# --- fetch() SSRF guard ---


@pytest.mark.asyncio
async def test_fetch_blocks_loopback(monkeypatch):
    monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
    from kitsune_mcp.tools.exec import fetch
    result = await fetch("http://127.0.0.1/")
    assert "Blocked" in result


@pytest.mark.asyncio
async def test_fetch_blocks_metadata_endpoint(monkeypatch):
    monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
    from kitsune_mcp.tools.exec import fetch
    result = await fetch("https://169.254.169.254/latest/meta-data/")
    assert "Blocked" in result


@pytest.mark.asyncio
async def test_fetch_passes_public_url(monkeypatch, respx_mock):
    monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
    import respx
    import httpx
    respx_mock.get("https://example.com").mock(return_value=httpx.Response(200, text="hello"))

    with patch("kitsune_mcp.tools.exec._try_axonmcp", new=AsyncMock(return_value=None)):
        from kitsune_mcp.tools.exec import fetch
        result = await fetch("https://example.com")
    assert "Blocked" not in result


@pytest.mark.asyncio
async def test_fetch_allow_local_override(monkeypatch, respx_mock):
    monkeypatch.setenv("KITSUNE_ALLOW_LOCAL_FETCH", "1")
    import httpx
    respx_mock.get("http://127.0.0.1/").mock(return_value=httpx.Response(200, text="local ok"))

    with patch("kitsune_mcp.tools.exec._try_axonmcp", new=AsyncMock(return_value=None)):
        from kitsune_mcp.tools.exec import fetch
        result = await fetch("http://127.0.0.1/")
    assert "Blocked" not in result


# --- craft() SSRF guard ---


@pytest.mark.asyncio
async def test_craft_blocks_private_url(monkeypatch):
    monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
    ctx = MagicMock()
    ctx.session = AsyncMock()
    from kitsune_mcp.tools.morph import craft
    result = await craft(ctx=ctx, name="my_tool", description="test", params={}, url="https://192.168.1.1/api")
    assert "Blocked" in result


@pytest.mark.asyncio
async def test_craft_blocks_loopback_url(monkeypatch):
    monkeypatch.delenv("KITSUNE_ALLOW_LOCAL_FETCH", raising=False)
    ctx = MagicMock()
    ctx.session = AsyncMock()
    from kitsune_mcp.tools.morph import craft
    result = await craft(ctx=ctx, name="my_tool", description="test", params={}, url="http://127.0.0.1/api")
    assert "Blocked" in result
