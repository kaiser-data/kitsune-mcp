# Installing Kitsune MCP (for AI agents)

Kitsune MCP is a stdio MCP server. It needs no API keys and no Docker.

## 1. Check requirements

- Python 3.12 or newer
- `uv`: check with `uv --version`. If missing: `curl -LsSf https://astral.sh/uv/install.sh | sh` (macOS/Linux) or `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"` (Windows).
- Optional: `node`/`npx` (only needed to mount npm-based community servers), Docker (only used to sandbox community servers).

## 2. Add the server to the MCP settings

```json
{
  "mcpServers": {
    "kitsune": {
      "command": "uvx",
      "args": ["kitsune-mcp"]
    }
  }
}
```

No environment variables are required. `SMITHERY_API_KEY` is optional and only adds Smithery to registry search.

## 3. Verify

Call the `status` tool. It should print `KITSUNE MCP v<version>` and a list of providers (Official MCP Registry, npm + PyPI, Glama).

## Using it

- Test an MCP server you are building: `connect("uv run my_server.py", name="dev")`, then `call(...)`; after editing the code, `reload("dev")` and call again.
- Find and mount a community server: `search("weather")`, then `shapeshift("<server-id>")`.

Docs: https://kaiser-data.github.io/kitsune-mcp/
