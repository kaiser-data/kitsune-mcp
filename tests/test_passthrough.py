"""Mounted tools pass schemas, arguments and results through unchanged (Codex P1).

A real mcp SDK server runs on localhost; its tools are mounted through
Kitsune's shapeshift registration, and an MCP client session talks to
Kitsune itself, so everything below is what a real client would see.
"""

import base64
import socket
import threading
import time
from typing import Literal

import pytest
from pydantic import BaseModel

import kitsune_mcp.transport as tp
from kitsune_mcp import oauth
from kitsune_mcp.app import mcp as kitsune
from kitsune_mcp.shapeshift import _make_proxy_tool, _register_proxy_tools
from kitsune_mcp.transport import HTTPSSETransport

fastmcp = pytest.importorskip("mcp.server.fastmcp")
uvicorn = pytest.importorskip("uvicorn")
from mcp.shared.memory import create_connected_server_and_client_session  # noqa: E402

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class Filters(BaseModel):
    language: Literal["en", "de"] = "en"
    tags: list[str] = []


class Hit(BaseModel):
    title: str
    score: float


class Echoed(BaseModel):
    value: str | None
    was_null: bool


def _downstream(port: int):
    m = fastmcp.FastMCP("downstream", port=port)

    @m.tool(description="Search documents.")
    def find_docs(
        query: str,
        mode: Literal["fast", "deep"] = "fast",
        limit: int | None = None,
        filters: Filters | None = None,
    ) -> Hit:
        lang = filters.language if filters else "none"
        return Hit(title=f"{query}/{mode}/{limit}/{lang}", score=0.5)

    @m.tool()
    def echo(value: str | None = "default") -> Echoed:
        return Echoed(value=value, was_null=value is None)

    @m.tool()
    def fail() -> str:
        raise ValueError("downstream exploded")

    @m.tool()
    def picture() -> fastmcp.Image:
        return fastmcp.Image(data=PNG, format="png")

    @m.tool()
    def code() -> str:
        return "def f():\n\n\n    return  1   \n"

    return m


@pytest.fixture
async def mounted(tmp_path, monkeypatch):
    """Downstream server mounted into Kitsune; yields (open_client, downstream tool list).

    The client session is opened inside each test: its task group must be
    entered and left in the same task, which a yielding fixture cannot do.
    """
    import kitsune_mcp.utils as utils

    monkeypatch.setattr(oauth, "_KITSUNE_DIR", tmp_path / "oauth")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(
        uvicorn.Config(_downstream(port).streamable_http_app(), port=port, log_level="error")
    )
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.02)
    utils._http_client = None
    transport = HTTPSSETransport(f"http://127.0.0.1:{port}/mcp", direct=True)
    tools = await transport.list_tools()
    names, failed = _register_proxy_tools("fixture", tools, transport, {})
    assert failed == [] and set(names) == {"find_docs", "echo", "fail", "picture", "code"}
    try:
        yield (
            lambda: create_connected_server_and_client_session(kitsune._mcp_server),
            {t["name"]: t for t in tools},
        )
    finally:
        for n in names:
            kitsune.remove_tool(n)
        await tp.close_http_sessions()
        if utils._http_client is not None:
            await utils._http_client.aclose()
        utils._http_client = None
        srv.should_exit = True
        thread.join(timeout=10)


async def test_schemas_are_advertised_unchanged(mounted):
    open_client, downstream = mounted
    async with open_client() as client:
        listed = {t.name: t for t in (await client.list_tools()).tools}
        found = listed["find_docs"]
        assert found.inputSchema == downstream["find_docs"]["inputSchema"]
        # The parts the old type-mapping lost:
        props = found.inputSchema["properties"]
        assert props["mode"]["enum"] == ["fast", "deep"]
        assert {"type": "null"} in props["limit"]["anyOf"]
        assert "$defs" in found.inputSchema and "Filters" in found.inputSchema["$defs"]
        assert found.outputSchema == downstream["find_docs"]["outputSchema"]


async def test_nested_enum_and_nullable_arguments_reach_the_server(mounted):
    open_client, _ = mounted
    async with open_client() as client:
        r = await client.call_tool(
            "find_docs",
            {"query": "q", "mode": "deep", "limit": None, "filters": {"language": "de"}},
        )
        assert not r.isError
        assert r.structuredContent == {"title": "q/deep/None/de", "score": 0.5}


async def test_explicit_null_is_forwarded_not_dropped(mounted):
    open_client, _ = mounted
    async with open_client() as client:
        r = await client.call_tool("echo", {"value": None})
        assert r.structuredContent == {"value": None, "was_null": True}
        r = await client.call_tool("echo", {})
        assert r.structuredContent == {"value": "default", "was_null": False}


async def test_invalid_arguments_are_rejected_against_the_real_schema(mounted):
    open_client, _ = mounted
    async with open_client() as client:
        r = await client.call_tool("find_docs", {"query": "q", "mode": "sideways"})
        assert r.isError
        assert "sideways" in r.content[0].text


async def test_downstream_error_keeps_is_error(mounted):
    open_client, _ = mounted
    async with open_client() as client:
        r = await client.call_tool("fail", {})
        assert r.isError is True
        assert "downstream exploded" in r.content[0].text


async def test_image_content_is_relayed(mounted):
    open_client, _ = mounted
    async with open_client() as client:
        r = await client.call_tool("picture", {})
        assert r.content[0].type == "image"
        assert base64.b64decode(r.content[0].data) == PNG


async def test_whitespace_in_text_is_preserved(mounted):
    open_client, _ = mounted
    async with open_client() as client:
        r = await client.call_tool("code", {})
        assert r.content[0].text == "def f():\n\n\n    return  1   \n"


# ---------------------------------------------------------------------------
# Unit-level edge cases
# ---------------------------------------------------------------------------


class _Recorder(tp.BaseTransport):
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute(self, tool, args, config):  # pragma: no cover - not used
        return ""

    async def call_tool(self, tool, args, config):
        self.calls.append((tool, args))
        return self.result


async def test_unusable_schema_falls_back_to_permissive():
    schema = {"name": "t", "inputSchema": {"type": "object", "properties": {"a": {"type": 5}}}}
    tool = _make_proxy_tool("s", schema, _Recorder({"content": []}), {})
    assert tool.parameters == {"type": "object"}


async def test_kitsune_failure_becomes_is_error():
    t = _Recorder("⚠️  outcome unknown")
    tool = _make_proxy_tool("s", {"name": "t", "inputSchema": {"type": "object"}}, t, {})
    r = await tool.run({})
    assert r.isError and "outcome unknown" in r.content[0].text


async def test_paths_are_not_rewritten_for_remote_servers(tmp_path):
    link = tmp_path / "link"
    link.symlink_to(tmp_path)
    t = _Recorder({"content": []})
    tool = _make_proxy_tool("s", {"name": "t", "inputSchema": {"type": "object"}}, t, {})
    await tool.run({"path": str(link)})
    assert t.calls == [("t", {"path": str(link)})]


async def test_malformed_annotations_do_not_cost_the_tool():
    schema = {"name": "t", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": "x"}}
    tool = _make_proxy_tool("s", schema, _Recorder({"content": []}), {})
    assert tool.name == "t"


async def test_annotations_and_title_are_relayed():
    schema = {
        "name": "t",
        "title": "Nice Title",
        "inputSchema": {"type": "object"},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    }
    tool = _make_proxy_tool("s", schema, _Recorder({"content": []}), {})
    assert tool.title == "Nice Title"
    assert tool.annotations.readOnlyHint is True


async def test_name_collision_is_reported_not_hidden():
    from kitsune_mcp.shapeshift import _register_proxy_tools as reg

    tool = {"name": "dup_probe", "inputSchema": {"type": "object"}}
    first, _ = reg("a", [tool], _Recorder({"content": []}), {})
    try:
        names, failed = reg("b", [tool], _Recorder({"content": []}), {})
        assert names == [] and failed[0][0] == "dup_probe"
    finally:
        for n in first:
            kitsune.remove_tool(n)
