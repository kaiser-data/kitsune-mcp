"""Sandbox and trust fixes from the 2026-11-22 external reviews.

Codex #2/#3/#4/#11, Grok #4/#5/#16.
"""

import sys

import pytest

from kitsune_mcp.constants import TRUST_LOW
from kitsune_mcp.registry import GlamaRegistry
from kitsune_mcp.transport import DockerTransport, PersistentStdioTransport

# --- Glama listings that install from GitHub are low trust ------------------


def test_glama_github_stdio_entry_is_low_trust():
    srv = GlamaRegistry._to_server_info(
        {
            "name": "thing",
            "namespace": "someone",
            "slug": "thing",
            "repository": {"url": "https://github.com/someone/thing"},
            "attributes": [],
        }
    )
    assert srv.install_cmd == ["npx", "github:someone/thing"]
    assert srv.source in TRUST_LOW


def test_glama_remote_http_entry_keeps_glama_source():
    srv = GlamaRegistry._to_server_info(
        {
            "name": "remote",
            "namespace": "someone",
            "slug": "remote",
            "repository": {"url": "https://github.com/someone/remote"},
            "attributes": ["hosting:remote-capable"],
        }
    )
    assert srv.source == "glama"


# --- docker: tool-call config may tighten the cage, never loosen it ---------


def test_docker_config_cannot_loosen_cage(monkeypatch):
    monkeypatch.delenv("KITSUNE_DOCKER_ALLOW_OVERRIDES", raising=False)
    cmd, _ = DockerTransport("alpine")._build_cmd(
        {"network": "host", "cap_add": ["ALL"], "writable": True, "memory": "64g"}
    )
    assert "--cap-add" not in cmd
    assert "--read-only" in cmd
    assert "host" not in cmd
    assert "64g" not in cmd


def test_docker_config_may_cut_network(monkeypatch):
    monkeypatch.delenv("KITSUNE_DOCKER_ALLOW_OVERRIDES", raising=False)
    cmd, _ = DockerTransport("alpine")._build_cmd({"network": "none"})
    i = cmd.index("--network")
    assert cmd[i + 1] == "none"


def test_docker_overrides_with_user_opt_in(monkeypatch):
    monkeypatch.setenv("KITSUNE_DOCKER_ALLOW_OVERRIDES", "1")
    cmd, _ = DockerTransport("alpine")._build_cmd({"cap_add": ["NET_ADMIN"], "writable": True})
    assert "NET_ADMIN" in cmd
    assert "--read-only" not in cmd


# --- docker env values never appear on the command line ---------------------


def test_docker_env_passed_by_name_only():
    cmd, env = DockerTransport("alpine")._build_cmd({"env": {"API_TOKEN": "s3cret"}})
    assert "s3cret" not in " ".join(cmd)
    assert cmd[cmd.index("-e") + 1] == "API_TOKEN"
    assert env == {"API_TOKEN": "s3cret"}


def test_stdio_pool_key_hides_env_values_but_separates_accounts():
    a = PersistentStdioTransport(["docker", "run", "img"], extra_env={"API_TOKEN": "account-a"})
    b = PersistentStdioTransport(["docker", "run", "img"], extra_env={"API_TOKEN": "account-b"})
    assert "account-a" not in a._pool_key
    assert a._pool_key != b._pool_key


# --- run(): package names cannot be npm/uvx options -------------------------


@pytest.mark.parametrize("package", ["--call=printf hi", "-c", "uvx:--with=evil"])
async def test_run_rejects_option_shaped_package(package):
    from kitsune_mcp.tools import exec as exec_tools

    result = await exec_tools.run(package, "anything")
    assert "package" in result.lower() and "invalid" in result.lower()


# --- bench() and test(level="full") use the sandbox-aware transport ---------


def _exec_module():
    import kitsune_mcp.tools.exec  # noqa: F401

    return sys.modules["kitsune_mcp.tools.exec"]


async def test_bench_uses_transport_for_exec(monkeypatch):
    ex = _exec_module()
    used = {}

    def _for_exec(server_id, srv, explicit_sandbox=False):
        used["for_exec"] = server_id
        raise RuntimeError("stop here")

    def _plain(*a, **k):
        raise AssertionError("bench must not use the uncaged _get_transport")

    class _Srv:
        id = "pkg"
        source = "npm"
        credentials = {}
        transport = "stdio"
        install_cmd = ["npx", "-y", "pkg"]

    async def _get_server(sid):
        return _Srv()

    monkeypatch.setattr(ex._state, "transport_for_exec", _for_exec)
    monkeypatch.setattr(ex._state, "_get_transport", _plain)
    monkeypatch.setattr(ex._state._registry, "get_server", _get_server)

    with pytest.raises(RuntimeError, match="stop here"):
        await ex.bench("pkg", "tool")
    assert used["for_exec"] == "pkg"


async def test_connect_consults_guard(monkeypatch):
    # connect() launching a local command is the feature; a guard policy must
    # still be able to restrict it.
    import kitsune_mcp.tools.shapeshift  # noqa: F401

    ss = sys.modules["kitsune_mcp.tools.shapeshift"]
    seen = {}

    async def _block(server_id, tool, args):
        seen.update(server_id=server_id, tool=tool, args=args)
        return "⛔ Blocked by Kitsune guard"

    def _no_spawn(*a, **k):
        raise AssertionError("connect must not spawn when the guard blocks")

    monkeypatch.setattr(ss, "guard_call", _block)
    monkeypatch.setattr(ss, "PersistentStdioTransport", _no_spawn, raising=False)

    result = await ss.connect("bash -c 'echo hi'")
    assert "Blocked" in result
    assert seen["server_id"] == "connect"
    assert seen["args"]["command"] == "bash -c 'echo hi'"
