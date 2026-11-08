"""Shared test fixtures for Chameleon MCP tests."""

import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx

# Isolate the suite from the developer's real Kitsune state. Every state path
# (credentials .env, state.json, skills.json, OAuth tokens, pins, absorbed
# servers, guard policy) derives from kitsune_home(), and several modules bind
# it at import time — so KITSUNE_HOME must be set here, before any test module
# imports kitsune_mcp. Without this, running the suite wrote test servers,
# skills and keys into ~/.kitsune, where a real Kitsune install picked them up.
_TEST_KITSUNE_HOME = tempfile.mkdtemp(prefix="kitsune-test-home-")
os.environ["KITSUNE_HOME"] = _TEST_KITSUNE_HOME
atexit.register(shutil.rmtree, _TEST_KITSUNE_HOME, ignore_errors=True)
_REAL_KITSUNE_HOME = Path.home() / ".kitsune"

_REAL_WHICH = shutil.which


@pytest.fixture(autouse=True)
def _no_host_docker(request, monkeypatch):
    """Make the suite deterministic regardless of host Docker.

    Sandbox-by-default (transport_for_exec / sandboxed_stdio_transport /
    shapeshift's sandbox pre-flight) branches on shutil.which("docker"): with
    Docker on PATH the launch is docker-wrapped and bypasses the mocked
    _get_transport — so a suite that is green on a docker-less dev machine can
    still fail on a CI runner, which ships Docker. Force the docker lookup to
    None by default; every other executable resolves normally.

    Tests that fake Docker present keep patching shutil.which in their own
    scope (the inner patch wins for its duration); tests that need the real
    daemon opt out with @pytest.mark.real_docker.
    """
    if request.node.get_closest_marker("real_docker"):
        return

    def _which(cmd, *args, **kwargs):
        if cmd == "docker":
            return None
        return _REAL_WHICH(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", _which)


# ---------------------------------------------------------------------------
# Shared subprocess mock helpers (importable or usable as fixtures)
# ---------------------------------------------------------------------------


def make_mock_process(returncode=None):
    """Create a mock asyncio subprocess with working stdin/stdout."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.pid = 99999
    proc.stdin = MagicMock()
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock()
    proc.stdin.close = MagicMock()
    proc.stdout = MagicMock()
    proc.kill = MagicMock()
    proc.wait = AsyncMock(return_value=0)
    return proc


def make_stdout_with_responses(responses: list[dict]):
    """Create a mock stdout that yields JSON-RPC responses one by one."""
    lines = iter((json.dumps(r) + "\n").encode() for r in responses)

    async def readline():
        try:
            return next(lines)
        except StopIteration:
            return b""

    stdout = MagicMock()
    stdout.readline = readline
    return stdout


@pytest.fixture
def mock_process():
    """Pytest fixture: a mock asyncio subprocess (alive by default)."""
    return make_mock_process(returncode=None)


# ---------------------------------------------------------------------------
# Mock subprocess helpers
# ---------------------------------------------------------------------------


class MockProcess:
    """Minimal asyncio subprocess mock for stdio transport tests."""

    def __init__(self, responses: list[dict], returncode: int = 0):
        self._responses = iter(responses)
        self.returncode = returncode
        self.stdin = MockStdin()
        self.stdout = MockStdout(responses)
        self.stderr = MockStdout([])
        self.pid = 12345

    async def wait(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


class MockStdin:
    def write(self, data: bytes):
        pass

    async def drain(self):
        pass

    def close(self):
        pass


class MockStdout:
    def __init__(self, responses: list[dict]):
        self._lines = iter((json.dumps(r) + "\n").encode() for r in responses)

    async def readline(self) -> bytes:
        try:
            return next(self._lines)
        except StopIteration:
            return b""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_smithery_server():
    """Mock Smithery registry responses."""
    server_list = {
        "servers": [
            {
                "qualifiedName": "test-org/test-server",
                "displayName": "Test Server",
                "description": "A test MCP server for unit tests",
                "remote": False,
                "connections": [
                    {"configSchema": {"properties": {"apiKey": {"description": "Your API key"}}}}
                ],
            }
        ]
    }
    server_detail = {
        "qualifiedName": "test-org/test-server",
        "displayName": "Test Server",
        "description": "A test MCP server for unit tests",
        "remote": False,
        "connections": [
            {"configSchema": {"properties": {"apiKey": {"description": "Your API key"}}}}
        ],
        "tools": [
            {
                "name": "do_thing",
                "description": "Does a thing",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
        ],
    }
    with respx.mock:
        respx.get("https://registry.smithery.ai/servers").mock(
            return_value=httpx.Response(200, json=server_list)
        )
        respx.get("https://registry.smithery.ai/servers/test-org/test-server").mock(
            return_value=httpx.Response(200, json=server_detail)
        )
        yield server_list, server_detail


@pytest.fixture
def mock_npm_server():
    """Mock npm registry responses."""
    npm_search = {
        "objects": [
            {
                "package": {
                    "name": "mcp-server-test",
                    "description": "A test npm MCP server",
                    "keywords": ["mcp", "mcp-server"],
                }
            }
        ]
    }
    npm_detail = {
        "name": "mcp-server-test",
        "description": "A test npm MCP server",
        "dist-tags": {"latest": "1.0.0"},
        "versions": {"1.0.0": {"description": "A test npm MCP server"}},
    }
    with respx.mock:
        respx.get("https://registry.npmjs.org/-/v1/search").mock(
            return_value=httpx.Response(200, json=npm_search)
        )
        respx.get("https://registry.npmjs.org/mcp-server-test").mock(
            return_value=httpx.Response(200, json=npm_detail)
        )
        yield npm_search, npm_detail


@pytest.fixture
def stdio_init_responses():
    """Standard init + tool list JSON-RPC responses for a stdio process mock."""
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "hello",
                        "description": "Say hello",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    }
                ]
            },
        },
    ]


@pytest.fixture
def stdio_tool_call_responses():
    """Standard init + tool call JSON-RPC responses."""
    return [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "test", "version": "1.0"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"content": [{"type": "text", "text": "Hello, world!"}]},
        },
    ]


@pytest.fixture(autouse=True)
def _clear_process_pool():
    """Never let a test's mock/leaked pool entry survive to interpreter exit.

    transport.py registers an atexit handler (_kill_all_pool_processes) that
    calls _kill_process_tree() on every entry in the module-global
    _process_pool. Tests populate that pool with MagicMock processes (some with
    a hardcoded pid like 99999). If such an entry survives the test, the atexit
    handler runs the real kill path against a fake pid at shutdown — which on a
    busy Linux CI runner could resolve to a live, unrelated process group. Clear
    the pool after every test so shutdown only ever sees genuine, dead state.
    """
    yield
    try:
        from kitsune_mcp.transport import _process_pool

        _process_pool.clear()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clear_http_sessions():
    """Cached MCP session ids must not leak between tests that reuse an endpoint."""
    from kitsune_mcp.transport import _http_session_locks, _http_sessions

    _http_sessions.clear()
    _http_session_locks.clear()
    yield
    _http_sessions.clear()
    _http_session_locks.clear()


def _script(items: list):
    """respx side_effect that answers each request in turn, echoing its JSON-RPC id.

    Fixtures write responses with a placeholder id; a real server echoes the
    request's id, and the transport matches responses by it.
    """
    queue = list(items)

    def respond(request: httpx.Request):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        req = json.loads(request.content or b"{}")
        if "id" not in req or not item.content:
            return item
        text = item.content.decode()
        lines = []
        for line in text.split("\n"):
            body = line[5:].strip() if line.startswith("data:") else line
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                lines.append(line)
                continue
            if isinstance(msg, dict) and "id" in msg and "method" not in msg:
                msg["id"] = req["id"]
            dumped = json.dumps(msg)
            lines.append(f"data: {dumped}" if line.startswith("data:") else dumped)
        return httpx.Response(item.status_code, text="\n".join(lines), headers=item.headers)

    return respond


@pytest.fixture(autouse=True)
def _clear_registry_search_cache():
    """McpRegistryIO caches per-term searches; tests must not see each other's."""
    from kitsune_mcp.registry import McpRegistryIO

    McpRegistryIO._SEARCH_CACHE.clear()
    yield
    McpRegistryIO._SEARCH_CACHE.clear()
