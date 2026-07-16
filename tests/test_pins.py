"""Tests for trust-on-first-use (TOFU) version pinning (kitsune_mcp/pins.py).

Resolution-time pinning (npx -y pkg@1.2.3) makes one session reproducible but
"latest" drifts across sessions. TOFU records the version trusted on first
mount in ~/.kitsune/pins.json, reuses it on later mounts, and warns when the
registry has moved on — so a post-install package hijack surfaces instead of
silently executing. KITSUNE_REPIN=1 adopts the newer version.
"""
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kitsune_mcp import pins
from kitsune_mcp.registry import ServerInfo


@pytest.fixture(autouse=True)
def _isolated_pins_home(tmp_path, monkeypatch):
    """Every test gets its own empty pins store and no repin policy."""
    monkeypatch.setenv("KITSUNE_HOME", str(tmp_path))
    monkeypatch.delenv("KITSUNE_REPIN", raising=False)
    yield


class TestParseSpec:
    def test_npx_bare(self):
        assert pins._parse_spec(["npx", "-y", "pkg@1.2.3"]) == (2, "pkg", "1.2.3", "@")

    def test_npx_scoped(self):
        assert pins._parse_spec(["npx", "-y", "@scope/pkg@1.2.3"]) == (2, "@scope/pkg", "1.2.3", "@")

    def test_uvx(self):
        assert pins._parse_spec(["uvx", "pkg==1.2.3"]) == (1, "pkg", "1.2.3", "==")

    def test_npx_no_version_returns_none(self):
        assert pins._parse_spec(["npx", "-y", "pkg"]) is None

    def test_scoped_no_version_returns_none(self):
        assert pins._parse_spec(["npx", "-y", "@scope/pkg"]) is None

    def test_uvx_no_version_returns_none(self):
        assert pins._parse_spec(["uvx", "pkg"]) is None

    def test_github_target_returns_none(self):
        assert pins._parse_spec(["npx", "-y", "github:owner/repo"]) is None

    def test_non_launcher_returns_none(self):
        assert pins._parse_spec(["node", "server.js"]) is None

    def test_empty_returns_none(self):
        assert pins._parse_spec([]) is None


class TestReconcile:
    def test_first_use_records_and_notes(self):
        cmd, note = pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")
        assert cmd == ["npx", "-y", "some-pkg@1.2.3"]  # unchanged
        assert "first use" in note.lower()
        assert "1.2.3" in note
        stored = pins.get_pin("some-pkg")
        assert stored == {"source": "npm", "name": "some-pkg", "version": "1.2.3"}

    def test_same_version_is_silent(self):
        pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")
        cmd, note = pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")
        assert cmd == ["npx", "-y", "some-pkg@1.2.3"]
        assert note == ""

    def test_drift_runs_pinned_and_warns(self):
        pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")  # pin 1.2.3
        cmd, note = pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.3.0"], "npm")
        assert cmd == ["npx", "-y", "some-pkg@1.2.3"]  # ran the PINNED version
        assert "1.2.3" in note and "1.3.0" in note
        assert "KITSUNE_REPIN" in note
        # Pin is unchanged by a drift-without-repin
        assert pins.get_pin("some-pkg")["version"] == "1.2.3"

    def test_drift_rewrites_scoped_correctly(self):
        pins.reconcile("s", ["npx", "-y", "@scope/pkg@1.0.0"], "npm")
        cmd, _ = pins.reconcile("s", ["npx", "-y", "@scope/pkg@2.0.0"], "npm")
        assert cmd == ["npx", "-y", "@scope/pkg@1.0.0"]

    def test_drift_rewrites_uvx(self):
        pins.reconcile("p", ["uvx", "p==1.0.0"], "pypi")
        cmd, _ = pins.reconcile("p", ["uvx", "p==2.0.0"], "pypi")
        assert cmd == ["uvx", "p==1.0.0"]

    def test_repin_flag_adopts_new_version(self):
        pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")
        cmd, note = pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.3.0"], "npm", repin=True)
        assert cmd == ["npx", "-y", "some-pkg@1.3.0"]  # ran the new version
        assert "1.2.3" in note and "1.3.0" in note  # repinned X → Y
        assert pins.get_pin("some-pkg")["version"] == "1.3.0"  # pin updated

    def test_repin_env_policy(self, monkeypatch):
        pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")
        monkeypatch.setenv("KITSUNE_REPIN", "1")
        cmd, _ = pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.3.0"], "npm")
        assert cmd == ["npx", "-y", "some-pkg@1.3.0"]
        assert pins.get_pin("some-pkg")["version"] == "1.3.0"

    def test_unpinnable_cmd_passes_through_and_writes_nothing(self):
        cmd, note = pins.reconcile("gh-srv", ["npx", "-y", "github:o/r"], "github")
        assert cmd == ["npx", "-y", "github:o/r"]
        assert note == ""
        assert not pins._pins_path().exists()  # no store created

    def test_explicit_repin_false_overrides_env(self, monkeypatch):
        pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.2.3"], "npm")
        monkeypatch.setenv("KITSUNE_REPIN", "1")
        cmd, _ = pins.reconcile("some-pkg", ["npx", "-y", "some-pkg@1.3.0"], "npm", repin=False)
        assert cmd == ["npx", "-y", "some-pkg@1.2.3"]  # pinned wins despite env


class TestStore:
    def test_round_trip_persists_to_disk(self):
        pins.record_pin("a", "npm", "a", "1.0.0")
        raw = json.loads(pins._pins_path().read_text())
        assert raw["version"] == pins.PINS_VERSION
        assert raw["pins"]["a"]["version"] == "1.0.0"

    def test_missing_file_is_empty(self):
        assert pins._load() == {}
        assert pins.get_pin("nope") is None

    def test_corrupt_file_tolerated(self):
        p = pins._pins_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json")
        assert pins._load() == {}

    def test_pins_file_is_private(self):
        pins.record_pin("a", "npm", "a", "1.0.0")
        mode = pins._pins_path().stat().st_mode & 0o777
        assert mode == 0o600

    def test_honors_kitsune_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KITSUNE_HOME", str(tmp_path / "custom"))
        pins.record_pin("a", "npm", "a", "1.0.0")
        assert (tmp_path / "custom" / "pins.json").exists()


# --------------------------------------------------------------------------
# Integration through shapeshift()
# --------------------------------------------------------------------------

def _ctx():
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.send_tool_list_changed = AsyncMock()
    ctx.session.send_resource_list_changed = AsyncMock()
    ctx.session.send_prompt_list_changed = AsyncMock()
    return ctx


_PING = {"name": "ping", "description": "", "inputSchema": {"type": "object", "properties": {}, "required": []}}


def _npm_srv(version="1.2.3"):
    return ServerInfo(
        id="some-pkg", name="some-pkg", description="", source="npm",
        transport="stdio", url="", install_cmd=["npx", "-y", f"some-pkg@{version}"],
        credentials={}, tools=[_PING],
    )


def _capture_factory(captured):
    def factory(cmd, **kw):
        captured.append(cmd)
        t = MagicMock()
        t.list_tools = AsyncMock(return_value=[_PING])
        t.list_resources = AsyncMock(return_value=[])
        t.list_prompts = AsyncMock(return_value=[])
        return t
    return factory


@pytest.mark.asyncio
class TestShapeshiftPinning:
    async def _mount(self, srv, monkeypatch):
        from kitsune_mcp.tools import _state, shapeshift
        from kitsune_mcp.tools._state import _registry
        monkeypatch.setenv("KITSUNE_TRUST", "community")  # skip the npm consent gate
        captured = []
        try:
            with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
                 patch.object(_state, "PersistentStdioTransport", _capture_factory(captured)), \
                 patch.object(_state, "_probe_requirements", return_value={"missing_env": []}):
                result = await shapeshift(srv.id, _ctx())
        finally:
            _state._do_shed()
        return result, captured

    async def test_first_mount_pins_and_labels(self, monkeypatch):
        result, captured = await self._mount(_npm_srv("1.2.3"), monkeypatch)
        assert result.startswith("Shapeshifted"), result
        assert captured[0] == ["npx", "-y", "some-pkg@1.2.3"]
        assert "first use" in result.lower()
        assert pins.get_pin("some-pkg")["version"] == "1.2.3"

    async def test_second_mount_after_drift_runs_pinned_version(self, monkeypatch):
        await self._mount(_npm_srv("1.2.3"), monkeypatch)          # pin 1.2.3
        result, captured = await self._mount(_npm_srv("1.3.0"), monkeypatch)  # registry moved
        assert captured[0] == ["npx", "-y", "some-pkg@1.2.3"]      # still 1.2.3
        assert "1.3.0" in result and "KITSUNE_REPIN" in result

    async def test_repin_env_upgrades(self, monkeypatch):
        await self._mount(_npm_srv("1.2.3"), monkeypatch)
        monkeypatch.setenv("KITSUNE_REPIN", "1")
        result, captured = await self._mount(_npm_srv("1.3.0"), monkeypatch)
        assert captured[0] == ["npx", "-y", "some-pkg@1.3.0"]
        assert pins.get_pin("some-pkg")["version"] == "1.3.0"

    async def test_pinned_version_flows_into_sandbox(self, monkeypatch):
        await self._mount(_npm_srv("1.2.3"), monkeypatch)  # pin 1.2.3
        from kitsune_mcp.tools import _state, shapeshift
        from kitsune_mcp.tools._state import _registry
        monkeypatch.setenv("KITSUNE_TRUST", "community")
        captured = []
        try:
            with patch.object(_registry, "get_server", AsyncMock(return_value=_npm_srv("1.3.0"))), \
                 patch.object(_state, "PersistentStdioTransport", _capture_factory(captured)), \
                 patch.object(_state, "_probe_requirements", return_value={"missing_env": []}), \
                 patch("kitsune_mcp.tools.shapeshift.shutil.which", return_value="/usr/bin/docker"):
                result = await shapeshift("some-pkg", _ctx(), sandbox=True)
        finally:
            _state._do_shed()
        assert result.startswith("Shapeshifted"), result
        # The docker-wrapped command still ends in the PINNED spec, not 1.3.0
        assert captured[0][0] == "docker"
        assert captured[0][-1] == "some-pkg@1.2.3"
