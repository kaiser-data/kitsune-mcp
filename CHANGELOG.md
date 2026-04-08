# Changelog

All notable changes to this project are documented here.

---

## [0.7.1] — 2026-04-08

### Changed
- New logo (`logo_protean-mcp.png`) replacing placeholder SVG
- README: removed "a new way" framing; architecture diagrams cleaned of chameleon references
- `docs/architecture.svg`: removed 🦎 emoji from Protean MCP label
- `docs/architecture-forge.svg`: "chameleon-forge" → "protean-forge"

---

## [0.7.0] — 2026-04-08

### Breaking Changes

- **`morph()` renamed to `mount()`** — update any prompts or scripts that call `morph(...)`
- **`shed()` renamed to `unmount()`** — update any prompts or scripts that call `shed()`
- **Package renamed from `chameleon-mcp` to `protean-mcp`** — update `pip install` and `pyproject.toml` references
- **Executables renamed**: `chameleon-mcp` → `protean-mcp`, `chameleon-forge` → `protean-forge`

### Migration Guide

| Before | After |
|---|---|
| `pip install chameleon-mcp` | `pip install protean-mcp` |
| `"command": "chameleon-mcp"` | `"command": "protean-mcp"` |
| `mount("exa")` | `mount("exa")` ← no change |
| `morph("exa")` | `mount("exa")` |
| `shed()` | `unmount()` |

**Deprecated executables** (`chameleon-mcp`, `chameleon-forge`) are kept as aliases in v0.7.x for backward compatibility and will be removed in v0.8.0.

### Added
- `protean-mcp` and `protean-forge` as primary entry point executables
- `chameleon-mcp` and `chameleon-forge` kept as deprecated backward-compat aliases

### Changed
- MCP server display name: `"chameleon"` → `"protean"`
- `pyproject.toml` keywords: removed `"smithery"`, added `"mcp-registry"`
- Package description updated to reflect 7-registry architecture

---

## [0.6.2] — 2026-04-08

### Fixed
- `mount()` cold-start: prefer registry results with cached tool schemas over those without (fixes Exa cold-start failure)
- Live `tools/list` HTTP fetch fallback when registry cache is cold
- Smithery URL format: `/mcp` suffix + `api_key` query param (was using wrong format)
- Doubled Smithery URL when `srv.url` was already a full URL
- Pool staleness: auto-evict subprocesses when `.env` changes mid-session

---

## [0.6.1] — 2026-04-07

### Added
- Frictionless credentials: `.env` auto-reload without restart (tracks mtime changes)
- `call()` is mount-aware: `server_id` optional after `mount()`
- `call()` added to lean profile (7 tools total)
- WebSocket transport support (`ws://`, `wss://`)

---

## [0.6.0] — 2026-04-07

### Added
- `mount()` proxies resources + prompts in addition to tools
- Install command validation (shell injection and path traversal blocked)
- Trust tier warnings in `mount()` output
- Credential warnings at mount-time (not just at `call()`-time)
- `examples/benchmark.py` — reproducible token overhead measurement
- Notification compatibility testing
- Provenance shown in all `search()`/`inspect()`/`mount()`/`call()` output

---

## [0.5.9] — 2026-04-06

### Added
- Refactored into `chameleon_mcp/` package structure
- `OfficialMCPRegistry` — seeds from `modelcontextprotocol/servers` GitHub repo
- `inspect()` stores measured `token_cost` from actual tool schemas
- `status()` sums measured costs for inspected-but-not-mounted servers
- Per-server trust tier tracking

### Fixed
- Registry fan-out priority: official > mcpregistry > glama > github > smithery > npm
- PyPI registry is opt-in only (not in default fan-out — too slow)
