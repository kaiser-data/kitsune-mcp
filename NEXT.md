# What's next — post v0.20.7

_Last updated: 2026-07-11 (evening). Running MCP confirmed on v0.20.7._

## RESOLVED + MERGED 2026-07-11 — KITSUNE_HOME everywhere (#39 → PR #57) and prewarm() (#41 → PR #58)

Both remaining code-backlog items closed the same day, TDD, CI green on 3.12 + 3.13:

- **PR #57** (`ad9c14e`) — new `kitsune_mcp/paths.py::kitsune_home()` is the single
  source of truth; all six hardcoded `~/.kitsune` sites (issue audit listed 4 —
  `SKILLS_PATH` and `server.py`'s dotenv load were also hardcoded) now derive from
  it. Constant names preserved → all existing test patches untouched. README
  gained a "Custom state directory" section. Issue #39 auto-closed.
- **PR #58** (`c1e767f`) — `prewarm(server_id)` starts a registry server's
  subprocess in the pool WITHOUT mounting tools; later `shapeshift()` reuses the
  warm process (identical cmd → same pool key). Same trust/credential gates as
  shapeshift. Pool entry named `server_id` → `status()` lists it, `release(id)`
  discards it. Forge-only (lean stays 6 tools). Forge is now **21 tools /
  ~3,216 tokens; break-even 6+ servers** — benchmarks.md, tools.md, and the
  server.py docstring were regenerated in the same PR (no doc drift). Issue #41
  auto-closed.
- Dependabot **PR #54** (upload-artifact 4→7) also merged. Suite: **723 passing**.

**Remaining backlog:** v1.0-track items only — demo video (script verified, needs
a human), Dockerfile/GHCR, client compat matrix, benchmark-in-CI — plus the
manual close of external PR #33 (SafeSkill badge). v1.0 hardening notes from the
graph trace (Literal types for `ServerInfo.source`, mutable fields in the frozen
dataclass) still stand below.

## RESOLVED + MERGED 2026-07-11 — Absorbed-server ranking + URL-server absorption (PR #55)

**Status:** ✅ Squash-merged to `main` (`9fe2a47`); post-merge CI green on 3.12 + 3.13
(run 29150842784, 709 passed). Found via knowledge-graph trace of the
`AbsorbedServer → ServerInfo` boundary after the #40 follow-up review:

- **URL-based remote servers** (`{"url": ..., "type": "http"|"sse"}` entries,
  common in `~/.claude.json` — the surface #40 added) were absorbed as
  `command=""` and converted with hardcoded `transport="stdio"`,
  `install_cmd=[]`; shapeshift's stdio fallback then "repaired" them into
  executing `npx -y <server-id>` — an arbitrary same-named npm package.
  `AbsorbedServer` now carries `url`/`transport` (defaulted — legacy
  `absorbed_servers.json` loads unchanged), parse maps ws://→websocket else
  http and skips unlaunchable stubs, `_to_server_info()` passes both through
  to the existing `_get_transport()` HTTP path.
- **Ranking inversion:** `source="absorbed"` was missing from `_SOURCE_TIER`
  (→ 99, behind every registry), `_WORKS_NOW_TIER` (→ 0.0, below anonymous
  npm), and `TRUST_HIGH` (→ "community — not verified" label). Now tier 0 /
  0.35 (above official) / high-trust — auto() prefers the user's own working
  config instead of routing away from it.
- 11 regression tests added (709 total passing).

**Note for v1.0 hardening (from the same trace):** `ServerInfo.source` is
stringly-typed and now documents 10 live values — `Literal` types would turn
silent `.get(..., default)` fall-throughs (the root cause here) into type
errors. `ServerInfo`'s frozen dataclass has mutable `list`/`dict` fields
(`tools` is lazily mutated post-construction) — aliasing hazard via the TTL
cache.

## RESOLVED + MERGED 2026-07-10 — Lean-profile setup() dead-end + stale benchmark docs (PR #52)

**Status:** ✅ Merged to `main` (`785ee24`); main CI green on 3.12 + 3.13.

External review (Grok, reports kept locally untracked) confirmed two issues:
- The GATEWAY hint in `status()` unconditionally recommended `setup()`, which
  doesn't exist under the default lean profile. Now profile-aware: lean users
  get "Restart with `KITSUNE_TOOLS=all` to unlock setup()", forge users keep
  the direct hint. Profile resolution centralized into `_LEAN_TOOL_NAMES` /
  `_active_tool_names()` in `kitsune_mcp/tools/_state.py` (single source of
  truth; `server._LEAN_TOOLS` kept as alias).
- Stale token numbers: `server.py` docstring (lean ~1,321 / forge ~3,033) and
  `docs/benchmarks.md` regenerated from actual v0.20.8 output; break-even
  corrected to 3+ servers (lean) / 5+ (forge).
- 5 regression tests added (691 total passing).

**Open follow-ups from that review:** issues #40 (`_find_mcp_configs()`
misses `~/.claude.json`) and #39 (`KITSUNE_HOME` only honored in session.py)
are the next code tasks; bigger v1.0-track items (demo video, Dockerfile/GHCR,
client compat matrix, benchmark-in-CI) are catalogued in the readiness report.

## RESOLVED + MERGED 2026-07-07 — CI Linux VM-kill (PR #49, #50)

**Status:** ✅ Fixed and merged to `main`; main CI green on 3.12 + 3.13
(run 28885353577, `686 passed`). Two PRs:
- **#49** (`adf9a40`) — the real fix (safe process-group kill + pipe drain).
- **#50** (`6a6dc9a`) — follow-up: the diagnostic hang-watcher had a leftover
  `FREEZE_SECONDS=6` from bisection that false-positived on healthy runs (a
  few-second static-log gap while coverage writes before `pytest.exit`) and
  failed the *green* post-merge run on main. Raised to 120s. Same PR carried
  two doc fixes: README hero token-savings `95% → 93%` (matches the reconciled
  savings table; the `~95%` long-tail *accuracy* figures are separate and
  correct, unchanged), and a CONTRIBUTING note that a bare `uv run pytest`
  needs `--extra dev` (addopts require pytest-timeout).

**Only open follow-up:** record the demo video (script is verified
reproducible; needs a human at the keyboard).

**It was never a hang — it was the runner VM being killed.** An `asyncio`
subprocess with a full, unread **stdout PIPE** that is then SIGKILLed via
`os.killpg` and awaited (`proc.wait()`) wedges the entire GitHub runner —
hard enough that step teardown *and* shell builtins stall, which is exactly
why all prior post-mortem attempts died with the job and retained no logs.
Proven with a **kitsune-free** control: `yes` → unread PIPE → `killpg(SIGKILL)`
→ `wait()` wedged the box; draining the pipe, using `/dev/null`, or not
flooding all survived (repro run 28880054696, case `yes-pipe-kill`).

**Two production defects in `transport.py`, both fixed:**
1. `_kill_process_tree()` called `os.killpg(os.getpgid(pid), SIGKILL)` on **any**
   pid — including leaked/mock pool entries (tests hardcode `pid=99999`). At the
   `atexit` `_kill_all_pool_processes` sweep a fake pid could resolve to a
   **live, unrelated group** on the busy runner and SIGKILL it (potentially the
   runner agent). Now killpg fires only for a real `int > 1` that leads its own
   session group (`getpgid(pid) == pid`, guaranteed by `start_new_session=True`).
2. `execute()` reaped with `proc.wait()` but never drained stdout/stderr → a
   flooded PIPE deadlocked. New `_reap()` drains both pipes to EOF concurrently
   with `wait()`, under a hard timeout.

**Also landed:** autouse conftest fixture clears `_process_pool` after every
test (no mock entry survives to the atexit killer); regression tests for the
safe-killpg guard and the drain reaper (`TestKillProcessTreeSafety`).

**How it was found:** 7 rounds of matrix bisection (file → class → single test)
narrowed it to transport/pool tests, then a kitsune-free raw-asyncio control
reproduced it with zero project code — reframing it from "our bug" to an
environmental asyncio/kernel interaction that our teardown happened to trigger.
The **pre-armed hang watcher** (`.github/scripts/ci-hang-watcher.py`, posts
`/dev/kmsg` + SysRq-W kernel stacks to the PR over HTTPS) is kept in CI as a
safety net: a future regression posts stacks instead of silently timing out.

**Follow-up (optional):** consider `pytest-timeout` at the session level and a
CONTRIBUTING note that a bare `uv run pytest` needs `--extra dev` (addopts pull
in pytest-timeout). Non-blocking.

**Session setup note:** `kitsune` MCP server is registered for this folder
(local scope in `~/.claude.json`): `uv run --directory <repo> kitsune-mcp` —
serves the live dev source; verified connected.

## Done 2026-06-09 (repo health session, unreleased on main)

- ✅ CI-breaking unused import removed (tools/discovery.py); Makefile lint/test
  targets realigned with CI scope and switched to `uv run`.
- ✅ transport.py test coverage 67% → 97% (59 new tests in
  tests/test_transport_coverage.py: Smithery Connect auth, list_tools,
  reconnect/broken-pipe paths, .env-revision respawn, pool lifecycle).
- ✅ Test suite warning-clean: all 8 "coroutine never awaited" RuntimeWarnings
  fixed (AsyncMock→MagicMock stdin/stdout; timeout fake closes the coroutine).
- ✅ MCP protocol bumped 2024-11-05 → 2025-06-18 with proper negotiation:
  HTTP transports echo the server's negotiated version via the
  MCP-Protocol-Version header (required by Streamable HTTP since 2025-03-26).
- ✅ Item 5 below (README "Peak" comments) — relabeled as mount cost + total
  with the ~1,321 floor, reductions recomputed (60/48/76%).
- These changes are commits on main, not yet released/tagged.

## Publishing status (corrected 2026-05-24)

### PyPI — ✅ NOT a problem; auto-publishes on tag
- `.github/workflows/publish.yml` uses **OIDC trusted publishing**
  (`pypa/gh-action-pypi-publish`, `id-token: write`, `environment: pypi`), triggered on every
  `vX.Y.Z` tag push. No token required.
- Verified: PyPI `info.version` = **0.20.8**; publish runs for 0.20.5–0.20.8 all succeeded.
- The local `~/.pypirc` token is project-scoped to a *different* project (hence the manual
  `twine upload` 403 seen earlier) — but it is **irrelevant to releases**, which never touch it.
  Optional cleanup: replace it with a kitsune-mcp-scoped token or delete the entry to avoid
  confusion, but nothing depends on it.

### npm — ✅ live at 0.20.8 (2026-05-24)
- Was stale at 0.20.1. Root cause: no Trusted Publisher registered (npm's
  404-on-PUT = OIDC rejected). Owner added the GitHub Actions Trusted Publisher
  (`kaiser-data` / `kitsune-mcp` / `publish.yml`, no environment, `npm publish`
  allowed); re-ran `gh workflow run publish.yml -f publish_npm=true` (run
  26372085037) → success. `npm dist-tags.latest` = 0.20.8.

### MCP Registry — ✅ live at 0.20.8 (2026-05-24)
- `gh workflow run publish.yml -f publish_registry=true` (run 26372105447) →
  success. Registry entry `io.github.kaiser-data/kitsune-mcp` 0.20.8 has
  `isLatest: true`.

**All three registries (PyPI / npm / MCP Registry) are now current at 0.20.8.**
Future tag pushes auto-publish PyPI only; npm + MCP Registry still require the
manual `workflow_dispatch` flags (`-f publish_npm=true`, `-f publish_registry=true`).

## Follow-ups from the v0.20.5 issue audit

### 2. ✅ DONE in v0.20.8 — #44 completed for Smithery servers
- Implemented option (a): `_commit_shapeshift` refetches the live schema via
  `transport.list_tools()` when the registry listing is thin (`_schemas_missing_required`).
  Fixes both proxy registration and the hint. 2 tests added; verified live against context7.

### 3. ✅ DONE 2026-06-13 — #43 logout, LIVE-VERIFIED against Notion
- Code + 6 unit tests (RFC 7009 revoke + `prompt=login`). Regression test
  `test_logout_then_reauth_is_fresh_flow_not_silent_refresh` locks the repro.
- **Live verification (real Notion OAuth, 2026-06-13 11:08 CEST):**
  - `auth("notion-hosted")` → returned cached token (valid leftover), prefix `fe5fb9ad…`.
  - `auth("notion-hosted", "logout")` → "Refresh token revoked at the identity provider" —
    RFC 7009 revoke confirmed firing live.
  - `auth("notion-hosted")` → a **browser window opened** (user-confirmed) and a FRESH token
    was minted: `tokens.json` rewritten at 11:08 with `expires_at` 12:08 (+58 min) and a new
    refresh token. Since logout deletes the bundle, the silent-refresh path is impossible —
    a completed `authorize()` flow is the only way that file exists.
- **Key finding — the `fe5fb9ad…` prefix is a Notion red herring.** Notion's 86-char access
  tokens for this app/workspace carry a STABLE prefix; re-issued tokens share `fe5fb9ad…`
  even when freshly minted. The original bug report's "same prefix ⟹ silently reused" was a
  false signal — verify with `expires_at` / on-disk write time, never the prefix.

### 4. ✅ DONE 2026-06-13 — #34 auto() capability filter (commit 002a5b3)
- Implemented the 3-point plan from the issue: generic intent verbs stripped from
  registry queries, intent-capability filter before ranking (a fetch-only server
  can no longer win a "search the web" task), and a guidance refusal when no
  candidate matches. 16 new tests in test_issue_34_capability_filter.py.
- NOT implemented (no data source): the `taskSupport: required ⊄ client_capabilities`
  filter from the issue comment — no registry currently exposes taskSupport, so
  there is nothing to filter on. Revisit if/when registries ship capability metadata.

## Docs polish (non-blocking)

### 5. ✅ DONE 2026-06-09 — README example-block "Peak" comments
- Relabeled as mount cost and added totals including the ~1,321 floor;
  reductions recomputed (60% / 48% / 76%).

### 6. ✅ DONE 2026-06-13 — token-cost SVG vs README table drift reconciled
- Both `docs/token-cost-{light,dark}.svg` now read 62 / 77–81 / 87–93 (was 62 / 74–81 / 89–94),
  matching the grounded per-server table. Kitsune bar values + heights updated to the range
  midpoints (~1,621 / ~1,820 / ~2,450) and the stale "500-token base" caption corrected to
  the measured "~1,321-token floor" in both the axis subtitle and the legend footnote.
- README upper table (saving-formula section) reconciled to the lower per-server table —
  both now read 62 / 77–81 / 87–93 with Kitsune ranges ~1,631–2,011 and ~1,631–3,271.
- Removed orphan `docs/token-cost.svg` — unreferenced since the May light/dark <picture>
  split and still carrying the pre-floor figures (800 / 81% etc.); recoverable from git.
- Open judgment call (not changed): hero line still says "Up to 95%"; the highest documented
  figure is now 93% (95% is reachable only for fleets larger than the 5-server example).

## Done this session (v0.20.7, verified live on running MCP)
- ✅ #42 savings counter — `status()` now shows `~2,661 tokens [1 mounted server(s) + 2
  inspected schema(s)]` after a single memory mount (was stuck at ~46).
- ✅ #45 HTTP unmount — no more "pool key missing" warning (context7 + memory unmounts clean).
- ✅ #44 for official/stdio servers — `server-memory` hint shows `{'entities': []}`.
- ✅ README baseline framing rewritten to be explicit that Kitsune has a fixed ~1,321-token
  floor (never zero), with a break-even note and corrected Performance tables.
