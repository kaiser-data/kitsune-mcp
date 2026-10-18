# Contributing to Kitsune MCP

Thank you for helping make Kitsune better! This guide gets you to a working dev setup in under 5 minutes.

Questions or ideas? Open an [issue](https://github.com/kaiser-data/kitsune-mcp/issues).

## Quick Setup

```bash
git clone https://github.com/kaiser-data/kitsune-mcp
cd kitsune-mcp
make dev        # install kitsune-mcp, dev deps and docs deps (uv)
make test       # run all tests
make lint       # ruff check + format check
make format     # auto-format with ruff
make docs       # preview the docs site at http://127.0.0.1:8000
```

> **Running pytest directly?** The test config in `pyproject.toml` (`addopts`)
> requires `pytest-timeout`, which is a dev dependency. A bare `uv run pytest`
> fails to start with `unrecognized arguments: --timeout`. Use `make test`, or
> include the dev extra: `uv run --extra dev pytest tests/`.

## Tool Patterns

Tools live in `kitsune_mcp/tools/` and follow this pattern:

```python
@mcp.tool()
async def my_tool(param: str, optional: int = 5) -> str:
    """One-line description. param: what it does."""
    # ... implementation
    return _truncate(result)
```

Rules:
- Return `str` always — FastMCP serializes everything
- Use `_truncate()` on any response that could be large
- Use `_clean_response()` on raw external content
- Update `session["stats"]` for call counts
- Add the tool name to `_BASE_TOOL_NAMES` in `kitsune_mcp/tools/_state.py`,
  and to `_LEAN_TOOL_NAMES` only if it belongs in the default profile

## Transport Patterns

Adding a new transport? Subclass `BaseTransport` in `kitsune_mcp/transport.py`:

```python
class MyTransport(BaseTransport):
    async def execute(self, tool: str, args: dict, config: dict) -> str:
        # connect, call, return str
        ...
```

Add a test in `tests/test_transports.py` with a `respx` or subprocess mock.

## Commit Style

```
feat: add PersistentStdioTransport for hardware servers
fix: handle timeout in StdioTransport._read_response
docs: add hardware.md connect/release guide
test: add test_connect_returns_tool_list
```

## PR Checklist

- [ ] `make test` passes
- [ ] `make lint` passes (zero ruff errors)
- [ ] New tools are in `_BASE_TOOL_NAMES` (and `_LEAN_TOOL_NAMES` if lean)
- [ ] New tools are documented in `docs/tools.md`; `make docs` renders it
- [ ] Tests cover the happy path + at least one error case

## Adding a New Server Integration

If you found a server that works well with Kitsune, open a "New Server" issue:
- Server ID (e.g. `@modelcontextprotocol/server-filesystem`)
- Transport type: `http` or `stdio`
- Any error from `call()` or `shapeshift()` you hit

## Project Structure

```
server.py              # entry point: loads .env, registers tools, prunes to the profile
server_forge.py        # kitsune-forge entry point (all tools)
kitsune_mcp/
  app.py               # the shared FastMCP instance
  tools/               # the MCP tools (discovery, exec, shapeshift, onboarding)
    _state.py          # tool-name sets for the lean and full profiles
  transport.py         # stdio, HTTP/SSE, WebSocket, persistent and Docker transports
  registry.py          # registry clients (official, MCP Registry, Glama, npm, PyPI, Smithery)
  shapeshift.py        # mounting proxied tools, resources and prompts
  credentials.py       # .env handling and credential checks
  guard.py, pins.py    # action guard and version pins
tests/                 # pytest suite
docs/                  # the docs site (MkDocs Material, see mkdocs.yml)
examples/              # demo servers and scenarios
```
