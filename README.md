<!-- mcp-name: io.github.kaiser-data/kitsune-mcp -->
<div align="center">
  <img src="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/kitsune-logo.png" alt="Kitsune MCP" width="160" />
  <h1>🦊 Kitsune MCP</h1>
  <p><strong>One config entry. Any MCP server on demand. Tools load when needed, release when done.</strong></p>
</div>

[![PyPI](https://img.shields.io/pypi/v/kitsune-mcp?color=blue&label=pypi)](https://pypi.org/project/kitsune-mcp/)
[![npm](https://img.shields.io/npm/v/kitsune-mcp?color=cb3837&label=npm&logo=npm)](https://www.npmjs.com/package/kitsune-mcp)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-8a2be2)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.kaiser-data%2Fkitsune-mcp)
[![Python](https://img.shields.io/pypi/pyversions/kitsune-mcp)](https://pypi.org/project/kitsune-mcp/)
[![CI](https://github.com/kaiser-data/kitsune-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/kitsune-mcp/actions)
[![Coverage](https://codecov.io/gh/kaiser-data/kitsune-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/kaiser-data/kitsune-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/kitsune-mcp)](https://smithery.ai/server/@kaiser-data/kitsune-mcp)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/EYgcf7EX)

---

Kitsune is a gateway MCP server that discovers, installs, and dynamically loads any of 10,000+ MCP servers at runtime. It exposes 5 tools at rest (~500 tokens). Tools from other servers are mounted on demand via `shapeshift()` and released when done — the same retrieval-augmented pattern document-RAG uses for text chunks, applied to tool schemas.

---

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Tool reference](#tool-reference)
- [Server sources](#server-sources)
- [GATEWAY: context bloat detection](#gateway-context-bloat-detection)
- [Performance](#performance)
- [Configuration](#configuration)
- [Agent profiles](#agent-profiles)
- [Security](#security)
- [For MCP developers](#for-mcp-developers)
- [Contributing](#contributing)

---

## Installation

```bash
pip install kitsune-mcp      # recommended
# or
uvx kitsune-mcp              # isolated env via uv, no venv setup
# or
npx kitsune-mcp              # npm (delegates to uvx internally)
```

**Requirements:** Python 3.12+ · `node`/`npx` for npm-based servers · `uvx` from [uv](https://github.com/astral-sh/uv) for PyPI-based servers

Add to your MCP client config — once, globally:

```json
{
  "mcpServers": {
    "kitsune": { "command": "kitsune-mcp" }
  }
}
```

Compatible with Claude Desktop, Claude Code, Cursor, Cline, OpenClaw, Continue.dev, Zed, and any MCP-compatible client.

| Client | Config file |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `~/.claude/mcp.json` |
| Cursor / Windsurf | `~/.cursor/mcp.json` |
| Cline / Continue.dev | VS Code settings / `~/.continue/config.json` |

---

## Quick start

```python
# Find a server
search("web scraping")

# Mount specific tools, use them, release
shapeshift("notion-hosted", tools=["notion-search"])
call("notion-search", arguments={"query": "roadmap"})
shapeshift()                          # context returns to ~500 tokens

# One-shot via auto() — use server_hint for reliable routing
auto("current time in Tokyo", server_hint="mcp-server-time")

# Store a credential, then mount
auth("BRAVE_API_KEY", "sk-...")
shapeshift("brave", tools=["brave_web_search"])
call("brave_web_search", arguments={"query": "MCP protocol 2025"})
shapeshift()
```

---

## How it works

Kitsune is a **dynamic MCP proxy**. `shapeshift(server_id)` connects to a target server via the appropriate transport (stdio subprocess, HTTP, WebSocket), fetches its `tools/list`, and registers each tool as a native FastMCP tool with the exact schema from the server. The AI client receives a `notifications/tools/list_changed` event and sees the new tools as first-class — no wrapper, no indirection.

`shapeshift()` with no args reverses all of it: deregisters the proxy closures, closes the connection, and notifies the client. Context returns to the ~500-token baseline.

### Tool-schema RAG

| Document RAG | Kitsune |
|---|---|
| Index all documents | Registry: 10,000+ servers across 7 sources |
| Query → retrieve relevant chunks | `search("notion")` → ranked candidates with token estimates |
| Inject only relevant content | `shapeshift(server, tools=[...])` → mount only what is needed |
| Model reasons over those chunks | Agent calls those tools natively |
| Evict when done | `shapeshift()` → context returns to baseline |

### Transport selection

| Server source | Transport |
|---|---|
| npm package | `npx <package>` — spawned locally |
| PyPI package | `uvx <package>` — spawned locally |
| GitHub repo | `npx github:user/repo` or `uvx --from git+https://...` |
| Smithery hosted | HTTP + SSE (requires `SMITHERY_API_KEY`) |
| WebSocket | `ws://` / `wss://` |
| Docker | `docker run --rm -i --memory 512m <image>` |

---

## Tool reference

| Tool | Signature | Description |
|---|---|---|
| `status()` | — | Provider auth state, GATEWAY bloat detection, session performance stats |
| `search()` | `query, registry?, compare?` | Search for servers across 7 registries; `compare=True` shows side-by-side token costs |
| `shapeshift()` | `server_id?, tools=[], server_args=[]` | Mount a server's tools (with ID) or unmount current form (no args). `tools=[...]` for surgical load |
| `call()` | `tool_name, arguments` | Invoke a tool; `server_id` inferred when shapeshifted |
| `auth()` | `server_or_var, value?` | Check or set env vars; trigger OAuth 2.1 browser flow for hosted servers |
| `auto()` | `task, server_hint=, arguments=` | One-shot: search → mount → call → return result |

Context overhead at rest: **~500 tokens** for all 5 tools.

> **`auto()` note:** `auto(task, server_hint="server-id")` gives reliable results. Without `server_hint`, routing is best-effort via semantic search and can misfire on ambiguous queries — use `search()` first when unsure.

---

## Server sources

Kitsune searches 7 registries in parallel. No single registry is required.

| Registry | Auth required | `registry=` value |
|---|---|---|
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | None | `official` |
| [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) | None | `mcpregistry` |
| [Glama](https://glama.ai/mcp/servers) | None | `glama` |
| npm | None | `npm` |
| PyPI | None | `pypi` |
| GitHub repos | None | `github:owner/repo` |
| [Smithery](https://smithery.ai) | Free API key | `smithery` |

`search()` fans out across all no-auth registries by default. Add a `SMITHERY_API_KEY` to include Smithery's hosted catalog (HTTP servers, no local install required).

---

## GATEWAY: context bloat detection

`status()` scans your active MCP client configs and reports what other servers are running on every turn:

```
GATEWAY
  ⚠  1 other server(s) active in claude-desktop (~8 extra tools in context)
     Run setup() to harvest their credentials and reduce bloat
  ⚠  1 other server(s) active in claude-code (~8 extra tools in context)
```

To consolidate:

```python
setup()                    # preview — shows what can be harvested
setup(action="harvest")    # extract API keys → ~/.kitsune/.env  (non-destructive)
setup(action="absorb")     # register those servers for shapeshift()
setup(project=True)        # write .claude/mcp.json with only Kitsune (this project)
```

Kitsune never modifies existing configs without explicit confirmation.

---

## Performance

### Token overhead: surgical mount vs full mount

All figures measured live against v0.20.1. Reproduce with `KITSUNE_TOOLS=all python examples/benchmark.py`.

| Server | Tools | Full mount | Surgical example | Surgical tokens | Saved |
|---|---:|---:|---|---:|---:|
| `mcp-server-time` | 2 | 261 | (all tools) | 261 | 0% |
| `mcp-server-git` | 12 | 1,242 | status / diff / log | ~310 | 75% |
| `@modelcontextprotocol/server-memory` | 9 | 2,615 | read_graph / search_nodes | ~580 | 78% |
| `@modelcontextprotocol/server-filesystem` | 14 | 3,207 | read / write / edit | ~690 | 78% |
| `brave` | 8 | 3,612 | brave_web_search | ~450 | 88% |
| `@modelcontextprotocol/server-github` | 26 | 4,229 | search_repositories | ~300 | 93% |
| `notion-hosted` | 14 | 13,707 | search / fetch | ~1,950 | 86% |

### Multi-server compounding

Kitsune's resting cost (~500 tokens) is constant regardless of how many servers are registered. Always-on cost grows linearly with each server added.

| Servers always-on | Always-on tokens/turn | Kitsune tokens/turn | Reduction |
|---:|---:|---:|---:|
| 1 | ~1,500 | 500 | 67% |
| 3 | ~7,700 | 500 | 94% |
| 5 | ~43,700 | 500 | 98.9% |
| 10 | ~58,700 | 500 | 99.2% |

Five connectors always-on (Notion 13.7K + Gmail 8K + Drive 10K + Slack 7K + Calendar 5K = ~43.7K tokens/turn). Over 100 turns: **4.37M tokens of overhead vs ~310K — approximately 14× longer conversations within a 200K context window.**

### Tool-selection accuracy

LLM tool-selection accuracy degrades as the visible tool count grows. Patil et al. 2023 (Gorilla) and Hsieh et al. 2023 both show 20–40% accuracy lift with retrieval-augmented tool selection versus full-catalog exposure. The canonical failure mode is adjacent-name confusion (`read_file` / `read_text_file` / `read_media_file`).

| Tools visible | Typical accuracy |
|---:|---|
| 5–10 | ~98% |
| 20–30 | ~90% |
| 50–70 | ~75% |
| 100+ | ~60% |

Kitsune holds 5 tools at rest; 6–8 during active use.

### Connection latency

Kitsune maintains a persistent process pool — re-attaching to a running server within a session takes 0 ms.

| Transport | Cold start | Warm (pooled) |
|---|---|---|
| HTTP / Smithery hosted | 0–1.4 s | 0.0 s |
| Local stdio via `npx` | 1.7–6.3 s | 0.0 s |
| Local stdio via `uvx` | 1.0–5.2 s | 0.0 s |

---

## Configuration

### Env vars and `.env` files

Kitsune re-reads credentials on every `shapeshift()` and `call()`. Add or update a key mid-session — no restart needed.

Search order: `CWD/.env` → `~/.env` → `~/.kitsune/.env` (last wins).

```bash
# Write a key and activate immediately
auth("BRAVE_API_KEY", "sk-...")    # writes to ~/.kitsune/.env

# Or manage .env directly
echo "BRAVE_API_KEY=sk-..." >> ~/.kitsune/.env
```

### Custom tool surface

Expose only specific tools via `KITSUNE_TOOLS`:

```json
{
  "mcpServers": {
    "kitsune": {
      "command": "kitsune-mcp",
      "env": { "KITSUNE_TOOLS": "shapeshift,call,auth" }
    }
  }
}
```

### Smithery

```json
{ "env": { "SMITHERY_API_KEY": "your-key" } }
```

Get a free key at [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys). Without it, Kitsune is fully functional via npm, PyPI, official registry, and GitHub.

---

## Agent profiles

### Research agent — web search + fetch + memory

```python
shapeshift("brave", tools=["brave_web_search"])                              # ~450 tokens
shapeshift("mcp-server-fetch")                                               # ~289 tokens
shapeshift("@modelcontextprotocol/server-memory",
           tools=["read_graph", "search_nodes"])                             # ~580 tokens
# Peak: ~1,300 tokens vs 6,516 always-on  →  80% reduction
```

### Code agent — filesystem + git

```python
shapeshift("@modelcontextprotocol/server-filesystem",
           tools=["read_file", "write_file", "edit_file"],
           server_args=["/path/to/project"])                                 # ~690 tokens
shapeshift("mcp-server-git",
           tools=["git_status", "git_diff", "git_log"])                     # ~310 tokens
# Peak: ~1,000 tokens vs 4,449 always-on  →  78% reduction
```

### Notes / PM agent — Notion + memory

```python
shapeshift("notion-hosted",
           tools=["notion-search", "notion-append-block-children"])         # ~1,950 tokens
shapeshift("@modelcontextprotocol/server-memory",
           tools=["add_memory", "search_nodes"])                            # ~580 tokens
# Peak: ~2,500 tokens vs 16,322 always-on  →  85% reduction
```

---

## Security

### Trust tiers

| Tier | Sources | Label |
|---|---|---|
| High | `official` (modelcontextprotocol/servers) | `✓ Source: official` |
| Medium | `mcpregistry`, `glama`, `smithery` | `✓ Source: smithery` |
| Community | `npm`, `pypi`, `github` | `⚠ Source: npm (community — not verified)` |

Community servers require `confirm=True` on `shapeshift()` — an explicit acknowledgement before running arbitrary code. Set `KITSUNE_TRUST=community` (via `auth("KITSUNE_TRUST", "community")` or `.env`) to skip the gate globally for servers you already trust.

### Credential handling

- Credentials stored at `~/.kitsune/.env` and `~/.kitsune/oauth/` with mode `0600`
- OAuth 2.1 with PKCE S256 and Dynamic Client Registration (RFC 7591) for hosted servers
- `shapeshift()` warns on missing credentials before any tool call
- `auth("server-id", "logout")` clears cached OAuth tokens

### Process isolation

- stdio servers run as isolated OS subprocesses — no shared memory with Kitsune
- Docker servers run with `--rm -i --memory 512m`
- `fetch()` blocks private IPs, loopback, and non-HTTPS URLs
- Process pool capped at 10 concurrent servers; idle processes evicted after 1 hour
- Install commands validated against shell metacharacter and path-traversal patterns before execution

---

## For MCP developers

The full evaluation suite is available by setting `KITSUNE_TOOLS=all`:

```json
{ "command": "kitsune-mcp", "env": { "KITSUNE_TOOLS": "all" } }
```

Additional tools:

| Tool | What it does |
|---|---|
| `inspect(server_id)` | Schema review + live credential check (✓/✗ per key) + measured token cost |
| `test(server_id)` | Quality score 0–100 across connectivity, schema correctness, and tool behaviour |
| `bench(server_id, tool, args)` | Latency benchmark — p50, p95, min, max |
| `compare(query)` | Side-by-side: token cost, tool count, trust tier, credential status |
| `craft(name, description, params, url)` | Register a custom HTTP-backed tool; `shapeshift()` removes it |

Test your server inside real Claude or Cursor sessions — not in an isolated inspector UI.

---

## Why Kitsune?

In Japanese folklore, the Kitsune (狐) is a fox spirit that shapeshifts between forms, gains new powers, and releases them at will. One fox. Many forms. Total fluidity.

`shapeshift("brave-search")` — the fox takes on a new form, its tools appear natively.
`shapeshift()` — it returns to its true shape, ready to become something else.

> *I am not Japanese, and I use this name with the highest respect for the mythology and culture it comes from.*

---

## Contributing

```bash
make dev     # install with dev dependencies
make test    # pytest
make lint    # ruff
```

Issues and PRs: [github.com/kaiser-data/kitsune-mcp](https://github.com/kaiser-data/kitsune-mcp)

See [CHANGELOG.md](CHANGELOG.md) for version history.

---

*MIT License · Python 3.12+ · Built on [FastMCP](https://github.com/jlowin/fastmcp)*
