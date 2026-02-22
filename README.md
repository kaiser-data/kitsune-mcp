# 🦎 Chameleon MCP

**A single MCP server that becomes any other MCP server on demand.**

[![PyPI](https://img.shields.io/pypi/v/chameleon-mcp?color=blue)](https://pypi.org/project/chameleon-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/chameleon-mcp)](https://pypi.org/project/chameleon-mcp/)
[![CI](https://github.com/kaiser-data/chameleon-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/chameleon-mcp/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/chameleon-mcp)](https://smithery.ai/server/@kaiser-data/chameleon-mcp)

---

## What is Chameleon MCP?

The [Model Context Protocol](https://modelcontextprotocol.io) lets AI agents call external tools — but the standard workflow requires you to know which server you want, configure it in a JSON file, and restart your AI client every time you add or switch one.

Chameleon solves this by acting as a **dynamic proxy**. You configure it once, and from that point Claude can discover, connect to, and call any of 3,000+ MCP servers in the [Smithery registry](https://smithery.ai) — or any npm/pip-installable server — without touching a config file or restarting anything.

The key primitive is `morph()`: when you call `morph("exa/exa")`, Chameleon downloads the server's tool definitions and registers them directly onto itself via FastMCP's live tool API. The tools appear in Claude's tool list as native tools — no wrapper, no extra indirection. When you're done, `shed()` removes them and you're back to the base set.

---

## Quick Start

### 1. Install

```bash
pip install chameleon-mcp
```

### 2. Configure your MCP client

Add Chameleon to your `mcp.json` (Claude Desktop, Claude Code, or any MCP-compatible client):

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp",
      "env": {
        "SMITHERY_API_KEY": "your-key-here"
      }
    }
  }
}
```

A free Smithery API key gives access to 3,000+ verified remote servers. Get one at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys).

**Without a Smithery key:** Chameleon still works — it falls back to running servers locally via `npx` or `uvx`. Discovery is limited to the npm registry.

### 3. Use it

```
search("web search")          → find servers
morph("exa/exa")              → take the form of Exa
web_search_exa(query="...")   → call the tool natively
shed()                        → return to base form
```

---

## How It Works

### The morph pattern

Traditional MCP hubs route calls through a wrapper: `hub.call("exa", "web_search", args)`. Chameleon goes further — it **becomes** the server. After `morph()`, the server's tools are registered directly on Chameleon and callable by name with no extra layers.

```
Before morph():
  Claude → Chameleon (search, inspect, call, morph, shed, ...)

After morph("exa/exa"):
  Claude → Chameleon (search, inspect, call, morph, shed, ...,
                      web_search_exa, find_similar_exa, get_contents_exa)
```

Claude sees the morphed tools exactly as if Exa were configured directly. No prompt overhead, no tool-calling indirection.

### Transport selection

Chameleon picks the right transport automatically based on the server:

| Server type | Transport | How it runs |
|---|---|---|
| Smithery-hosted server | HTTP+SSE | Remote call via `server.smithery.ai` |
| npm package | Stdio | Spawned locally via `npx` |
| pip package | Stdio | Spawned locally via `uvx` |
| Persistent server | Persistent Stdio | Long-lived process, reused across calls |

### Persistent connections

Some servers — audio pipelines, hardware interfaces, stateful services — cannot cold-start on every tool call. `connect()` starts the process once and keeps it in a pool. The same process handles all subsequent calls until you explicitly `release()` it.

---

## Installation Options

### From PyPI (recommended)

```bash
pip install chameleon-mcp
```

### From source

```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp
pip install -e .
```

### Requirements

- Python 3.12+
- `node` / `npx` — required to run npm-based servers locally
- `uvx` (from [uv](https://github.com/astral-sh/uv)) — required to run pip-based servers locally

---

## Configuration

### mcp.json reference

```json
{
  "mcpServers": {
    "chameleon": {
      "command": "chameleon-mcp",
      "env": {
        "SMITHERY_API_KEY": "your-smithery-key"
      }
    }
  }
}
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `SMITHERY_API_KEY` | Recommended | Access to 3,000+ Smithery-hosted servers. Free at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys). |

All other API keys (for individual servers like Exa, Brave, etc.) are stored in `.env` in the working directory via the `key()` tool. They are loaded automatically on startup and passed to servers as needed.

### Storing API keys at runtime

You don't need to pre-configure individual server keys. Use the `key()` tool from inside your AI session:

```
key("EXA_API_KEY", "your-exa-key")
```

This writes the value to `.env` and sets it in the current process immediately. No restart needed.

---

## All Tools

### Discovery

| Tool | Description |
|---|---|
| `search(query, registry, limit)` | Search for MCP servers by task description. Searches Smithery and npm. Returns names, descriptions, and credential requirements. |
| `inspect(server_id)` | Show full details for a server: all tools with schemas, required credentials, connection type, and estimated token cost. |

### Execution

| Tool | Description |
|---|---|
| `call(server_id, tool, args, config)` | Call a single tool on any server without morphing. One-shot — no process is kept alive. |
| `run(package, tool, args)` | Run a tool from any npm or pip package directly by package name. No registry lookup needed. |
| `auto(task, tool, args)` | Full pipeline in one call: search → pick best server → call tool. |
| `fetch(url, intent)` | Fetch a URL and return cleaned, compressed text (~17x smaller than raw HTML). |

### Shape-shifting

| Tool | Description |
|---|---|
| `morph(server_id, config)` | Take the form of a server — its tools are registered directly on Chameleon and callable by name. Replaces the current form if one is active. |
| `shed()` | Drop the current form and remove its tools. Returns to base Chameleon. |

### Persistent connections

| Tool | Description |
|---|---|
| `connect(command, name, inherit_stderr)` | Start a persistent MCP server process. The process stays alive between calls. Probes for missing credentials and prints a setup guide if needed. |
| `release(name)` | Kill a persistent connection and free its resources. |
| `setup(name)` | Step-by-step configuration wizard for a connected server. Shows exactly what is missing and how to fix it. Call repeatedly until all requirements are satisfied. |

### Quality & benchmarking

| Tool | Description |
|---|---|
| `test(server_id, level)` | Run quality checks on a server and return a score from 0–100. Checks connectivity, tool schema validity, response format, and latency. |
| `bench(server_id, tool, args, n)` | Run a tool `n` times and return latency statistics: p50, p95, min, max. |

### Configuration

| Tool | Description |
|---|---|
| `key(env_var, value)` | Save an API key to `.env` permanently and load it into the current session immediately. |
| `skill(qualified_name)` | Fetch a server's Smithery skill prompt and inject it into the conversation context. |

### Status

| Tool | Description |
|---|---|
| `status()` | Show current form, active persistent connections, morphed tools, and token usage statistics. |

---

## Usage Examples

### Discover and use a web search server

```
search("web search")
morph("exa/exa")
key("EXA_API_KEY", "your-key")   ← only needed once, saved to .env
web_search_exa(query="MCP protocol 2025")
shed()
```

### Use a filesystem server from npm

```
morph("@modelcontextprotocol/server-filesystem")
read_file(path="/tmp/notes.txt")
shed()
```

### Run a tool without morphing

```
call("exa/exa", "web_search_exa", {"query": "latest AI news"})
```

### Persistent server with setup guidance

```
connect("uvx voice-mode", name="voice")
# → ⚠️  Setup required before calling 'voice' tools:
# →   Missing env vars:
# →     key("DEEPGRAM_API_KEY", "<your-value>")
# → Call setup('voice') for step-by-step guidance.

setup("voice")                         ← shows next unresolved step
key("DEEPGRAM_API_KEY", "your-key")
setup("voice")                         ← confirms ready

morph("voice-mode")
speak(text="Hello from Chameleon!")
shed()
release("voice")
```

### Full auto pipeline

```
auto("summarize the content at https://example.com/article", "fetch", {"url": "..."})
```

---

## Architecture

```
Claude / AI Agent
       │
       ▼
  Chameleon MCP (server.py — entry point)
       │
       ├── chameleon_mcp/
       │     ├── registry.py    ── SmitheryRegistry + NpmRegistry
       │     ├── transport.py   ── HTTPSSETransport, StdioTransport, PersistentStdioTransport
       │     ├── morph.py       ── live tool registration via FastMCP.add_tool / remove_tool
       │     ├── probe.py       ── env var detection, OAuth, schema creds, setup guide generation
       │     ├── credentials.py ── .env I/O, config resolution
       │     └── tools.py       ── all 16 @mcp.tool() definitions
       │
       ├── SmitheryRegistry  ──► registry.smithery.ai  (3,000+ servers)
       └── NpmRegistry       ──► registry.npmjs.org
```

---

## Roadmap

- [x] Search across Smithery + npm
- [x] morph() / shed() — live tool registration
- [x] HTTP+SSE transport for Smithery-hosted servers
- [x] Stdio transport for local npm/pip servers
- [x] Persistent process pool — connect() / release()
- [x] test() quality scoring (0–100)
- [x] bench() latency benchmarking
- [x] setup() step-by-step configuration wizard
- [x] Readiness probe: env vars, OAuth, schema credentials, local URL reachability
- [ ] WebSocket transport
- [ ] Server health monitoring in status()
- [ ] Smithery registry listing

---

## Contributing

```bash
git clone https://github.com/kaiser-data/chameleon-mcp
cd chameleon-mcp
make dev     # install with dev dependencies
make test    # run the test suite (pytest)
make lint    # ruff check
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for tool patterns, commit style, and PR checklist.

Issues and PRs: [github.com/kaiser-data/chameleon-mcp](https://github.com/kaiser-data/chameleon-mcp)

---

*MIT License · Python 3.12+ · Powered by [FastMCP](https://github.com/jlowin/fastmcp) and [Smithery](https://smithery.ai)*
