# Changelog

All notable changes to this project are documented here.

---

## [0.15.0] — 2026-05-09

### Fixed — `auto()` arg inference and routing (continued from v0.14.0)

- **Issue #1 fixed — optional search params now filled.** Many Smithery servers declare all params as optional (`required=[]`) but still reject calls without the primary query argument. `_infer_args_from_task` now fills the first `SEARCH_PARAM_NAMES` property (`query`, `q`, `text`, etc.) even when `required` is empty, preventing `query=undefined` errors on `web_search_exa` and similar tools.
- **Issue #3 continued — `"current"` context queries blocked.** Added `"current"`, `"latest"`, `"today"`, `"now"` to `_NL_STARTERS` so `auto("current time in Berlin")` returns `{}` for `timezone` instead of forwarding the full phrase.
- **Path params protected.** New Rule 2a: `path`/`file`/`directory` params are never filled unless the task string looks like a filesystem path (`/…`, `~/…`, `./…`). Prevents `auto("web search for X")` from routing to `mcp-server-git` and calling `search_files(path="web search for X")`.
- **Issue #4 fully fixed — `onboard()` added to lean profile.** `onboard` is now in `_LEAN_TOOLS` so the `auto("onboard") → "call it directly → onboard()"` redirect actually works. Also distinguishes lean vs forge tool names in the redirect message.

### Testing
- Updated `test_auto_args.py` and `test_tool_surface.py` to reflect new behavior.
- Total: **481 tests** (was 480).

---

## [0.14.0] — 2026-05-09

### Fixed — `auto()` routing

- **`_simple_search` now does word-by-word matching** instead of full-string substring matching. `search("what time is it in Tokyo")` now returns `mcp-server-time` because "time" appears in its name. Previously only Smithery (server-side full-text) found anything for NL queries; official/McpRegistry/Glama/npm all returned zero results, so `auto()` routed to random Smithery HTTP servers. (Closes issues #2 and #1.)
- **`auto()` extracts keywords before searching**. Raw NL task `"what time is it in Tokyo"` → search query `"time Tokyo"`. Official registry now surfaces `mcp-server-time` at rank #1. Fallback to raw task if keyword extraction strips everything.
- **`_infer_args_from_task` refuses to forward NL sentences to structured params.** New rule: if the task starts with a question word (`what`, `how`, `where`, …) AND the required param is a structured identifier (`timezone`, `currency`, `language`, `city`, …), return `{}` instead of forwarding the full sentence verbatim. `get_current_time` no longer receives `timezone: "what time is it in Tokyo"`. (Closes issue #3.)
- **`_infer_args_from_task` correctly fills search-like and QA params.** `query`, `q`, `text`, `prompt`, `user_question`, etc. are always filled unconditionally — these are payload params that expect free text. Multiple required string params → `{}` (ambiguous; let LLM supply explicit args).
- **`auto()` guards against built-in Kitsune tool names.** `auto("onboard")` now returns a redirect message instead of searching the registry for an external server named "onboard". (Closes issue #4.)
- **`status()` verifies Smithery API key liveness.** A 3-second ping to `registry.smithery.ai` distinguishes "key set — verified ✓", "key set but INVALID", and "could not verify". (Closes issue #5.)

### Testing
- 23 new tests in `tests/test_v014_fixes.py`.
- Total: **480 tests** (was 457).

---

## [0.13.0] — 2026-05-09

### Security
- **SSRF via redirect blocked** — `_ssrf_safe_request()` validates each redirect hop against `_is_safe_url()`. `fetch()` and `craft()` endpoint proxies now use it, closing the open-redirect bypass (a public URL redirecting to `169.254.169.254` was previously followed without checks).
- `_is_safe_url` moved from `onboarding.py` to `utils.py` — canonical, single definition, no circular-import risk.

### Fixed
- **Probe temp dirs now cleaned up** — `inspect()` wraps the probe subprocess in `try/finally` and calls `shutil.rmtree(tmpdir)` after the probe exits. Previously every `inspect()` call leaked a `kitsune-probe-*` temp dir.
- **SSE multi-line events** — `_parse_sse()` now collects all `data:` lines per event (separated by blank lines) before parsing, matching RFC 6455. Servers that spread a large JSON response across multiple `data:` lines are now handled correctly.
- **`datetime.utcnow()` removed** — replaced with `datetime.now(UTC)` in `onboarding.py` (Python 3.12+ deprecation).
- **PyPI HTML search** — switched from CSS class-name regex (`package-snippet__name`) to stable `/project/<name>/` link extraction. Less fragile across PyPI redesigns.

### Performance
- **NpmRegistry + PyPIRegistry now cache responses** — 60 s TTL for search, 300 s for `get_server`. Cold `MultiRegistry` calls no longer re-fetch npm/PyPI on every search miss.
- `MultiRegistry.bust_cache()` propagates the clear to individual registry caches.

### UX
- **`status()` shows crafted tools** — persistent `crafted_tools` are now listed in the CRAFTED TOOLS section with method + URL, so users know what survived restart.
- **`MCP_CLIENT_INFO.version` reflects actual package version** — reads from `importlib.metadata` instead of being hardcoded to `"1.0.0"`.

### Testing
- 28 new tests in `tests/test_audit_fixes.py` covering: SSRF redirect guard, SSE multi-line parsing, probe tmpdir cleanup, `_restore_crafted_tools`, `bench()`, `test()` quality scorer, `run()`, crafted tools in `status()`, PyPI link-based search, NpmRegistry/PyPIRegistry caching.
- Total: **457 tests** (was 429).

---

## [0.12.0] — 2026-05-09

### Security
- **SSRF protection in `fetch()` and `craft()`** — both tools now block requests to private/loopback addresses (127.x, 10.x, 192.168.x, 169.254.x, localhost), consistent with the existing guard in `skill()`. Override with `KITSUNE_ALLOW_LOCAL_FETCH=1` for local development.

### New Features
- **Parameter aliasing in proxy tools** — `from_timezone` is silently remapped to `source_timezone`, `to_timezone` to `target_timezone`, `from`/`to` to `source`/`target`, `src`/`dst`/`dest` to `source`/`target`, and language variants (`from_lang`, `to_lang`, `input_lang`, `output_lang`). Applied only when the alias key is absent from the tool schema. Closes #9.
- **Shapeshifted tool registration failures now surface** — failed `mcp.add_tool()` calls are no longer silently swallowed; they appear as `⚠️ N tool(s) failed to register: name: error` in the `shapeshift()` output.
- **Session persistence** — `crafted_tools` and `connections` metadata (minus PIDs and `started_at`) now survive server restarts in `~/.kitsune/state.json`. Explored history is capped at 100 entries. Crafted tools are re-registered with FastMCP on startup.
- **`auto()` prefers official stdio servers over Smithery HTTP** — `mcp-server-time` (official, stdio, free) now beats a Smithery HTTP equivalent when both are returned by search. Ties broken by `not (transport == "stdio")` as the 4th sort key.

### CI / Infrastructure
- **mcp-publisher bumped to v1.7.6** — fixes silent MCP Registry publish failures since v0.9.0 (OIDC audience binding changed in v1.7.6).
- **`actions/checkout` → v6**, **`actions/setup-python` → v6** (Dependabot #1, #2).

### Reliability
- `_registry_lock` (`asyncio.Lock`) prevents concurrent shapeshifts from leaving orphaned tools. Without it, two concurrent shapeshifts could interleave shed + register, leaving both servers' tools mounted while session only tracked one.
- `atexit` handler persists session state before killing pool processes on interpreter exit.
- Probe processes from `inspect()`/`compare()` are killed immediately after `list_tools()` returns.
- Registry paginated fetch no longer caches empty/partial results on transient failures.
- `shiftback(kill=True)` no longer mass-kills unrelated `connect()` sessions when pool key is missing — warns instead.
- `source='local'` on HTTP-only Smithery servers returns a clear error before shedding the current form.
- `call()` uses the shapeshifted session's pooled transport instead of re-resolving from registry.

### UX
- `auto()` surfaces registry fetch failures instead of silently returning "no tools listed".
- `compare()` shows `—` instead of `?` for unknown values; error labels are human-readable.
- `search()` warning uses actual exception class per registry.
- `shapeshift()` output includes wall-clock timing for cold npm installs.
- Filesystem server shapeshift proactively hints about `server_args` when no allowed dirs are passed.
- macOS `/tmp` → `/private/tmp` symlink resolved in proxy args.
- httpx INFO logging suppressed by default (`KITSUNE_DEBUG_HTTP=1` to re-enable).

### Correctness
- `tokens_sent` tracked in `StdioTransport`, `PersistentStdioTransport`, `WebSocketTransport`.
- `key()` masks secret value in response; `.env` written with `0o600` permissions.
- `_infer_args_from_task` returns `{}` when tool has multiple required string params.
- `__version__` exposed via `importlib.metadata`.

### Testing
- `tests/test_ssrf.py` — SSRF guard tests for `fetch()` and `craft()`.
- `tests/test_param_aliases.py` — alias normalization logic tests.
- `tests/test_session_persistence.py` — crafted_tools / connections / explored persistence tests.
- 6 integration tests for lean vs forge tool surface.
- `_registry_lock` concurrency tests.
- `tokens_sent` tests for all three previously-broken transports.

---

## [0.11.0] — 2026-05-04

Provider-aware onboarding — closes the rest of issue #8. Configure providers once up front, explore freely. Hermes-style agents now reach a working tool call in ≤3 steps with zero API keys.

### Added
- **`onboard()` tool** — first-run wizard. Shows provider auth state, recommends 5 zero-config servers (`mcp-server-time`, `@modelcontextprotocol/server-memory`, `mcp-server-fetch`, `@modelcontextprotocol/server-filesystem`, `@upstash/context7-mcp`), and ends with a 3-step verification flow. Optional Smithery upgrade path with a direct link to API key setup. (Issue #8 acceptance: "new user reaches working tool call in ≤3 steps".)
- **Multi-provider fallback in `auto()`** — when no `server_hint` is pinned and the chosen provider returns auth-failure response (`"Auth failed"`, `401`, `unauthorized`, etc.), `auto()` walks through the remaining `search()` candidates whose creds it can satisfy. The user asked for "web search", not Provider X.
- **Argument inference in `auto()`** — when `auto()` implicit-selects a tool but caller passed no `arguments`, fills the primary string param (`query`/`q`/`prompt`/`text`/etc., or single required string) from `task`. Without this, every implicit-select search tool failed with `query: undefined`. Existing explicit `arguments` are never overridden.

### Changed
- **`_credentials_ready()` returns three explicit tiers** instead of the ambiguous "no creds declared":
  - `✅ free – no key` for official sources without declared creds
  - `🔑 needs SMITHERY_API_KEY` (or other key name) for Smithery-hosted servers AND any server with declared creds — Smithery is checked unconditionally because per-server creds may be empty but `SMITHERY_API_KEY` is always required
  - `⚠️  community — may need creds` for npm/pypi/github undeclared
  - `🔑 may need OAuth or registry key` for mcpregistry/glama undeclared
  Closes the issue-#8 misread where "no creds" looked like "free".
- **`status()` headline reordered** — `PROVIDERS` section now appears immediately after the title, before everything else. PID/memory/perf stats moved below. Auth state is the actionable info; perf stats aren't.
- **`shapeshift()` pre-flight gate for Smithery-hosted servers** — fails fast with `❌ shapeshift failed: '...' is hosted on Smithery and needs SMITHERY_API_KEY` *before* tools are loaded, instead of letting the user discover the auth wall on the first tool call. Bypassed with `confirm=True`. Includes a direct link to `smithery.ai/account/api-keys` and an offered workaround (`source="local"`).

### Acceptance criteria from issue #8

- ✅ `oauth.py` present and importable (v0.10.2)
- ✅ OAuth 2.1 flow works for direct HTTP servers (v0.10.2)
- ✅ New user reaches working tool call in ≤3 steps with zero API keys (`onboard()` + free-tier list)
- ✅ Search results never show Smithery-hosted as "no creds" (3-tier labels)
- ✅ `shapeshift()` warns before loading server with unconfigured creds (Smithery pre-flight gate)
- ✅ `status()` shows provider auth state primarily (reorder)
- ✅ `auto()` falls back across providers silently on auth failure (multi-provider walk)
- ✅ `auto()` correctly passes args to npm-based servers (argument inference + bug verified absent)

---

## [0.10.2] — 2026-05-03

### Hotfix
- **`kitsune_mcp/oauth.py` is now actually shipped.** v0.10.0 and v0.10.1 wheels were missing the module on PyPI and npm. `transport.py` imports it at line 13 and calls `oauth.ensure_token` / `oauth.delete_tokens` / `oauth._origin` from `HTTPSSETransport(direct=True)`, so every fresh `npx -y kitsune-mcp` and `pip install kitsune-mcp` hit `ImportError: cannot import name 'oauth' from 'kitsune_mcp'` at startup. Local development was unaffected because the file existed on disk; the file was authored locally but never staged. Closes #8 (Bug 1).
- **OAuth 2.1 device/browser flow** for direct HTTP MCP servers (`HTTPSSETransport(direct=True)`) is now functional in installed packages. 29 tests cover the flow end-to-end (`tests/test_oauth.py`).
- **CI guard added** — `tests/test_release_smoke.py` imports every `kitsune_mcp.*` module and asserts `kitsune_mcp.oauth` exports the symbols `transport.py` calls. Any future missing-module-on-publish bug will fail CI before reaching PyPI/npm.

---

## [0.10.1] — 2026-05-03

### Fixed
- **`_make_proxy` no longer forwards `None` for omitted optional params.** When a client called a shapeshifted tool without supplying optional non-string args (integers, booleans, arrays), the proxy filled them with `None` from its `__signature__` defaults and forwarded those `None`s to the inner MCP server, which rejected them with `Input validation error: None is not of type 'integer'` (JSON Schema doesn't permit null for typed params unless explicitly declared as `["type", "null"]`). Affected most non-trivial servers — `mcp-server-fetch` (`max_length`, `start_index`, `raw`), GitHub (`per_page`, `page`), Postgres/SQLite (`limit`, `offset`), Filesystem (`head`, `tail`). The proxy now drops `None`-valued kwargs so the inner server applies its own defaults instead. Falsy-but-not-None values (`0`, `False`, `""`) are preserved. Surfaced during the v0.10.0 setup-coverage tests against `mcp-server-fetch`.

---

## [0.10.0] — 2026-05-02

### Added
- **Auto-resolution of typo'd / wrong-namespace server IDs in `shapeshift()`** — `shapeshift("@modelcontextprotocol/server-time")` now silently resolves to the canonical `mcp-server-time` and proceeds, instead of returning a confusing "not found" error. Multiple plausible matches surface as a `Did you mean: a, b, c` suggestion list. Single high-confidence match auto-resolves on the first turn — agents recover without needing a retry. Closes #6 (the verified piece — see issue thread).
- **Machine-detectable failure marker** — every `shapeshift()` failure response now starts with `❌ shapeshift failed:` so callers can detect failure with one prefix check instead of parsing prose. Successful responses still start with `Shapeshifted into '...'`.
- **`_PaginatedListRegistry` base class** — `McpRegistryIO` and `GlamaRegistry` share a hookable paginated-fetch loop. New paginated registries now cost ~10 lines of overrides instead of ~30 lines of fresh page-loop code.
- **`TTLDict[K, V]` cache primitive** — keyed time-to-live cache with lazy expiry; replaces the ad-hoc `dict[tuple, (value, expires_at)]` pattern that was scattered across `MultiRegistry`.
- **`_fastmcp_compat` shim** — single point of contact for FastMCP private-API access (`_resource_manager._resources`, `_prompt_manager._prompts`). `_assert_internals(mcp)` runs at app startup so any future FastMCP refactor fails loudly at import rather than silently breaking `shiftback()`.
- **Per-registry timeout in `MultiRegistry`** — `search()` and `get_server()` wrap each registry call in `asyncio.wait_for(..., TIMEOUT_REGISTRY_TASK)` so one stalled DNS/TCP-connect can't block the others.
- **`_dotenv_revision` invariant** — documented as monotonically non-decreasing, with a guard test so future fixtures can't break pool eviction by resetting the counter.

### Changed
- **`kitsune_mcp/tools.py` (1782 lines) → `kitsune_mcp/tools/` package** with themed submodules: `discovery.py` (search/inspect/compare/status), `exec.py` (call/run/fetch/test/bench), `morph.py` (shapeshift/shiftback/craft/connect/release), `onboarding.py` (skill/key/auto/setup), `_state.py` (shared helpers + mocks-target namespace). All public imports preserved via `tools/__init__.py` re-exports — no breaking changes.
- **`ServerInfo` is now `frozen=True, slots=True`** — eliminates cache-poisoning via mutation and saves ~30% memory per instance. `dataclasses.replace(srv, ...)` continues to work.
- **`_SmitheryAuth` dataclass with `asyncio.Lock`** — replaces 4 module-level globals; concurrent `get_token()` / `get_namespace()` callers serialize on a lock with double-check, eliminating thundering-herd token refresh.
- **`_evict_stale_pool_entries()` debounced** to once per 30s on the call hot path (force=True still available for tests). Pool sweep is no longer O(N) per tool call.

### Fixed
- **Test mock-patch surface unified** — all `kitsune_mcp.tools.X` patch sites now route through `kitsune_mcp.tools._state.X`, the canonical namespace for cross-cutting state. 133 patch sites updated; future submodule refactors won't silently invalidate tests.

### Issue #6 follow-up (verification notes)
The reported "Bug 1" (`current_form` not set after shapeshift) does not reproduce against a verified-valid server ID. The agent's repro used `@modelcontextprotocol/server-time` — which doesn't exist in any registry. shapeshift correctly returned a "not found" error which the agent misread as success, then was confused when downstream `call()` had no `current_form` to use. The auto-resolution work above fixes the underlying UX failure (typo'd ID → confusing error chain) so the same pattern can't happen again. The architectural claim that ~80% of clients are blind to dynamic tool changes is partially incorrect — the standard `mcp` Python SDK honors `notifications/tools/list_changed` (which Kitsune already sends), and verification confirms tools become visible to spec-compliant clients. Specific clients that don't honor the notification are the right targets to fix once verified — defensive-only code (Solution 1 / refresh tool) deferred until verified reports exist.

---

## [0.9.0] — 2026-04-12

### Added
- **`source=` parameter on `shapeshift()`** — `"local"` forces npx/uvx install (no Smithery key); `"smithery"` forces HTTP; `"official"` requires verified registry listing; `"auto"` (default) keeps current behavior
- **`shiftback(uninstall=True)`** — optionally uninstalls the locally installed package; uvx packages fully removed (`uv tool uninstall`), npx cache auto-expires
- **`KITSUNE_TRUST` env var** — set `"community"` to permanently bypass the community/local confirmation gate for trusted users and agents (`key("KITSUNE_TRUST", "community")`)
- **Credential status in `search()` results** — each row now shows `✅ ready` or `✗ needs API_KEY`
- **`inspect()` next-step CTA** — ends with `Next: key("VAR", "...") then shapeshift("id")` or `Next: shapeshift("id")` based on credential state
- **Lean hint after `shapeshift()`** — servers with >4 tools loaded without a filter show `💡 N tools loaded (~X tokens). For lean mounting: shapeshift("id", tools=[...])`
- **First-run onboarding in `status()`** — clean sessions show a 5-step guide with example flow
- **Registry failure reporting in `search()`** — timed-out registries shown as `⚠️ Skipped: name (timeout)` so partial results are visible

### Fixed
- **Credential check before `_do_shed()`** — missing credentials no longer drop your active form before returning the error
- **`bust_cache(server_id)` now works** — cache uses `(id, source_preference)` tuple keys; old `pop(str)` silently missed every entry
- **`source="official"` gate ordering** — official-source check fires before the trust gate, giving the right error for non-official servers
- **Pool path `current_form_local_install` leak** — pool shapeshift clears local install record so stale data can't trigger `uninstall=True` on the wrong package

### Changed
- `shapeshift()` pool-path and registry-path share a single `_commit_shapeshift()` helper — ~70 lines of duplication removed
- `_credentials_ready()` calls `_to_env_var(k)` once per key instead of three times
- `MultiRegistry._reg_names` precomputed at init instead of on every `search()` call

---

## [0.8.5] — 2026-04-11

### Fixed
- **Circular import** between `registry.py` and `official_registry.py` — `_registry` is now
  a lazy proxy; `MultiRegistry()` is deferred until first use
- **Ruff lint** — 64 errors resolved (import ordering, unused vars, SIM105, B023, UP046);
  CI pipeline is now fully green on Python 3.12 and 3.13

### Added
- Codecov coverage reporting (badge in README, uploads on every CI run)
- Automated GitHub Releases with CHANGELOG excerpt on tag push
- Glama registry listing (`glama.json`)
- Dependabot for weekly pip + GitHub Actions updates
- SECURITY.md and PR template

---

## [0.8.2] — 2026-04-11

### Added
- npm wrapper package — `npx kitsune-mcp` delegates to `uvx kitsune-mcp` (Python)
- Official MCP registry listing (`server.json` for `mcp-publisher`)
- `mcp-name` ownership tag in README for registry verification

---

## [0.8.1] — 2026-04-11

### Fixed
- **Smithery transport rewritten** — replaced dead `server.smithery.ai/{name}/mcp?config=b64` URL
  with the new Smithery Connect API: namespace → service token → connection upsert →
  `api.smithery.ai/connect/{ns}/{id}/mcp`. Fixes 400 "Server configuration is incomplete"
  and "Invalid token" errors from `run.tools`.
- **Registry** now reads `deploymentUrl` from Smithery API response instead of reconstructing stale URLs
- **`_resolve_config`** always writes all credential keys (`None` → JSON `null`) so Smithery's
  schema validator sees all expected keys even when optional vars are unset

### Changed
- `morph.py` → `shapeshift.py` (rename complete; `morph.py` deleted)
- Session keys: `morphed_tools/resources/prompts` → `shapeshift_tools/resources/prompts`
- `.chameleon` directory references → `.kitsune` in `credentials.py`, `session.py`, `transport.py`
- Docker label: `chameleon-mcp=1` → `kitsune-mcp=1`

---

## [0.8.0] — 2026-04-10

### Breaking Changes
- **Package renamed** `protean-mcp` → `kitsune-mcp` — update `pip install` and client configs
- **Package directory renamed** `chameleon_mcp/` → `kitsune_mcp/` — update any direct imports
- **Env var renamed** `CHAMELEON_TOOLS` → `KITSUNE_TOOLS` — update any custom tool filters
- **FastMCP server name** `"protean"` → `"kitsune"` — affects MCP client display name

### Deprecated (remove in v0.9)
- `protean-mcp`, `protean-forge` executables (kept as aliases)
- `chameleon-mcp`, `chameleon-forge` executables (kept as aliases)

### Migration
```bash
pip install kitsune-mcp
# update mcp.json: "command": "kitsune-mcp"
# update env: KITSUNE_TOOLS=... (was CHAMELEON_TOOLS)
```

---

## [0.7.3] — 2026-04-08

### Fixed
- `status()` output header: "CHAMELEON MCP STATUS" → "KITSUNE MCP STATUS"

---

## [0.7.2] — 2026-04-08

### Fixed
- README: absolute image URLs so logo and diagrams render on PyPI

---

## [0.7.1] — 2026-04-08

### Changed
- New logo (`logo_kitsune-mcp.png`) replacing placeholder SVG
- README: removed "a new way" framing; architecture diagrams cleaned of chameleon references
- `docs/architecture.svg`: removed 🦎 emoji from Kitsune MCP label
- `docs/architecture-forge.svg`: "chameleon-forge" → "kitsune-forge"

---

## [0.7.0] — 2026-04-08

### Breaking Changes

- **`morph()` renamed to `receive()`** — update any prompts or scripts that call `morph(...)`
- **`shed()` renamed to `cast_off()`** — update any prompts or scripts that call `shed()`
- **Package renamed from `chameleon-mcp` to `kitsune-mcp`** — update `pip install` and `pyproject.toml` references
- **Executables renamed**: `chameleon-mcp` → `kitsune-mcp`, `chameleon-forge` → `kitsune-forge`

### Migration Guide

| Before | After |
|---|---|
| `pip install chameleon-mcp` | `pip install kitsune-mcp` |
| `"command": "chameleon-mcp"` | `"command": "kitsune-mcp"` |
| `receive("exa")` | `receive("exa")` ← no change |
| `morph("exa")` | `receive("exa")` |
| `shed()` | `cast_off()` |

**Deprecated executables** (`chameleon-mcp`, `chameleon-forge`) are kept as aliases in v0.7.x for backward compatibility and will be removed in v0.8.0.

### Added
- `kitsune-mcp` and `kitsune-forge` as primary entry point executables
- `chameleon-mcp` and `chameleon-forge` kept as deprecated backward-compat aliases

### Changed
- MCP server display name: `"chameleon"` → `"protean"`
- `pyproject.toml` keywords: removed `"smithery"`, added `"mcp-registry"`
- Package description updated to reflect 7-registry architecture

---

## [0.6.2] — 2026-04-08

### Fixed
- `receive()` cold-start: prefer registry results with cached tool schemas over those without (fixes Exa cold-start failure)
- Live `tools/list` HTTP fetch fallback when registry cache is cold
- Smithery URL format: `/mcp` suffix + `api_key` query param (was using wrong format)
- Doubled Smithery URL when `srv.url` was already a full URL
- Pool staleness: auto-evict subprocesses when `.env` changes mid-session

---

## [0.6.1] — 2026-04-07

### Added
- Frictionless credentials: `.env` auto-reload without restart (tracks mtime changes)
- `call()` is mount-aware: `server_id` optional after `receive()`
- `call()` added to lean profile (7 tools total)
- WebSocket transport support (`ws://`, `wss://`)

---

## [0.6.0] — 2026-04-07

### Added
- `receive()` proxies resources + prompts in addition to tools
- Install command validation (shell injection and path traversal blocked)
- Trust tier warnings in `receive()` output
- Credential warnings at mount-time (not just at `call()`-time)
- `examples/benchmark.py` — reproducible token overhead measurement
- Notification compatibility testing
- Provenance shown in all `search()`/`inspect()`/`receive()`/`call()` output

---

## [0.5.9] — 2026-04-06

### Added
- Refactored into `kitsune_mcp/` package structure
- `OfficialMCPRegistry` — seeds from `modelcontextprotocol/servers` GitHub repo
- `inspect()` stores measured `token_cost` from actual tool schemas
- `status()` sums measured costs for inspected-but-not-mounted servers
- Per-server trust tier tracking

### Fixed
- Registry fan-out priority: official > mcpregistry > glama > github > smithery > npm
- PyPI registry is opt-in only (not in default fan-out — too slow)
