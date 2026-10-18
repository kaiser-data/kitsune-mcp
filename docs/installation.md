# Installation

Kitsune is one MCP server. Add it to your client once; everything else
happens through its tools.

**Requirements:** Python 3.12+ and [uv](https://docs.astral.sh/uv/). `node`
and `npx` for npm-based servers. Docker is optional and cages community
servers.

## Add it to your client

=== "Claude Code"

    ```bash
    claude mcp add -s user kitsune -- uvx kitsune-mcp
    ```

    `-s user` makes it available in every project. Use `-s project` to
    write it to this project's `.mcp.json` instead.

=== "Claude Desktop"

    Edit `claude_desktop_config.json` (macOS:
    `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

    ```json
    {
      "mcpServers": {
        "kitsune": { "command": "uvx", "args": ["kitsune-mcp"] }
      }
    }
    ```

    Restart Claude Desktop.

=== "Cursor"

    Edit `~/.cursor/mcp.json`, or `.cursor/mcp.json` in your project:

    ```json
    {
      "mcpServers": {
        "kitsune": { "command": "uvx", "args": ["kitsune-mcp"] }
      }
    }
    ```

=== "Other clients"

    Windsurf, Cline, Zed and any other MCP client take the same entry:

    ```json
    {
      "mcpServers": {
        "kitsune": { "command": "uvx", "args": ["kitsune-mcp"] }
      }
    }
    ```

## Other ways to run it

=== "pip"

    ```bash
    pip install kitsune-mcp
    ```

    Then use `"command": "kitsune-mcp"` with no `args`.

=== "npx"

    ```bash
    npx kitsune-mcp
    ```

    The npm package delegates to `uvx`, so uv is still required.

=== "WebSocket transport"

    ```bash
    pip install "kitsune-mcp[ws]"
    ```

    Adds the `websockets` package for `ws://` and `wss://` servers. See
    [transports](transports.md).

## Check that it works

Start a new session and ask your agent to call `status()`. It lists the
registries Kitsune can reach and the tools it registered: 9 in the default
lean profile. To turn on every tool, set `KITSUNE_TOOLS=all`; see
[tool profiles](tools.md#tool-profiles).

## Next

- [Hot-reload tutorial](hot-reload.md): let your agent test the server it's
  building
- [Quickstart](quickstart.md): borrow a server you never configured
