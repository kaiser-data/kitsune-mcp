"""End-to-end: reload() picks up an edit to a real server's source.

This is Kitsune's core promise, so it runs a real MCP server process instead of
mocks: connect() it, call a tool, rewrite the file, reload(), call again.
"""

import asyncio
import importlib
import shlex
import sys
import textwrap

import pytest
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

_SERVER = textwrap.dedent(
    """
    from mcp.server.mcpserver import MCPServer

    mcp = MCPServer("e2e")


    @mcp.tool()
    {signature} -> str:
        return {expression}


    if __name__ == "__main__":
        mcp.run()
    """
)


@pytest.mark.asyncio
async def test_reload_runs_the_edited_source(tmp_path):
    from kitsune_mcp.session import session

    ss = importlib.import_module("kitsune_mcp.tools.shapeshift")
    call_mod = importlib.import_module("kitsune_mcp.tools.exec")
    server = tmp_path / "server.py"
    server.write_text(_SERVER.format(signature="def answer()", expression=repr("BEFORE-EDIT")))
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(server))}"

    try:
        assert (await ss.connect(command, name="e2e")).startswith("Connected:")
        assert "BEFORE-EDIT" in await call_mod.call("answer", server_id="e2e", arguments={})

        server.write_text(
            _SERVER.format(
                signature="def answer()", expression=repr("AFTER-EDIT-WITH-A-LONGER-STRING")
            )
        )
        out = await ss.reload("e2e")
        assert out.startswith("Reloaded: e2e"), out

        result = await call_mod.call("answer", server_id="e2e", arguments={})
        assert "AFTER-EDIT-WITH-A-LONGER-STRING" in result
        assert "BEFORE-EDIT" not in result
    finally:
        await ss.shiftback(_NoCtx(), kill=False)
        await ss.release("e2e")  # kills and waits, so the loop closes cleanly
        session["connections"].clear()


class _NoCtx:
    class session:  # noqa: N801
        @staticmethod
        async def send_tool_list_changed():
            pass

        @staticmethod
        async def send_resource_list_changed():
            pass

        @staticmethod
        async def send_prompt_list_changed():
            pass


@pytest.mark.asyncio
async def test_client_sees_tools_change_on_reload_and_switch(tmp_path):
    first = tmp_path / "first.py"
    second = tmp_path / "second.py"
    first.write_text(_SERVER.format(signature="def answer()", expression=repr("first")))
    second.write_text(_SERVER.format(signature="def next_answer()", expression=repr("second")))
    notifications = asyncio.Queue()

    async def on_message(message):
        if isinstance(message, types.ToolListChangedNotification):
            notifications.put_nowait(message)

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server"],
        cwd=tmp_path,
        env={"KITSUNE_HOME": str(tmp_path / "kitsune")},
    )
    async with (
        stdio_client(params) as (reader, writer),
        ClientSession(reader, writer, message_handler=on_message) as client,
    ):
        await client.initialize()

        async def call(tool_name, **arguments):
            result = await client.call_tool(tool_name, arguments)
            assert not result.is_error, result
            return result.content[0].text

        async def changed_tools():
            await asyncio.wait_for(notifications.get(), timeout=5)
            return {tool.name: tool for tool in (await client.list_tools()).tools}

        for name, path in (("first", first), ("second", second)):
            command = shlex.join([sys.executable, str(path)])
            assert (await call("connect", command=command, name=name)).startswith("Connected:")

        assert (await call("shapeshift", server_id="first")).startswith("Shapeshifted")
        assert "answer" in await changed_tools()
        assert await call("answer") == "first"

        first.write_text(
            _SERVER.format(signature="def answer(value: int)", expression="str(value)")
        )
        assert (await call("reload", name="first")).startswith("Reloaded:")
        tools = await changed_tools()
        assert tools["answer"].input_schema["properties"]["value"]["type"] == "integer"
        assert await call("answer", value=42) == "42"

        assert (await call("shapeshift", keep=True)).startswith("Shifted back")
        assert "answer" not in await changed_tools()
        assert (await call("release", name="first")).startswith("Released:")

        assert (await call("shapeshift", server_id="second")).startswith("Shapeshifted")
        tools = await changed_tools()
        assert "answer" not in tools
        assert "next_answer" in tools
        assert await call("next_answer") == "second"
        assert (await call("shapeshift")).startswith("Shifted back")
