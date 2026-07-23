"""Tests for best-effort sandbox-by-default on the exec paths.

shapeshift() gates + optionally sandboxes local servers, but the "magic" exec
paths — auto() (model picks the server), call() ad-hoc, and run() — used to spawn
community npx/uvx processes uncaged. These paths now default to the hardened
Docker cage for low-trust / unknown-source local servers, BEST-EFFORT:

- Docker present → wrap the launch in `docker run` automatically.
- Docker absent  → run uncaged and return a nudge note (never hard-fail).
- High-trust registry sources (official/absorbed/registries) are NOT caged
  by default; an explicit KITSUNE_SANDBOX policy still applies on top.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kitsune_mcp.registry import ServerInfo


def _srv(id="some-pkg", name="some-pkg", source="npm", transport="stdio",
         install_cmd=None, credentials=None, tools=None, url=""):
    if install_cmd is None:
        install_cmd = ["npx", "-y", f"{id}@1.2.3"]
    return ServerInfo(
        id=id, name=name, description="test server", source=source,
        transport=transport, url=url, install_cmd=install_cmd,
        credentials=credentials or {}, tools=tools if tools is not None else [],
    )


def _capture_transports(monkeypatch):
    """Patch _state.PersistentStdioTransport to record the argv it was built with."""
    captured: list = []

    def factory(cmd, **kwargs):
        captured.append(cmd)
        t = MagicMock()
        t.execute = AsyncMock(return_value="ok")
        t.list_tools = AsyncMock(return_value=[])
        t.list_resources = AsyncMock(return_value=[])
        t.list_prompts = AsyncMock(return_value=[])
        return t

    monkeypatch.setattr("kitsune_mcp.tools._state.PersistentStdioTransport", factory)
    return captured


def _docker(available: bool, monkeypatch):
    monkeypatch.setattr(
        "kitsune_mcp.tools._state.shutil.which",
        (lambda name: "/usr/local/bin/docker") if available else (lambda name: None),
    )


# ---------------------------------------------------------------------------
# Policy resolution
# ---------------------------------------------------------------------------
class TestSandboxDefaultForExec:
    def test_community_source_sandboxes_by_default(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_default_for_exec
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        assert _sandbox_default_for_exec(False, "npm") is True
        assert _sandbox_default_for_exec(False, "pypi") is True
        assert _sandbox_default_for_exec(False, "github") is True

    def test_unknown_source_sandboxes_by_default(self, monkeypatch):
        """run() and ad-hoc call() often have no registry entry — treat the
        unknown source as untrusted and cage it."""
        from kitsune_mcp.tools._state import _sandbox_default_for_exec
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        assert _sandbox_default_for_exec(False, "") is True

    def test_trusted_sources_not_sandboxed_by_default(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_default_for_exec
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        assert _sandbox_default_for_exec(False, "official") is False
        assert _sandbox_default_for_exec(False, "absorbed") is False
        # medium-trust registries are vetted enough to skip the default cage
        assert _sandbox_default_for_exec(False, "mcpregistry") is False
        assert _sandbox_default_for_exec(False, "smithery") is False

    def test_explicit_all_policy_still_applies(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_default_for_exec
        monkeypatch.setenv("KITSUNE_SANDBOX", "all")
        assert _sandbox_default_for_exec(False, "official") is True

    def test_off_policy_disables_default_cage(self, monkeypatch):
        """KITSUNE_SANDBOX=off is the escape hatch — it must also turn off the
        low-trust/unknown-source default cage, not just the all/community policy."""
        from kitsune_mcp.tools._state import _sandbox_default_for_exec
        monkeypatch.setenv("KITSUNE_SANDBOX", "off")
        assert _sandbox_default_for_exec(False, "npm") is False
        assert _sandbox_default_for_exec(False, "") is False
        # explicit request still wins over the off policy
        assert _sandbox_default_for_exec(True, "npm") is True


# ---------------------------------------------------------------------------
# Tri-state mount resolver (shapeshift()/prewarm())
# ---------------------------------------------------------------------------
class TestSandboxForMount:
    def test_true_always_cages(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_for_mount
        monkeypatch.setenv("KITSUNE_SANDBOX", "off")
        assert _sandbox_for_mount(True, "official") is True

    def test_false_never_cages(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_for_mount
        monkeypatch.setenv("KITSUNE_SANDBOX", "all")
        assert _sandbox_for_mount(False, "npm") is False

    def test_none_uses_default_policy(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_for_mount
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        assert _sandbox_for_mount(None, "npm") is True
        assert _sandbox_for_mount(None, "official") is False

    def test_none_honors_off(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_for_mount
        monkeypatch.setenv("KITSUNE_SANDBOX", "off")
        assert _sandbox_for_mount(None, "npm") is False


# ---------------------------------------------------------------------------
# Best-effort wrap
# ---------------------------------------------------------------------------
class TestSandboxedStdioTransport:
    def test_wraps_community_launch_when_docker_present(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        _t, note = _state.sandboxed_stdio_transport(["npx", "-y", "pkg@1.0.0"], _srv(source="npm"))
        assert captured[0][:2] == ["docker", "run"]
        assert note == ""

    def test_runs_uncaged_with_note_when_docker_absent(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(False, monkeypatch)
        captured = _capture_transports(monkeypatch)
        _t, note = _state.sandboxed_stdio_transport(["npx", "-y", "pkg@1.0.0"], _srv(source="npm"))
        assert captured[0] == ["npx", "-y", "pkg@1.0.0"]  # NOT wrapped
        assert "uncaged" in note.lower()
        assert "docker" in note.lower()

    def test_trusted_source_not_wrapped_even_with_docker(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        _t, note = _state.sandboxed_stdio_transport(["npx", "-y", "pkg"], _srv(source="official"))
        assert captured[0] == ["npx", "-y", "pkg"]
        assert note == ""

    def test_non_npx_launch_never_wrapped(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        _t, note = _state.sandboxed_stdio_transport(["node", "server.js"], _srv(source="npm"))
        assert captured[0] == ["node", "server.js"]
        assert note == ""

    def test_credential_names_forwarded_when_wrapped(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        srv = _srv(source="npm", credentials={"notion_token": "Notion token"})
        _state.sandboxed_stdio_transport(["npx", "-y", "pkg"], srv)
        assert "NOTION_TOKEN" in captured[0]
        assert not any(a.startswith("NOTION_TOKEN=") for a in captured[0])


# ---------------------------------------------------------------------------
# Routing helper
# ---------------------------------------------------------------------------
class TestTransportForExec:
    def test_http_server_routes_unchanged_no_note(self, monkeypatch):
        from kitsune_mcp.tools import _state
        _docker(True, monkeypatch)
        _t, note = _state.transport_for_exec("https://example.com/mcp", None)
        assert note == ""

    def test_stdio_community_server_is_sandboxed(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        _t, note = _state.transport_for_exec("some-pkg", _srv(source="npm"))
        assert captured[0][:2] == ["docker", "run"]
        assert note == ""

    def test_unknown_package_defaults_to_npx_and_sandboxes(self, monkeypatch):
        from kitsune_mcp.tools import _state
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        _state.transport_for_exec("@scope/pkg", None)
        assert captured[0][:2] == ["docker", "run"]
        # inferred an npx launch for the @scope package
        assert "npx" in captured[0]


# ---------------------------------------------------------------------------
# Integration: run() sandboxes ad-hoc npm packages
# ---------------------------------------------------------------------------
class TestRunSandboxesByDefault:
    @pytest.mark.asyncio
    async def test_run_caged_when_docker_present(self, monkeypatch):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools import exec as exec_mod
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(True, monkeypatch)
        captured = _capture_transports(monkeypatch)
        monkeypatch.setattr(_state, "_track_call", lambda *a, **k: None)
        await exec_mod.run("some-pkg", "ping", {})
        assert captured[0][:2] == ["docker", "run"]

    @pytest.mark.asyncio
    async def test_run_uncaged_note_when_docker_absent(self, monkeypatch):
        from kitsune_mcp.tools import _state
        from kitsune_mcp.tools import exec as exec_mod
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        _docker(False, monkeypatch)
        captured = _capture_transports(monkeypatch)
        monkeypatch.setattr(_state, "_track_call", lambda *a, **k: None)
        result = await exec_mod.run("some-pkg", "ping", {})
        assert captured[0] == ["npx", "-y", "some-pkg"]
        assert "uncaged" in result.lower()
