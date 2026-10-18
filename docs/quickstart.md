# Quickstart

Your first borrowed server in two minutes. If you are here to iterate on your
own MCP server, go to the [hot-reload tutorial](hot-reload.md) instead.

## 1. Install

=== "Claude Code"

    ```bash
    claude mcp add -s user kitsune -- uvx kitsune-mcp
    ```

=== "Any other client"

    Add this to your client's MCP config (Claude Desktop, Cursor, Windsurf,
    Cline, Zed, …):

    ```json
    {
      "mcpServers": {
        "kitsune": { "command": "uvx", "args": ["kitsune-mcp"] }
      }
    }
    ```

Then start a new session. More options, including pip and npx, are on the
[installation page](installation.md).

## 2. Find a server

Ask your agent, or call the tool yourself:

```python
search("current time")
```

`search()` covers 7 registries: the official servers repo, the MCP Registry,
Glama, npm, PyPI, GitHub and Smithery. No API key is needed; Smithery's
hosted servers need a free key, see [configuration](configuration.md).

## 3. Mount it

```python
shapeshift("mcp-server-time")
```

Its tools now appear in your client as native tools. Packages from npm or PyPI
are community code: Kitsune asks you to repeat the call with `confirm=True`
and runs them in a hardened Docker container when Docker is available. See
[safety](safety.md).

Mount only the tools you need with `tools=[...]`:

```python
shapeshift("mcp-server-time", tools=["get_current_time"])
```

## 4. Use it

```python
get_current_time(timezone="Asia/Tokyo")
```

## 5. Drop it

```python
shapeshift()
```

The tools disappear, the process stops, and your session carries on.

!!! tip "One-shot alternative"
    `auto("current time in Tokyo", server_hint="mcp-server-time")` searches,
    mounts, calls and releases in one step.

## Next steps

- [Hot-reload tutorial](hot-reload.md): let your agent test its own MCP server
- [Tools reference](tools.md): every tool and its parameters
- [Agent patterns](agent-patterns.md): recipes that combine the tools
