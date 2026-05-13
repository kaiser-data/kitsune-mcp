"""Adapter for shell/terminal MCP servers."""

from kitsune_mcp.adapters import Adapter, _register


class ShellAdapter(Adapter):
    CATEGORY = "shell"
    KNOWN_IDS = frozenset({
        "mcp-server-shell",
        "mcp-shell",
        "terminal-mcp",
        "mcp-server-bash",
    })

    # No setup_hint: shell servers typically need no credentials
    # No infer_args: Rule 2.5 already handles shell_command params


_register(ShellAdapter())
