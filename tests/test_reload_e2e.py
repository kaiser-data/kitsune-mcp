"""End-to-end: reload() picks up an edit to a real server's source.

This is Kitsune's core promise, so it runs a real MCP server process instead of
mocks: connect() it, call a tool, rewrite the file, reload(), call again.
"""

import importlib
import shlex
import sys
import textwrap

import pytest

_SERVER = textwrap.dedent(
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("e2e")


    @mcp.tool()
    def answer() -> str:
        return "{marker}"


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
    server.write_text(_SERVER.format(marker="BEFORE-EDIT"))
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(server))}"

    try:
        assert (await ss.connect(command, name="e2e")).startswith("Connected:")
        assert "BEFORE-EDIT" in await call_mod.call("answer", server_id="e2e", arguments={})

        server.write_text(_SERVER.format(marker="AFTER-EDIT-WITH-A-LONGER-STRING"))
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
