"""Regression tests for hot-path caching (perf/hot-path-caching)."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from kitsune_mcp import credentials as creds
from kitsune_mcp.utils import _clean_response, _clean_truncate, _truncate


class TestDotenvReparseOnlyOnChange:
    def test_unchanged_files_are_not_reparsed(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("KITSUNE_PERF_A=1\n")
        monkeypatch.setattr(creds, "_DOTENV_PATHS", [env_file])
        monkeypatch.setattr(creds, "_last_dotenv_mtimes", creds._dotenv_mtimes())
        calls = []
        monkeypatch.setattr(creds, "_load_dotenv_files", lambda: calls.append(1))
        for _ in range(5):
            creds._reload_dotenv()
        assert calls == []

    def test_edit_is_picked_up_even_with_same_mtime(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text("KITSUNE_PERF_B=old\n")
        st = env_file.stat()
        monkeypatch.setattr(creds, "_DOTENV_PATHS", [env_file])
        monkeypatch.setattr(creds, "_last_dotenv_mtimes", creds._dotenv_mtimes())
        monkeypatch.delenv("KITSUNE_PERF_B", raising=False)
        before = creds._dotenv_revision

        # Same mtime, different size: still a change.
        env_file.write_text("KITSUNE_PERF_B=newer\n")
        os.utime(env_file, ns=(st.st_atime_ns, st.st_mtime_ns))
        creds._reload_dotenv()

        assert creds._dotenv_revision == before + 1
        assert os.environ["KITSUNE_PERF_B"] == "newer"
        monkeypatch.delenv("KITSUNE_PERF_B", raising=False)


class TestCleanTruncate:
    def test_small_input_matches_original_pipeline(self):
        text = "see [docs](https://x.y)   now\n\n\n\nok ![img]"
        assert _clean_truncate(text) == _truncate(_clean_response(text))

    def test_huge_input_is_truncated_with_marker(self):
        text = "abc [link](http://example.com) " * 200_000  # ~6 MB
        out = _clean_truncate(text, max_tokens=100)
        assert out.endswith("[...truncated at ~100 tokens]")
        assert out.startswith("abc link abc link")
        assert len(out) <= 400 + len("\n[...truncated at ~100 tokens]")
        assert out == _truncate(_clean_response(text), max_tokens=100)


class TestScopedRegistryReuse:
    def test_same_class_returns_same_instance(self):
        from kitsune_mcp.tools.discovery import _scoped_registry

        class Dummy:
            pass

        assert _scoped_registry(Dummy) is _scoped_registry(Dummy)


class TestCallReusesMountedForm:
    @pytest.mark.asyncio
    async def test_call_on_mounted_form_skips_registry(self, monkeypatch):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import exec as exec_mod

        srv = SimpleNamespace(credentials={}, source="official")
        transport = SimpleNamespace(execute=AsyncMock(return_value="ran"))
        lookup = AsyncMock(side_effect=AssertionError("registry must not be queried"))
        monkeypatch.setitem(session, "current_form", "mounted-srv")
        monkeypatch.setitem(session, "current_form_srv", srv)
        monkeypatch.setitem(session, "current_form_pool_key", None)
        with (
            patch.object(exec_mod._state._registry, "get_server", lookup),
            patch.object(exec_mod._state, "transport_for_exec", return_value=(transport, "")),
        ):
            result = await exec_mod.call("some_tool", "mounted-srv", {})
        assert result == "ran"
        lookup.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_call_on_other_server_still_queries_registry(self, monkeypatch):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import exec as exec_mod

        other = SimpleNamespace(credentials={}, source="official")
        transport = SimpleNamespace(execute=AsyncMock(return_value="ran"))
        lookup = AsyncMock(return_value=other)
        monkeypatch.setitem(session, "current_form", "mounted-srv")
        monkeypatch.setitem(
            session, "current_form_srv", SimpleNamespace(credentials={}, source="x")
        )
        with (
            patch.object(exec_mod._state._registry, "get_server", lookup),
            patch.object(exec_mod._state, "transport_for_exec", return_value=(transport, "")),
        ):
            await exec_mod.call("some_tool", "another-srv", {})
        lookup.assert_awaited_once()


class TestStatusDoesNotWaitOnBusyEntry:
    @pytest.mark.asyncio
    async def test_busy_entry_reported_without_ping(self, monkeypatch):
        import time

        from kitsune_mcp import transport as tp
        from kitsune_mcp.tools import discovery
        from tests.test_transport_coverage import make_mock_process

        entry = tp._PoolEntry(
            proc=make_mock_process(), install_cmd=["busy-cmd"], started_at=time.monotonic()
        )
        monkeypatch.setitem(tp._process_pool, "busy-key", entry)
        ping = AsyncMock(side_effect=AssertionError("must not ping a busy entry"))
        monkeypatch.setattr(discovery, "_ping", ping)
        async with entry.lock:  # simulate a tool call in flight
            out = await discovery.status()
        assert "alive+busy" in out
        ping.assert_not_awaited()
