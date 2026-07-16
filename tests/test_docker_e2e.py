"""Container E2E: the sandbox really boots MCP servers under Docker.

Everything else in the suite mocks the Docker boundary; these tests prove the
hardened `docker run` wrap actually starts a server, completes the MCP
handshake, and serves tool calls. They need a live daemon plus registry
egress, so they are gated behind KITSUNE_E2E_DOCKER=1 and run in the
dedicated `docker-e2e` CI job (ubuntu runners ship Docker; dev machines may
not). The `real_docker` marker opts them out of conftest's no-host-docker
fixture.
"""
import os

import pytest

from kitsune_mcp.registry import ServerInfo
from kitsune_mcp.tools._state import transport_for_exec
from kitsune_mcp.transport import (
    PersistentStdioTransport,
    _kill_process_tree,
    _process_pool,
    sandbox_wrap_cmd,
)

pytestmark = [
    pytest.mark.real_docker,
    # First run downloads the npm/PyPI package inside the container (base
    # images are pre-pulled by the CI job) — well beyond the 60s default.
    pytest.mark.timeout(240),
    pytest.mark.skipif(
        not os.environ.get("KITSUNE_E2E_DOCKER"),
        reason="set KITSUNE_E2E_DOCKER=1 with a running Docker daemon",
    ),
]


@pytest.fixture(autouse=True)
def _kill_real_pool_processes():
    """Kill the REAL docker processes these tests pool.

    The shared _clear_process_pool fixture only clears the dict — correct for
    mock entries, but here that would leak a live `docker run` client until
    interpreter exit (the container itself exits on stdin EOF thanks to --rm).
    """
    yield
    for entry in list(_process_pool.values()):
        _kill_process_tree(entry.proc)
    _process_pool.clear()


async def test_sandboxed_uvx_time_server_serves_tools():
    """shapeshift(sandbox=True)'s wrap: uvx mcp-server-time inside the cage."""
    cmd = sandbox_wrap_cmd(["uvx", "mcp-server-time"])
    transport = PersistentStdioTransport(cmd)

    tools = await transport.list_tools()
    names = {t["name"] for t in tools}
    assert "get_current_time" in names, f"unexpected tool list: {sorted(names)}"

    result = await transport.execute("get_current_time", {"timezone": "UTC"}, {})
    assert "datetime" in result, f"unexpected tool result: {result[:300]}"


async def test_exec_path_default_wraps_npm_server_in_docker():
    """auto()/call()'s routing: a low-trust npm server is caged by default."""
    srv = ServerInfo(
        id="@modelcontextprotocol/server-everything",
        name="server-everything",
        description="",
        source="npm",
        transport="stdio",
        install_cmd=["npx", "-y", "@modelcontextprotocol/server-everything"],
    )

    transport, note = transport_for_exec(srv.id, srv)
    assert note == ""  # Docker present — no uncaged nudge
    assert transport.install_cmd[:2] == ["docker", "run"]

    tools = await transport.list_tools()
    names = {t["name"] for t in tools}
    assert "echo" in names, f"unexpected tool list: {sorted(names)}"
