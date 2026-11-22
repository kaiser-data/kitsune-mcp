"""Trust follows what is launched; release and stderr lifecycle (review 2: Codex #5, #6, #11, #13)."""

import asyncio
import json
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import kitsune_mcp.tools.shapeshift  # noqa: F401  (package re-exports a function of that name)
from kitsune_mcp.registry import ServerInfo
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import PersistentStdioTransport, _PoolEntry, _process_pool

from .conftest import make_mock_process

ss = sys.modules["kitsune_mcp.tools.shapeshift"]


def _srv(source, transport, install_cmd):
    return ServerInfo(
        id="owner/thing",
        name="thing",
        description="",
        source=source,
        transport=transport,
        url="https://thing.example/mcp" if transport == "http" else "",
        install_cmd=install_cmd,
        credentials={},
        tools=[],
        token_cost=0,
    )


@pytest.mark.parametrize(
    "srv, expected",
    [
        (_srv("glama", "http", ["npx", "github:owner/thing"]), "github"),
        (
            _srv("mcpregistry", "stdio", ["uvx", "--from", "git+https://github.com/o/r", "r"]),
            "github",
        ),
        (_srv("glama", "http", []), "glama"),
        (
            _srv("official", "stdio", ["npx", "-y", "@modelcontextprotocol/server-memory"]),
            "official",
        ),
    ],
)
def test_launch_source_reflects_the_command(srv, expected):
    assert _state._launch_source(srv) == expected


def _no_spawn():
    return patch(
        "asyncio.create_subprocess_exec", AsyncMock(side_effect=AssertionError("must not spawn"))
    )


async def test_prewarm_remote_glama_github_needs_confirm(monkeypatch):
    monkeypatch.delenv("KITSUNE_TRUST", raising=False)
    srv = _srv("glama", "http", ["npx", "github:owner/thing"])
    with patch.object(_state._registry, "get_server", AsyncMock(return_value=srv)), _no_spawn():
        out = await ss.prewarm("owner/thing")
    assert "confirm=True" in out and "github" in out


async def test_prewarm_sandbox_true_refuses_uncageable_launcher(monkeypatch):
    srv = _srv("absorbed", "stdio", ["python3", "/project/server.py"])
    with (
        patch.object(_state._registry, "get_server", AsyncMock(return_value=srv)),
        patch.object(_state.shutil, "which", return_value="/usr/bin/docker"),
        _no_spawn(),
    ):
        out = await ss.prewarm("owner/thing", sandbox=True)
    assert out.startswith("❌") and "npx/uvx" in out


async def test_release_does_not_drop_a_replacement_process():
    old, new = make_mock_process(), make_mock_process()
    key = json.dumps(["rel-cmd"], sort_keys=True)
    old_entry = _PoolEntry(
        proc=old, install_cmd=["rel-cmd"], started_at=time.monotonic(), name="rel"
    )
    new_entry = _PoolEntry(
        proc=new, install_cmd=["rel-cmd"], started_at=time.monotonic(), name="rel"
    )
    _process_pool[key] = old_entry

    async def _wait():
        _process_pool[key] = new_entry  # a concurrent call restarted it meanwhile
        await asyncio.sleep(0)
        return 0

    old.wait = _wait
    out = await ss.release("rel")
    assert out.startswith("Released")
    assert _process_pool.get(key) is new_entry


async def test_captured_stderr_is_discarded_not_piped():
    proc = make_mock_process()
    spawn = AsyncMock(return_value=proc)
    with patch("asyncio.create_subprocess_exec", spawn), pytest.raises(RuntimeError):
        # stdout yields nothing, so the handshake fails; we only check the spawn.
        proc.stdout = MagicMock()
        proc.stdout.readline = AsyncMock(return_value=b"")
        await PersistentStdioTransport(["quiet"], inherit_stderr=False)._start_process()
    assert spawn.call_args.kwargs["stderr"] == asyncio.subprocess.DEVNULL


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("https://github.com/o/r/archive/main.tar.gz", "github"),
        ("https://evil.example/github.com/o/r.tar.gz", "npm"),
    ],
)
def test_launch_source_checks_the_url_host(spec, expected):
    assert _state._launch_source(_srv("npm", "stdio", ["uvx", "--from", spec, "r"])) == expected
