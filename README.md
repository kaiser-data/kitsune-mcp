<!-- mcp-name: io.github.kaiser-data/kitsune-mcp -->
<div align="center">
  <img src="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/kitsune-logo.png" alt="Kitsune MCP" width="160" />
  <h1>🦊 Kitsune MCP</h1>
  <p><strong>The agent harness for MCP.</strong><br/>
  One config entry. Borrow any of 130,000+ servers <em>mid-session</em> — develop live, reach the long tail, try community code contained — then shift back.<br/>
  <em>Session survives.</em></p>
</div>

[![PyPI](https://img.shields.io/pypi/v/kitsune-mcp?color=blue&label=pypi)](https://pypi.org/project/kitsune-mcp/)
[![npm](https://img.shields.io/npm/v/kitsune-mcp?color=cb3837&label=npm&logo=npm)](https://www.npmjs.com/package/kitsune-mcp)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-listed-8a2be2)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.kaiser-data%2Fkitsune-mcp)
[![Python](https://img.shields.io/pypi/pyversions/kitsune-mcp)](https://pypi.org/project/kitsune-mcp/)
[![CI](https://github.com/kaiser-data/kitsune-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/kaiser-data/kitsune-mcp/actions)
[![Coverage](https://codecov.io/gh/kaiser-data/kitsune-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/kaiser-data/kitsune-mcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Smithery](https://smithery.ai/badge/@kaiser-data/kitsune-mcp)](https://smithery.ai/server/@kaiser-data/kitsune-mcp)
[![Glama](https://glama.ai/mcp/servers/kaiser-data/kitsune-mcp/badges/score.svg)](https://glama.ai/mcp/servers/kaiser-data/kitsune-mcp)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/EYgcf7EX)

---

Kitsune is a **runtime MCP proxy**: one always-on gateway your agent uses to reach the rest of the ecosystem. `search` finds a server across 7 registries. `shapeshift(id)` mounts its tools in the current turn. `shapeshift()` drops them. No config edit. No client restart.

```text
search → shapeshift → call → shapeshift()     # reach, use, release
connect → edit → release → connect → call     # MCP REPL (forge profile)
```

**Install for reach and live execution — not for token savings.** Native Tool Search already defers schemas for servers you've configured. Kitsune covers what Tool Search cannot: servers you've never set up, servers you're writing right now, and community packages you want to try without wiring them into `mcp.json` forever.

| | Loop | Why it wins |
|---|---|---|
| **MCP REPL** | edit → `release` → `connect` → `call` | Iterate on your own server without killing the session |
| **Long-tail reach** | `search` → `shapeshift` → `call` | One-offs and obscure APIs with no pre-install |
| **Try-before-you-trust** | `confirm=True` + optional `sandbox=True` + TOFU pins | Community catalog without blind always-on installs |

| Use Kitsune when… | Skip it when… |
|---|---|
| You're building an MCP and need an edit/reload loop | You only need 1–3 trusted servers (configure them natively) |
| A task needs a server that isn't in your config | Every turn hits the same server (keep it always-on) |
| CLI flag-guessing on a long-tail API is too risky | You want cheaper tokens — floor is **~1,358 tokens/turn**, additive on modern clients |
| You want to evaluate community MCP code safely | Unattended prod admin/billing/security keys ([Safety](#safety-model)) |
| You're consolidating a crowded MCP config ([GATEWAY](#gateway-consolidate-always-on-servers)) | You need sub-second first call (cold mount ~1–15s — `prewarm` or always-on) |

Worked high-stakes flows (IAM, IR, audits): [`examples/scenarios/`](./examples/scenarios/). CLI vs MCP accuracy argument lives there too — short version: models nail common CLI commands and fail on the long tail; Kitsune mounts schemas only while you need them.

---

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [Developing an MCP server live](#developing-an-mcp-server-live)
- [How it works](#how-it-works)
- [Tool reference](#tool-reference)
- [Server sources](#server-sources)
- [Safety model](#safety-model)
- [GATEWAY: consolidate always-on servers](#gateway-consolidate-always-on-servers)
- [Performance](#performance)
- [Configuration](#configuration)
- [Mount patterns](#mount-patterns)
- [For MCP developers](#for-mcp-developers)
- [Why Kitsune?](#why-kitsune)
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

**Requirements:** Python 3.12+ · `node`/`npx` for npm-based servers · `uvx` from [uv](https://github.com/astral-sh/uv) for PyPI-based servers · Docker optional (sandbox)

Add once to your MCP client config:

```json
{
  "mcpServers": {
    "kitsune": { "command": "kitsune-mcp" }
  }
}
```

| Client | Config file |
|---|---|
| Claude Desktop (macOS) | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Desktop (Windows) | `%APPDATA%\Claude\claude_desktop_config.json` |
| Claude Code | `~/.claude/mcp.json` |
| Cursor / Windsurf | `~/.cursor/mcp.json` |
| Cline / Continue.dev | VS Code settings / `~/.continue/config.json` |

Also works with OpenClaw, Zed, and any MCP-compatible client.

Lean profile at rest: **6 tools · ~1,358 tokens/turn** (`status`, `search`, `auth`, `shapeshift`, `call`, `auto`) — measured via `python examples/benchmark.py`.

---

## Quick start

**Borrow a server you never configured:**

```python
search("web scraping")
shapeshift("firecrawl", tools=["scrape_url"])   # surgical: one tool, not the whole surface
call("scrape_url", arguments={"url": "https://example.com"})
shapeshift()                                    # drop form — session stays up
```

**Community / long-tail (confirm + optional sandbox):**

```python
search("pdf", registry="glama")
shapeshift("mcp-pdf-tools", confirm=True, sandbox=True)  # Docker cage for npm/PyPI
call("extract_text", arguments={"path": "report.pdf"})
shapeshift()
```

**Hosted (Smithery HTTP — needs a free `SMITHERY_API_KEY`):**

```python
search("exa", registry="smithery")
shapeshift("exa")
call("web_search_exa", arguments={"query": "MCP registry growth 2026"})
shapeshift()
```

**Credentials mid-session:**

```python
auth("BRAVE_API_KEY", "sk-...")
shapeshift("brave", tools=["brave_web_search"])
call("brave_web_search", arguments={"query": "MCP protocol 2026"})
shapeshift()
```

**One-shot** — pass `server_hint` when you know the id (`auto` without it is best-effort and can misfire):

```python
auto("current time in Tokyo", server_hint="mcp-server-time")
```

Full live walkthrough: [`docs/demo-realtime.md`](docs/demo-realtime.md).

---

## Developing an MCP server live

Building an MCP normally means: edit → restart client → lose session → re-test. Kitsune turns that into an **MCP REPL** in one session.

`connect` / `release` are forge tools — enable them:

```json
{
  "mcpServers": {
    "kitsune": {
      "command": "kitsune-mcp",
      "env": { "KITSUNE_TOOLS": "all" }
    }
  }
}
```

```python
connect("uvx --from . my-mcp-server", name="dev")       # start child process
shapeshift("dev")                                       # mount tools → client sees them
call("summarize", arguments={"url": "https://example.com"})

# … edit the tool in your editor …

release("dev")                                          # kill stale process first
connect("uvx --from . my-mcp-server", name="dev")      # fresh code
shapeshift("dev")                                       # remount new schemas live
call("summarize", arguments={"url": "https://example.com"})
```

> **Footgun:** `connect()` pools by command. Calling it again after an edit *without* `release()` returns the old process. Kitsune warns: *"Changed the code? release('dev') first."* Always `release()` before reconnecting.

Local `connect()` targets are untrusted (`confirm` / `KITSUNE_TRUST` apply). Process isolation ≠ security sandbox — see [Safety model](#safety-model). Companion skill: `kitsune-dev`.

---

## How it works

`shapeshift(server_id)` picks a transport (stdio / HTTP+SSE / WebSocket / Docker), connects, fetches `tools/list`, and registers each tool as a native FastMCP tool with the server's real schema. The client gets `notifications/tools/list_changed` and sees first-class tools — no wrapper indirection.

`shapeshift()` with no args deregisters proxies, closes the connection, and returns to the lean baseline.

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"
            srcset="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/architecture-dark.svg"/>
    <img src="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/architecture-light.svg"
         alt="Kitsune MCP architecture" width="700"/>
  </picture>
</div>

**Mental model — tool-schema RAG:** index the ecosystem → `search` retrieves candidates → `shapeshift(..., tools=[…])` injects only what's needed → agent calls natively → `shapeshift()` evicts.

| Source | Transport |
|---|---|
| npm | `npx <package>` (local; optional Docker sandbox) |
| PyPI | `uvx <package>` (local; optional Docker sandbox) |
| GitHub | `npx github:user/repo` or `uvx --from git+…` |
| Smithery hosted | HTTP + SSE (`SMITHERY_API_KEY`) |
| WebSocket | `ws://` / `wss://` |
| Docker image | `docker run …` hardened profile |

---

## Tool reference

**Lean (default)**

| Tool | Signature | Role |
|---|---|---|
| `status()` | — | Current form, pool, GATEWAY scan, session stats |
| `search()` | `query, registry?, compare?` | Fan-out across 7 registries |
| `auth()` | `server_or_var, value?` | Env keys + OAuth 2.1 browser flow / logout |
| `shapeshift()` | `server_id?, tools=[], …` | Mount / unmount; `tools=[…]` surgical; `sandbox=True` / `confirm=True` |
| `call()` | `tool_name, arguments` | Invoke; server inferred when mounted |
| `auto()` | `task, server_hint=, arguments=` | search → mount → call (prefer `server_hint`) |

**Forge** (`KITSUNE_TOOLS=all` or `kitsune-forge`): `connect`, `release`, `prewarm`, `inspect`, `test`, `bench`, `compare`, `craft`, `run`, `fetch`, `setup`, `skill`, `shiftback`, … — see [For MCP developers](#for-mcp-developers).

---

## Server sources

| Registry | Auth | `registry=` |
|---|---|---|
| [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) | — | `official` |
| [registry.modelcontextprotocol.io](https://registry.modelcontextprotocol.io) | — | `mcpregistry` |
| [Glama](https://glama.ai/mcp/servers) | — | `glama` |
| npm | — | `npm` |
| PyPI | — | `pypi` |
| GitHub | — | `github:owner/repo` |
| [Smithery](https://smithery.ai) | Free API key | `smithery` |

`search()` fans out across no-auth registries by default. Add `SMITHERY_API_KEY` for hosted HTTP servers (no local install).

---

## Safety model

Reach into 130k community servers only works if unknown code can be **contained**. Consent, sandbox, and pins are product features — not footnotes.

**Headline controls**

- `confirm=True` (or `KITSUNE_TRUST`) before community / local mounts
- `sandbox=True` or `KITSUNE_SANDBOX=community|all` → hardened Docker for npm/PyPI
- TOFU pins in `~/.kitsune/pins.json` — later malicious publishes don't silently replace what you already ran

### What it protects against

**1. Unverified code without consent**

| Tier | Sources | On mount |
|---|---|---|
| High | `official` | runs directly |
| Medium | `mcpregistry`, `glama`, `smithery` | runs directly |
| Community | `npm`, `pypi`, `github`, local `connect()` | **requires `confirm=True`** |

`KITSUNE_TRUST=community` waives the gate; `status()` warns when that override is active.

> **`confirm=True` is not a human-approval boundary.** The model can set it. Real approval belongs in your client's tool-approval UI.

**2. Shell injection at spawn.** Install commands are validated (no `& ; | $ \` `\n` / `../`) and launched with `create_subprocess_exec` — no shell. Vets the launch line, not what the package does once running.

**3. SSRF.** `fetch()` and registry HTTP are HTTPS-only; private/loopback/non-global hosts blocked; **every redirect hop re-validated** (`KITSUNE_ALLOW_LOCAL_FETCH=1` to opt out).

**4. Credential exposure.** `~/.kitsune/.env` and `oauth/` at mode `0600`; OAuth 2.1 + PKCE S256 + DCR (RFC 7591); missing-cred warnings before calls; `auth(id, "logout")` clears tokens (RFC 7009 where available).

**5. Docker sandbox for untrusted local servers.** `shapeshift("pkg", sandbox=True)` runs npm/PyPI inside: no host FS, `--cap-drop ALL`, read-only rootfs, RAM/PID caps. Cred env vars forwarded by **name** only (`docker -e KEY`) — never in argv, `ps`, or the pool key. First sandboxed mount pulls `node:22-slim` / `uv:python3.13-bookworm-slim`. Filesystem-style servers need host paths and don't fit the sandbox.

### What it does NOT do

- **No sandbox without opt-in.** Default local stdio runs as your user — full FS, network, inherited env. Process isolation ≠ a security boundary.
- **Docker ≠ kernel boundary.** Hardened flags blunt escalation / fork bombs / FS tampering; not a guarantee against container escape. No default non-root / `--network none` (most servers need egress).
- **TOFU ≠ digest pin.** Pins a version, not a content hash. `github:` / `git+` / hand-written `connect()` commands aren't pinned. High assurance: pin by digest or vendor.
- **Tools first.** Resource/prompt proxying is narrower (URI templates skipped; HTTP path differs). "Any server" means tool execution.

**Bottom line:** strong for supervised developer and personal use. **Do not run unattended with production admin, billing, or security credentials in default local mode.** Prefer client approval + `sandbox=True` / `KITSUNE_SANDBOX=community` for untrusted packages.

See guards live: [`docs/demo-realtime.md`](docs/demo-realtime.md#act-3).

---

## GATEWAY: consolidate always-on servers

Optional. Keep daily drivers (GitHub, filesystem, …) native if you prefer. When a config is crowded, `status()` flags other always-on servers so you can collapse to one Kitsune entry and reach them via `shapeshift`:

```
GATEWAY
  ⚠  1 other server(s) active in claude-desktop (~8 extra tools in context)
     Run setup() to harvest their credentials and reduce bloat
```

```python
setup()                    # preview
setup(action="harvest")    # keys → ~/.kitsune/.env (non-destructive)
setup(action="absorb")     # register for shapeshift()
setup(project=True)        # project mcp.json with only Kitsune
```

Never modifies existing configs without explicit confirmation. (`setup` is forge-profile.)

---

## Performance

### Connection latency (what you feel)

Warm pool re-attach within a session: **0 ms**.

| Transport | Cold start | Warm |
|---|---|---|
| HTTP / Smithery | 0–1.4 s | 0.0 s |
| Local `npx` | 1.7–6.3 s | 0.0 s |
| Local `uvx` | 1.0–5.2 s | 0.0 s |

Use `prewarm` (forge) when you know you'll need a server soon.

### Token overhead (secondary)

> Real vs **fully-mounted always-on** or clients **without** Tool Search. On Claude Code 2.1.7+ with native deferral, this is mostly not a Kitsune-specific win. Product pitch is reach + REPL above — not this table.

Every Kitsune figure **includes** the ~1,358 floor. Reproduce: `python examples/benchmark.py`. Methodology: [`docs/benchmarks.md`](docs/benchmarks.md).

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"
            srcset="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/token-cost-dark.svg"/>
    <img src="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/token-cost-light.svg"
         alt="Token cost comparison: always-on vs Kitsune" width="700"/>
  </picture>
</div>

| Server | Always-on | Surgical + floor | vs always-on |
|---|---:|---:|---:|
| `mcp-server-time` | 261 | ~1,619 | always-on cheaper ¹ |
| `mcp-server-git` | 1,242 | ~1,668 | always-on cheaper ¹ |
| `server-memory` | 2,615 | ~1,938 | 26% |
| `server-filesystem` | 3,207 | ~2,048 | 36% |
| `brave` | 3,612 | ~1,808 | 50% |
| `server-github` | 4,229 | ~1,658 | 61% |
| `notion-hosted` | 13,707 | ~3,308 | 76% |

¹ Break-even: Kitsune pays off past one medium server, or two-plus small ones sharing the single floor. Multi-server stack (GitHub+fs+git → Notion suite): **76–93%** vs fully-mounted always-on — same caveat as above.

Fewer visible tools also helps selection reliability (Gorilla / ToolBench); on modern clients Tool Search delivers much of that focus for *configured* servers. Kitsune-specific accuracy bench: not yet — contributions welcome.

---

## Configuration

### Env and `.env`

Re-read on every `shapeshift` / `call` — add keys mid-session, no restart.

Search order: `CWD/.env` → `~/.env` → `~/.kitsune/.env` (last wins).

```bash
auth("BRAVE_API_KEY", "sk-...")    # → ~/.kitsune/.env
```

### Tool surface

```json
{ "env": { "KITSUNE_TOOLS": "shapeshift,call,auth" } }   # subset
{ "env": { "KITSUNE_TOOLS": "all" } }                    # forge
```

### State directory

Default `~/.kitsune/` (credentials, pins, OAuth, session). Relocate with `KITSUNE_HOME=/tmp/kitsune-iso`.

### Sandbox / trust policy

```bash
KITSUNE_SANDBOX=community   # Docker-cage community npm/PyPI mounts
KITSUNE_SANDBOX=all         # cage every local mount
KITSUNE_TRUST=community     # waive confirm gate (status warns)
KITSUNE_REPIN=1             # adopt newer pinned version
```

### Smithery

```json
{ "env": { "SMITHERY_API_KEY": "your-key" } }
```

Free key: [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys). Without it, npm / PyPI / official / GitHub still work.

---

## Mount patterns

Switch forms mid-session — take only the slice you need:

```python
# Research
shapeshift("brave", tools=["brave_web_search"])
shapeshift("mcp-server-fetch")
shapeshift("@modelcontextprotocol/server-memory", tools=["read_graph", "search_nodes"])

# Code
shapeshift("@modelcontextprotocol/server-filesystem",
           tools=["read_file", "write_file", "edit_file"],
           server_args=["/path/to/project"])
shapeshift("mcp-server-git", tools=["git_status", "git_diff", "git_log"])

# Notes
shapeshift("notion-hosted", tools=["notion-search", "notion-append-block-children"])
shapeshift("@modelcontextprotocol/server-memory", tools=["add_memory", "search_nodes"])

shapeshift()   # always drop when the task is done
```

---

## For MCP developers

```json
{ "command": "kitsune-mcp", "env": { "KITSUNE_TOOLS": "all" } }
```

| Tool | Role |
|---|---|
| `connect` / `release` / `prewarm` | MCP REPL + warm pool |
| `inspect(server_id)` | Schemas, live cred check, measured cost |
| `test(server_id)` | Quality score 0–100 |
| `bench(server_id, tool, args)` | Latency p50 / p95 / min / max |
| `compare(query)` | Side-by-side cost, tools, trust, creds |
| `craft(name, description, params, url)` | Register a live HTTP-backed tool |

Test inside real Claude / Cursor sessions — not only an inspector UI. Companion skills: `kitsune-dev`, `kitsune-improve`.

---

## Why Kitsune?

In Japanese folklore the Kitsune (狐) is known for what it can *become*: borrow a form, use that power, cast it off, return to itself.

That is the product loop — reach, use, release; or edit, reload, re-test. One config entry. Long tail one call away. Session intact.

`shapeshift()` is a literal mid-session mount, not a metaphor. Durable advantages: **reach, live development, contained try-before-trust** — not a smaller token bill on clients that already defer schemas.

> *I am not Japanese, and I use this name with the highest respect for the mythology and culture it comes from. The parallel felt too precise to ignore.*

---

## Contributing

```bash
make dev     # install with dev dependencies
make test    # pytest
make lint    # ruff
```

Issues and PRs: [github.com/kaiser-data/kitsune-mcp](https://github.com/kaiser-data/kitsune-mcp) · [CHANGELOG.md](CHANGELOG.md)

---

*MIT License · Python 3.12+ · Built on [FastMCP](https://github.com/jlowin/fastmcp)*
