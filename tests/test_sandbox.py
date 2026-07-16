"""Tests for the Docker sandbox for local npm/PyPI servers.

The last hardening pass locked down DockerTransport, but that profile was only
reachable via explicit `docker:` server IDs — npm/PyPI servers still ran as raw
host subprocesses. `sandbox=True` (or KITSUNE_SANDBOX) routes local npx/uvx
launches through the same hardened `docker run` profile:

- sandbox_wrap_cmd() builds the wrapped argv (transport.py)
- credential env vars are forwarded by NAME only (`-e KEY`) — no secret ever
  lands in the argv, the process list, or the pool key
- shapeshift(sandbox=True) wraps the stdio launch; KITSUNE_SANDBOX=all|community
  applies it as a session policy without the per-call flag
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from kitsune_mcp.constants import SANDBOX_NPM_IMAGE, SANDBOX_PYPI_IMAGE
from kitsune_mcp.registry import ServerInfo
from kitsune_mcp.transport import sandbox_wrap_cmd


class TestSandboxWrapCmd:
    def test_npx_command_is_wrapped_in_hardened_docker_run(self):
        wrapped = sandbox_wrap_cmd(["npx", "-y", "some-pkg@1.2.3"])
        assert wrapped[:4] == ["docker", "run", "--rm", "-i"]
        # Hardened profile — same flags DockerTransport applies
        for flag in ("--pids-limit", "--security-opt", "--cap-drop", "--read-only", "--memory"):
            assert flag in wrapped
        assert "ALL" in wrapped
        assert SANDBOX_NPM_IMAGE in wrapped
        # Original command preserved verbatim after the image
        img_idx = wrapped.index(SANDBOX_NPM_IMAGE)
        assert wrapped[img_idx + 1:] == ["npx", "-y", "some-pkg@1.2.3"]

    def test_sandbox_tmpfs_is_executable(self):
        """npx/uvx must be able to EXECUTE what they download into /tmp.

        Docker's default --tmpfs options include noexec, which broke every
        real sandboxed launch with 'Permission denied (os error 13)' — the
        wrap points HOME and the package caches at /tmp, so the server's
        entrypoint always lands there. Caught by the docker-e2e CI job.
        """
        wrapped = sandbox_wrap_cmd(["npx", "-y", "some-pkg@1.2.3"])
        tmpfs = wrapped[wrapped.index("--tmpfs") + 1]
        assert tmpfs.startswith("/tmp:")
        assert "exec" in tmpfs.split(":", 1)[1].split(",")
        assert "nosuid" in tmpfs

    def test_docker_transport_tmpfs_keeps_noexec_default(self):
        """docker: images ship their server in the image — their scratch
        tmpfs stays on Docker's stricter default (noexec)."""
        from kitsune_mcp.transport import _hardened_docker_flags

        flags = _hardened_docker_flags({})
        assert flags[flags.index("--tmpfs") + 1] == "/tmp"

    def test_uvx_command_uses_pypi_image_and_uv_cache(self):
        wrapped = sandbox_wrap_cmd(["uvx", "some-pkg==1.2.3"])
        assert SANDBOX_PYPI_IMAGE in wrapped
        assert "UV_CACHE_DIR=/tmp/.uv-cache" in wrapped
        img_idx = wrapped.index(SANDBOX_PYPI_IMAGE)
        assert wrapped[img_idx + 1:] == ["uvx", "some-pkg==1.2.3"]

    def test_npx_gets_writable_home_and_npm_cache_on_tmpfs(self):
        """--read-only rootfs would break npx (writes to ~/.npm) without a
        tmpfs-backed HOME. The wrap must redirect both to /tmp."""
        wrapped = sandbox_wrap_cmd(["npx", "-y", "pkg"])
        assert "HOME=/tmp" in wrapped
        assert "npm_config_cache=/tmp/.npm" in wrapped

    def test_env_names_forwarded_value_less(self):
        """Secrets pass through by NAME (`-e KEY`) so docker reads the value
        from its own environment — never inlined into the argv."""
        wrapped = sandbox_wrap_cmd(["npx", "-y", "pkg"], env_names=["NOTION_TOKEN"])
        idx = wrapped.index("NOTION_TOKEN")
        assert wrapped[idx - 1] == "-e"
        assert not any(a.startswith("NOTION_TOKEN=") for a in wrapped)

    def test_server_args_preserved_in_order(self):
        wrapped = sandbox_wrap_cmd(["npx", "-y", "server-fs", "/data", "--verbose"])
        img_idx = wrapped.index(SANDBOX_NPM_IMAGE)
        assert wrapped[img_idx + 1:] == ["npx", "-y", "server-fs", "/data", "--verbose"]

    def test_unsupported_launcher_raises(self):
        with pytest.raises(ValueError, match="npx/uvx"):
            sandbox_wrap_cmd(["node", "server.js"])

    def test_empty_command_raises(self):
        with pytest.raises(ValueError):
            sandbox_wrap_cmd([])

    def test_writable_config_drops_read_only(self):
        wrapped = sandbox_wrap_cmd(["npx", "-y", "pkg"], config={"writable": True})
        assert "--read-only" not in wrapped


class TestSandboxActive:
    def test_explicit_flag_wins(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_active
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        assert _sandbox_active(True, "official") is True

    def test_off_by_default(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_active
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        assert _sandbox_active(False, "npm") is False

    @pytest.mark.parametrize("mode", ["1", "true", "all", "docker"])
    def test_all_mode_sandboxes_every_source(self, monkeypatch, mode):
        from kitsune_mcp.tools._state import _sandbox_active
        monkeypatch.setenv("KITSUNE_SANDBOX", mode)
        assert _sandbox_active(False, "official") is True
        assert _sandbox_active(False, "npm") is True

    def test_community_mode_sandboxes_only_low_trust(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_active
        monkeypatch.setenv("KITSUNE_SANDBOX", "community")
        assert _sandbox_active(False, "npm") is True
        assert _sandbox_active(False, "pypi") is True
        assert _sandbox_active(False, "official") is False


class TestSandboxEnvNames:
    def test_declared_credentials_first(self):
        from kitsune_mcp.tools._state import _sandbox_env_names
        srv = _srv(credentials={"notion_token": "Notion API token"})
        assert "NOTION_TOKEN" in _sandbox_env_names(srv)

    def test_heuristic_matches_host_vars_by_server_name(self, monkeypatch):
        """Undeclared creds (npm/pypi listings declare none) still reach the
        container when the host var shares a name token with the server."""
        from kitsune_mcp.tools._state import _sandbox_env_names
        monkeypatch.setenv("EXAMPLECORP_API_KEY", "sk-secret")
        srv = _srv(id="examplecorp-mcp", name="examplecorp-mcp")
        assert "EXAMPLECORP_API_KEY" in _sandbox_env_names(srv)

    def test_unrelated_host_vars_excluded(self, monkeypatch):
        from kitsune_mcp.tools._state import _sandbox_env_names
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
        srv = _srv(id="examplecorp-mcp", name="examplecorp-mcp")
        assert "AWS_SECRET_ACCESS_KEY" not in _sandbox_env_names(srv)


def _ctx():
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.send_tool_list_changed = AsyncMock()
    ctx.session.send_resource_list_changed = AsyncMock()
    ctx.session.send_prompt_list_changed = AsyncMock()
    return ctx


_PING_TOOL = {"name": "ping", "description": "", "inputSchema": {"type": "object", "properties": {}, "required": []}}


def _srv(id="some-pkg", name="some-pkg", source="npm", transport="stdio",
         install_cmd=None, credentials=None, tools=None, url=""):
    if install_cmd is None:
        install_cmd = ["npx", "-y", f"{id}@1.2.3"]
    return ServerInfo(
        id=id, name=name, description="test server", source=source,
        transport=transport, url=url, install_cmd=install_cmd,
        credentials=credentials or {}, tools=tools if tools is not None else [_PING_TOOL],
    )


def _fake_transport_factory(captured_cmds: list):
    def factory(cmd, **kwargs):
        captured_cmds.append(cmd)
        t = MagicMock()
        t.list_tools = AsyncMock(return_value=[_PING_TOOL])
        t.list_resources = AsyncMock(return_value=[])
        t.list_prompts = AsyncMock(return_value=[])
        return t
    return factory


@pytest.mark.asyncio
class TestShapeshiftSandbox:
    async def _mount(self, srv, monkeypatch, docker="/usr/local/bin/docker", **kwargs):
        from kitsune_mcp.tools import _state, shapeshift
        from kitsune_mcp.tools._state import _registry
        monkeypatch.delenv("KITSUNE_TRUST", raising=False)
        captured: list = []
        try:
            with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
                 patch.object(_state, "PersistentStdioTransport", _fake_transport_factory(captured)), \
                 patch.object(_state, "_probe_requirements", return_value={"missing_env": []}), \
                 patch("kitsune_mcp.tools.shapeshift.shutil.which", return_value=docker):
                result = await shapeshift(srv.id, _ctx(), **kwargs)
        finally:
            from kitsune_mcp.tools._state import _do_shed
            _do_shed()
        return result, captured

    async def test_sandbox_true_wraps_stdio_launch_in_docker(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        result, captured = await self._mount(_srv(), monkeypatch, confirm=True, sandbox=True)
        assert result.startswith("Shapeshifted"), result
        assert captured, "no transport was constructed"
        cmd = captured[0]
        assert cmd[0] == "docker"
        assert "--cap-drop" in cmd
        assert cmd[-3:] == ["npx", "-y", "some-pkg@1.2.3"]

    async def test_sandbox_trust_note_labels_docker(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        result, _ = await self._mount(_srv(), monkeypatch, confirm=True, sandbox=True)
        assert "Docker sandbox" in result

    async def test_without_sandbox_cmd_is_unwrapped(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        result, captured = await self._mount(_srv(), monkeypatch, confirm=True)
        assert result.startswith("Shapeshifted"), result
        assert captured[0] == ["npx", "-y", "some-pkg@1.2.3"]

    async def test_sandbox_without_docker_fails_fast(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        result, captured = await self._mount(_srv(), monkeypatch, docker=None, confirm=True, sandbox=True)
        assert result.startswith("❌")
        assert "Docker" in result
        assert not captured  # no process was launched

    async def test_sandbox_on_http_only_server_fails_with_guidance(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        srv = _srv(source="official", transport="http", install_cmd=[],
                   url="https://mcp.example.com")
        result, captured = await self._mount(srv, monkeypatch, sandbox=True)
        assert result.startswith("❌")
        assert "source" in result  # points at source='local' as the way to force stdio
        assert not captured

    async def test_unsupported_launcher_fails_before_shed(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        srv = _srv(install_cmd=["node", "server.js"])
        result, captured = await self._mount(srv, monkeypatch, confirm=True, sandbox=True)
        assert result.startswith("❌")
        assert "npx/uvx" in result
        assert not captured

    async def test_kitsune_sandbox_all_applies_without_flag(self, monkeypatch):
        monkeypatch.setenv("KITSUNE_SANDBOX", "all")
        result, captured = await self._mount(_srv(), monkeypatch, confirm=True)
        assert result.startswith("Shapeshifted"), result
        assert captured[0][0] == "docker"

    async def test_kitsune_sandbox_community_skips_official(self, monkeypatch):
        monkeypatch.setenv("KITSUNE_SANDBOX", "community")
        srv = _srv(source="official")
        result, captured = await self._mount(srv, monkeypatch)
        assert result.startswith("Shapeshifted"), result
        assert captured[0][0] == "npx"

    async def test_community_gate_message_offers_sandbox(self, monkeypatch):
        """The trust gate should teach the safer path, not just block."""
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        result, _ = await self._mount(_srv(), monkeypatch)  # no confirm → gated
        assert result.startswith("⚠️")
        assert "sandbox=True" in result

    async def test_credential_names_forwarded_into_container(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
        monkeypatch.setenv("SOMEPKG_API_TOKEN", "sk-secret")
        srv = _srv(credentials={"somepkg_api_token": "token"})
        monkeypatch.setenv("KITSUNE_TRUST", "community")  # skip gate; creds declared
        from kitsune_mcp.tools import _state, shapeshift
        from kitsune_mcp.tools._state import _registry
        captured: list = []
        try:
            with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
                 patch.object(_state, "PersistentStdioTransport", _fake_transport_factory(captured)), \
                 patch.object(_state, "_probe_requirements", return_value={"missing_env": []}), \
                 patch("kitsune_mcp.tools.shapeshift.shutil.which", return_value="/usr/bin/docker"):
                result = await shapeshift(srv.id, _ctx(), sandbox=True)
        finally:
            _state._do_shed()
        assert result.startswith("Shapeshifted"), result
        cmd = captured[0]
        idx = cmd.index("SOMEPKG_API_TOKEN")
        assert cmd[idx - 1] == "-e"
        assert not any(a.startswith("SOMEPKG_API_TOKEN=") for a in cmd)
