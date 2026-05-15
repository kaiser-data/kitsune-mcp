<!-- mcp-name: io.github.kaiser-data/kitsune-mcp -->
<div align="center">
  <img src="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/kitsune-logo.png" alt="Kitsune MCP" width="160" />
  <h1>🦊 Kitsune MCP</h1>
  <p><strong>Connectors give your agent brain rot. Kitsune gives it superpowers.</strong><br/>
  10,000+ MCP servers reachable. 5 tools in context. Pick one when you need it. Drop it when you don't.</p>
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

## The 30-second demo

```python
shapeshift("notion-hosted", tools=["notion-search"])   # mount 1 tool (~1,950 tokens)
call("notion-search", arguments={"query": "roadmap"})  # use it
shapeshift()                                           # release → back to ~500 tokens
```

One entry in your MCP config. No restarts. Every server in the ecosystem, on demand.

---

## First run: see what you're paying for

Run `status()` immediately after installing. The GATEWAY section shows what other MCP servers your clients are silently loading on every turn:

```
GATEWAY
  ⚠  1 other server(s) active in claude-desktop (~8 extra tools in context)
     Run setup() to harvest their credentials and reduce bloat
  ⚠  1 other server(s) active in claude-code (~8 extra tools in context)
     Run setup() to harvest their credentials and reduce bloat
```

That overhead sits in your system prompt on every message — whether you use those servers or not. `setup(action="harvest")` extracts their API keys into `~/.kitsune/.env`. `setup(action="absorb")` registers them for `shapeshift()`. Then you can trim your configs down to Kitsune alone.

---

## Brain rot by overbloat

More tools in context means worse decisions. This is not a hunch — it is measured.

Patil et al. 2023 (Gorilla) and Hsieh et al. 2023 both show **20–40% accuracy lift** when tool selection uses retrieval rather than full-catalog exposure. The failure mode is adjacent-name confusion: a model with `read_file`, `read_text_file`, and `read_media_file` all visible will call the wrong one. A model that sees only `read_file` cannot.

```
Tools visible    Tool-selection accuracy
─────────────────────────────────────────
5–10             ~98%
20–30            ~90%
50–70            ~75%
100+             ~60% or lower
```

Five always-on connectors (Notion, Gmail, Drive, Slack, Calendar) puts **~130 tools** in front of the model every turn. Kitsune keeps it at 5 at rest, and 6–8 when you are actively working.

---

## Measured savings

### Surgical mount vs full mount (measured live, v0.20.1)

| Server | Tools | Full mount | Surgical example | Surgical tokens | Saved |
|---|---:|---:|---|---:|---:|
| `mcp-server-time` | 2 | 261 | (both tools) | 261 | 0% |
| `mcp-server-git` | 12 | 1,242 | status / diff / log | ~310 | 75% |
| `@modelcontextprotocol/server-memory` | 9 | 2,615 | read / search | ~580 | 78% |
| `@modelcontextprotocol/server-filesystem` | 14 | 3,207 | read / write / edit | ~690 | 78% |
| `brave` (search) | 8 | 3,612 | brave_web_search | ~450 | 88% |
| `@modelcontextprotocol/server-github` | 26 | 4,229 | search_repositories | ~300 | **93%** |
| `notion-hosted` | 14 | 13,707 | search / fetch | ~1,950 | 86% |

### Savings compound with each server added

Kitsune rests at ~500 tokens regardless of how many servers are registered behind it. Always-on cost grows with every server you add.

| Servers always-on | Always-on tokens/turn | Kitsune tokens/turn | Saved |
|---:|---:|---:|---:|
| 1 | ~1,500 | 500 | 67% |
| 3 | ~7,700 | 500 | 94% |
| 5 | ~43,700 | 500 | **98.9%** |
| 10 | ~58,700 | 500 | **99.2%** |
| 20 | ~130,000 | 500 | **99.6%** |

Over 100 turns with five connectors: **4.37M tokens of overhead vs ~310K.** That is ~14× longer conversations inside a 200K context window before you hit the limit. Before you upgrade your plan, check whether you are just paying for connectors you forgot were on.

---

## Kitsune is RAG for MCP servers

The same retrieval-augmented pattern that document-RAG uses for text — applied to tool schemas.

| Document RAG | Kitsune (tool RAG) |
|---|---|
| Index all your docs | Registry: 10,000+ servers across 7 sources |
| Query → retrieve top-k chunks | `search("notion")` → ranked candidates |
| Embed retrieved chunks in context | `shapeshift(server, tools=[...])` → mount |
| Model reasons over those chunks | Agent calls those tools natively |
| Evict when done | `shapeshift()` → context returns to baseline |

You never load what you do not need. The model never sees what it should not pick from.

---

## 10,000+ reach, 5-tool context

One `kitsune-mcp` entry in your config unlocks any of these on demand — no config edits, no restart:

| Category | Example servers | Key needed |
|---|---|---|
| Web search | Brave, Exa, Linkup | Free API keys |
| Web scraping | Firecrawl, ScrapeGraph | Free tiers |
| Code & repos | GitHub (26 tools) | Free GitHub token |
| Productivity | Notion, Linear, Slack | Workspace keys / OAuth |
| Google | Maps, Gmail, Drive, Calendar | GCP key / OAuth |
| Memory | Mem0, knowledge graphs | Free tiers |
| No key required | Filesystem, Git, weather, finance | — |

The context cost for all of them combined, while idle: **~500 tokens**.

---

## Quickstart

```bash
pip install kitsune-mcp
```

Add once to your MCP client config — globally or per project:

```json
{ "mcpServers": { "kitsune": { "command": "kitsune-mcp" } } }
```

Works with Claude Desktop, Claude Code, Cursor, Cline, OpenClaw, Continue.dev, Zed, and any MCP-compatible client.

### Three patterns

```python
# 1. One-shot — known server, single call
auto("current time in Tokyo", server_hint="mcp-server-time")
# server_hint is recommended; auto() without it still routes but less reliably

# 2. Multi-call agentic loop — hold the mount, run several calls
shapeshift("@modelcontextprotocol/server-filesystem",
           tools=["read_file"], server_args=["/path"])
call("read_file", arguments={"path": "/path/notes.md"})
shapeshift()

# 3. Surgical sub-server mount — one tool from a 14-tool server
shapeshift("notion-hosted", tools=["notion-search"])
call("notion-search", arguments={"query": "roadmap"})
shapeshift()
```

### Side-by-side with existing servers (Claude Code)

```bash
# Kitsune-only project — 5 tools, clean context
mkdir ~/projects/kitsune-session
echo '{"mcpServers":{"kitsune":{"command":"kitsune-mcp"}}}' \
  > ~/projects/kitsune-session/.claude/mcp.json
cd ~/projects/kitsune-session && claude

# Standard session in another terminal — unchanged
cd ~/projects/other && claude
```

---

## The 5-tool surface

| Tool | Purpose |
|---|---|
| `status()` | Provider auth, GATEWAY bloat detection, session performance stats |
| `search(query, registry?, compare?)` | Retrieve candidate servers across 7 registries |
| `shapeshift(server_id, tools=[], server_args=[])` | Mount tools (surgical with `tools=`). No args = unmount. |
| `call(tool_name, arguments)` | Invoke a mounted tool |
| `auth(server_or_var, value?)` | Check / set env vars and OAuth 2.1 flows |
| `auto(task, server_hint=, arguments=)` | One-shot search → mount → call |

Overhead at rest: **~500 tokens**. Each mount adds only what you load — `tools=["web_search"]` is ~450 tokens, not 3,612.

---

## Speed & pooling

Kitsune keeps a persistent process pool. Once a server starts, re-attaching within the session is instant.

| Transport | Cold start | Warm (pooled) |
|---|---|---|
| HTTP / Smithery hosted | 0–1.4 s | 0.0 s |
| Local stdio via `npx` | 1.7–6.3 s | 0.0 s |
| Local stdio via `uvx` | 1.0–5.2 s | 0.0 s |

`shapeshift("brave-search")` the second time costs nothing — the process is already running.

---

## Specialized agent profiles

Token figures are measured, not estimated. Reproduce with `KITSUNE_TOOLS=all python examples/benchmark.py`.

### Research agent — web + fetch + memory

```python
shapeshift("brave", tools=["brave_web_search"])          # ~450 tokens
shapeshift("mcp-server-fetch")                           # ~289 tokens
shapeshift("@modelcontextprotocol/server-memory",
           tools=["read_graph", "search_nodes"])          # ~580 tokens
# Peak: ~1,300 tokens vs 6,516 always-on  →  80% saved
```

### Code agent — filesystem + git

```python
shapeshift("@modelcontextprotocol/server-filesystem",
           tools=["read_file", "write_file", "edit_file"])  # ~690 tokens
shapeshift("mcp-server-git", tools=["git_status","git_diff","git_log"])  # ~310 tokens
# Peak: ~1,000 tokens vs 4,449 always-on  →  78% saved
```

### Notes / PM agent — Notion + memory

```python
shapeshift("notion-hosted", tools=["notion-search", "notion-append-block-children"])
shapeshift("@modelcontextprotocol/server-memory", tools=["add_memory","search_nodes"])
# Peak: ~2,500 tokens vs 16,322 always-on  →  85% saved
```

---

## FAQ

**Will Kitsune let me use a smaller Claude plan?**
It does not change message rate limits, but it extends each conversation roughly 14× in context budget. Before you upgrade your plan, check whether you are just paying for connectors you forgot were on.

**Does `auto()` always pick the right server?**
`auto(task, server_hint="server-id")` is reliable. `auto()` without a hint routes by semantic search and works well for common tasks, but can misfire on ambiguous queries. Use `search()` first when you are unsure.

**Is my data sent anywhere?**
Tool calls are forwarded to the target MCP server — the same server you would call directly. Kitsune relays the call; it does not inspect or store the content. OAuth tokens are stored locally at `~/.kitsune/oauth/` with mode `0600`.

**Can I keep my existing servers and add Kitsune?**
Yes. Kitsune never touches your other configs. Add it alongside; the GATEWAY section will then show you exactly what those servers are costing.

---

## For MCP developers

The full evaluation suite is available via `KITSUNE_TOOLS=all`:

```json
{ "command": "kitsune-mcp", "env": { "KITSUNE_TOOLS": "all" } }
```

Additional tools: `inspect` (schema + credential check), `test` (quality score 0–100), `bench` (p50/p95 latency), `craft` (register a custom HTTP-backed tool), `compare` (side-by-side token cost table). See [CHANGELOG.md](CHANGELOG.md) for the full list.

---

## Server sources

| Registry | Auth | `registry=` value |
|---|---|---|
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | None | `official` |
| [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) | None | `mcpregistry` |
| [Glama](https://glama.ai/mcp/servers) | None | `glama` |
| npm | None | `npm` |
| PyPI | None | `pypi` |
| GitHub repos | None | `github:owner/repo` |
| [Smithery](https://smithery.ai) | Free API key | `smithery` |

---

## Why Kitsune?

In Japanese folklore, the Kitsune (狐) is a fox spirit that shapeshifts between forms, gains new powers, and releases them at will. One fox. Many forms. Total fluidity.

`shapeshift("brave-search")` — the fox takes on a new form.
`shapeshift()` — it returns, ready to become something else.

> *I am not Japanese, and I use this name with the highest respect for the mythology and culture it comes from.*

---

## Contributing

```bash
make dev     # install with dev dependencies
make test    # pytest
make lint    # ruff
```

Issues and PRs welcome: [github.com/kaiser-data/kitsune-mcp](https://github.com/kaiser-data/kitsune-mcp)

---

*MIT License · Python 3.12+ · Built on [FastMCP](https://github.com/jlowin/fastmcp)*
