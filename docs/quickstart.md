# Quickstart

Use a server you never configured. Building your own? See the
[hot-reload tutorial](hot-reload.md).

## 1. Install

=== "Claude Code"

    ```bash
    claude mcp add -s user kitsune -- uvx kitsune-mcp
    ```

=== "Other clients"

    ```json
    {
      "mcpServers": {
        "kitsune": { "command": "uvx", "args": ["kitsune-mcp"] }
      }
    }
    ```

More options: [installation](installation.md).

## 2. Find, mount, use, drop

```python
search("current time")  # 7 registries, no API key needed
shapeshift("mcp-server-time")  # its tools appear in your client
get_current_time(timezone="Asia/Tokyo")
shapeshift()  # tools gone, process stopped
```

Community packages (npm, PyPI) ask for `confirm=True` and run in Docker when
available. See [safety](safety.md).

!!! tip "One step"
    `auto("current time in Tokyo")` does search, mount, call and release.

## Next

- [Hot-reload tutorial](hot-reload.md)
- [Tools reference](tools.md)
- [Agent patterns](agent-patterns.md)
