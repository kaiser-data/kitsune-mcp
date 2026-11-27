"""Norma review fixes: visible .env write failures, bounded compare fan-out,
registry outage reported by shapeshift()."""

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def test_save_to_env_reports_write_failure(tmp_path, monkeypatch):
    from kitsune_mcp import credentials

    monkeypatch.setattr(credentials, "ENV_PATH", str(tmp_path / "nodir" / "x" / ".env"))
    monkeypatch.setattr(credentials, "_KITSUNE_HOME", tmp_path / "file")
    (tmp_path / "file").write_text("")  # mkdir() on a file raises OSError
    monkeypatch.delenv("NORMA_TEST_TOKEN", raising=False)
    assert credentials._save_to_env("NORMA_TEST_TOKEN", "abcdef123") is False
    import os

    assert os.environ["NORMA_TEST_TOKEN"] == "abcdef123"  # still active this session
    monkeypatch.delenv("NORMA_TEST_TOKEN")


def test_saved_message_does_not_claim_saved_on_failure():
    from kitsune_mcp.tools.onboarding import _saved_message

    assert _saved_message("X_KEY", "abcdef123", True).startswith("Saved:")
    msg = _saved_message("X_KEY", "abcdef123", False)
    assert "Not saved" in msg and "Saved:" not in msg
    assert "abcdef123" not in msg


@pytest.mark.asyncio
async def test_compare_probes_are_bounded():
    from kitsune_mcp.tools import _state, discovery

    running = peak = 0

    async def fake_probe(srv, allow_low_trust):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return {"tokens": None, "tools": 0, "src": "x", "status": "ok", "id": srv.id}

    servers = [MagicMock(id=f"s{i}") for i in range(30)]
    with (
        patch.object(_state, "_registry") as reg,
        patch.object(discovery, "_compare_probe", side_effect=fake_probe),
    ):
        reg.search = AsyncMock(return_value=servers)
        with contextlib.suppress(Exception):  # row formatting is not under test
            await discovery._run_compare("q", limit=30)
    assert 0 < peak <= discovery._COMPARE_MAX_CONCURRENT_PROBES


@pytest.mark.asyncio
async def test_resolve_records_search_failure():
    from kitsune_mcp.tools import _state

    with patch.object(_state, "_registry") as reg:
        reg.search = AsyncMock(side_effect=RuntimeError("down"))
        rid, cands = await _state._resolve_server_id("anything")
        assert (rid, cands) == (None, [])
        assert reg.last_registry_errors == {"search": "RuntimeError"}
