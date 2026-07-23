# What's next — post v0.20.7

_Last updated: 2026-07-23. **Agent-harness reposition SHIPPED** + **PR A of the
sellability plan committed to `main`** (`fa420eb`, NOT pushed, NOT released).
Continue with **PR B** (discovery + demo hygiene), then **PR C** (sandbox-by-default).
v0.21.0 bump/tag/publish still NOT done._

## SESSION 2026-07-23 — reposition as agent harness + sellability plan PR A (lean MCP REPL)

Two things happened this session. Both are **local commits on `main`, unpushed**;
no release, no PR opened.

### 1. README/docs reposition — SHIPPED (`abf8be4`, pushed earlier this session)
The token-savings pitch is dead (native Tool Search owns deferral for configured
servers). Rewrote the story around the durable value: **agent harness = reach +
MCP REPL + contained try-before-trust**. Touched `README.md` (full restructure,
~580→~470 lines then re-expanded in PR A), `docs/article.md`, `docs/demo-script.md`,
`examples/scenarios/README.md`, `pyproject.toml` description, `NEXT.md`. This commit
WAS pushed to origin; the header's "reposition still pending" is now done.

### 2. Sellability analysis → 3-PR plan
Deep repo analysis (code-explorer subagent) found the core problem: **the pitch's
#1 feature (MCP REPL) was unreachable on a default install** — `connect`/`release`
were forge-only. Plan saved at
`~/.cursor/plans/Sellability Improvements-05b7ee0d.plan.md`:
- **PR A** (DONE this session): lean MCP REPL + `reload()`.
- **PR B** (NEXT): discovery works-now signal + `onboard` fix + rewrite `examples/demo_wow.md`.
- **PR C**: tri-state `sandbox` param, cage `TRUST_LOW` on `shapeshift`+`prewarm` by default.

### PR A — lean MCP REPL + reload() — COMMITTED (`fa420eb`, unpushed)
- `_LEAN_TOOL_NAMES` (`kitsune_mcp/tools/_state.py`) now includes `connect`,
  `release`, `reload`; `reload` added to `_BASE_TOOL_NAMES`. `auto()`'s built-in
  guard (`onboarding.py`) moved connect/release into `_KITSUNE_LEAN` + added reload.
- New **`reload(name)`** tool (`kitsune_mcp/tools/shapeshift.py`, after `release`):
  reuses release's lookup, reads the stored launch command from
  `session["connections"][key]["command"]`, then release → connect → `shapeshift(name)`.
  Surfaces connect failure verbatim and **skips remount** on failure. Removes the
  "connect handed back the old process" footgun (always releases first).
- Tests: new `tests/test_reload.py` (7 tests; note — import the module via
  `importlib.import_module("kitsune_mcp.tools.shapeshift")`, because
  `kitsune_mcp.tools.shapeshift` resolves to the re-exported *function*, not the
  module). `tests/test_tool_surface.py`: lean count **6 → 9**, REPL trio in
  `LEAN_REQUIRED`. **810 passed, 2 skipped; ruff clean.**
- **Token floor remeasured: lean 1,358 → 1,685 (9 tools), forge 3,253 → 3,396.**
  Updated every LIVE reference: `README.md` (fit-table, install line, Performance
  table recomputed + multi-server range ~77–85%, Developing section rewritten
  around `reload()` — no more "enable forge"), `server.py` docstring,
  `docs/benchmarks.md` (regenerated reference output + interpretation: lean now
  cost-effective at 4+ servers), `docs/article.md`, `docs/demo-script.md`,
  `examples/linkedin_post.md`.
- `graphify update .` run.

### PR B — discovery works-now signal + onboard fix + demo hygiene — COMMITTED (unpushed)
- **Works-now signal on `search`**: new `_works_now_label()` in
  `kitsune_mcp/tools/discovery.py` wraps `registry._works_now_score` (0.0–1.0)
  into `high|mid|low` (thresholds: ≥0.55 high, ≥0.3 mid, else low). Every search
  row now ends ` | ready: <label>` (no probe, pure heuristic: creds resolved +
  source tier + local transport). No forge `compare` table on lean.
- **`onboard()` 3-step check accuracy fix** (`onboarding.py`): step 3 was
  `shiftback()` (forge-only) → now `shapeshift()` (empty arg = unmount, and it's
  lean), so the check is copy-pasteable in **both** profiles.
- **`examples/demo_wow.md` full rewrite**: dropped Chameleon/`receive`/`cast_off`
  and the token-savings headline; now a lean-only 7-step session organized around
  the three pillars (reach / MCP REPL via `reload` / try-before-trust), default
  install, wedge line. Concrete `call` uses verified `mcp-server-time` /
  `get_current_time` (didn't assert the duckduckgo tool name).
- **`docs/demo-realtime.md`**: setup note no longer demands `KITSUNE_TOOLS=all`
  (trio is lean now); Act 1 rewritten to add the missing `shapeshift("dev")`
  mount step and use the one-call `reload("dev")` (was manual release+connect).
- **README hero**: trimmed the last "forge profile" REPL callout — the flow line
  now reads `connect → shapeshift → edit → reload → call   # MCP REPL (default
  install)` and the pillar table cell is `edit → reload → call`.
- Tests: `tests/test_ux_changes.py::TestSearchWorksNowSignal` (+3),
  `tests/test_onboard.py` updated to assert `shapeshift()` and NOT `shiftback()`.
  **812 passed, 2 skipped; ruff clean.** `graphify update .` run.
- NOT touched (out of PR-B scope, still stale): `examples/test_session.md`
  (legacy Chameleon/`receive`/`cast_off` walkthrough), `docs/compatibility.md` /
  `docs/transports.md` stray `Chameleon`/`receive` mentions, issue templates.
- [ ] **PR C** — tri-state `sandbox: bool | None` on `shapeshift` (None=policy,
  True=force+hard-fail, False=opt-out), cage `TRUST_LOW` by default on
  `shapeshift`+`prewarm` (best-effort uncaged+nudge if Docker missing, matching
  the exec paths), `KITSUNE_SANDBOX=off` escape hatch, unify README Safety wording.
- [ ] **Stale token-cost SVGs** — `docs/token-cost-{light,dark}.svg` still show the
  old floor; regen needed (deferred from PR A — needs the SVG regen script).
- [ ] v0.21.0 release (bump `pyproject.toml`/`package.json`/`server.json`, tag, publish).

---

## SESSION 2026-07-16 (evening) — CI red → green, container E2E in CI, real sandbox bug found+fixed, PR #61 merged

Started from "read handoff, analyze, path to next version". Found **PR #61's CI
was red** (the morning handoff's "801 pass" was local-only). All fixed, E2E added,
PR squash-merged to main (`e91d9df`). **803 tests + 2 gated E2E, all CI green.**

### The bug class: tests sensitive to host Docker
`transport_for_exec` branches on `shutil.which("docker")` — CI runners SHIP
Docker, this Mac doesn't (dangling OrbStack symlink). So sandbox-by-default made
`test_auto_falls_back_to_next_provider_on_auth_failure` take the real
Docker-wrap path on CI only, bypassing its mocked `_get_transport` (green local,
red CI; 3rd instance of this class). Fixes, in order:
- `fd28be2` — that test now forces Docker absent (same pattern as test_audit_fixes).
- `7068766` — **structural**: autouse conftest fixture forces
  `shutil.which("docker")` → None suite-wide (pass-through for other binaries);
  opt-out marker `real_docker` (registered in pyproject). Verified 801-green
  both with and without a docker on PATH.

### Container E2E now runs in CI (the deferred follow-up — CLOSED)
Key realization: ubuntu runners HAVE a live daemon — E2E was never blocked on
this machine. `9a2870b`:
- `tests/test_docker_e2e.py` (gated `KITSUNE_E2E_DOCKER=1` + `real_docker`):
  sandboxed `uvx mcp-server-time` answers a real `get_current_time` call through
  the hardened wrap; `transport_for_exec` cages a real npm server
  (`@modelcontextprotocol/server-everything`) end-to-end.
- New `docker-e2e` CI job; pre-pulls base images **from kitsune_mcp.constants**
  (no workflow/code drift). Tests skip cleanly everywhere else.

### E2E's first run caught a REAL product bug (`2707ce2`)
Docker's default `--tmpfs` options include **noexec**, and the sandbox wrap
points HOME + npm/uv caches at /tmp — so npx/uvx downloaded the server, then
`Permission denied (os error 13)` on spawn. **Every real sandboxed launch was
broken; all mocked tests passed.** Fix: sandbox wrap mounts
`/tmp:rw,exec,nosuid,size=512m` (tmpfs pages count against `--memory`);
DockerTransport's scratch tmpfs keeps the stricter noexec default (server ships
in the image). TDD'd (2 regression tests in test_sandbox.py); CHANGELOG updated.

### Publish dispatch (user-run) was a no-op — expected
`publish.yml -f publish_npm=true -f publish_registry=true` ran against main
@0.20.8: npm "cannot publish over 0.20.8", MCP Registry "duplicate version",
PyPI skip-existing no-op. Harmless; nothing changed anywhere.

### NEXT ACTIONS — finish the v0.21.0 release (merge is done, rest is NOT)
1. Bump **all three**: `pyproject.toml` (v7), `package.json` (v3),
   `server.json` (3 occurrences) → `0.21.0`.
2. CHANGELOG: `## [Unreleased]` → `## [0.21.0] — 2026-07-16`.
3. Commit to main, tag `v0.21.0`, push commit + tag → PyPI auto-publishes.
4. `gh workflow run publish.yml -f publish_npm=true -f publish_registry=true`
   → npm + MCP Registry at 0.21.0.
5. Verify: PyPI `info.version`, `npm dist-tags`, registry `isLatest`.
- Note: permission classifier blocks agent-run `gh pr merge`/some pushes —
  user ran the merge via `! gh pr merge 61 --squash --delete-branch`.
- **Judgment call flagged**: releasing 0.21.0 ships the README with the OLD
  token-savings pitch (reposition still pending, see below). User chose to
  proceed with release first.

## SESSION 2026-07-15 — supply-chain hardening of the local-execution path (branch `feat/docker-sandbox-local-servers`, pushed, NOT merged)

Two features built TDD-first on top of the shipped hardening commit (`3da2cc5`),
plus a strategic reframe and a companion skill. **787 tests pass (+55), ruff
clean.** Branch pushed to origin; no PR opened yet.

### 1. Docker sandbox for local npm/PyPI servers — `8ca8adb`
The hardened docker profile (`3da2cc5`) was only reachable via explicit
`docker:` image IDs; npm/PyPI servers still ran as raw host subprocesses (the
code literally called real isolation "the deferred Docker-sandbox follow-up").
Now delivered:
- `shapeshift(server_id, sandbox=True)` wraps the local `npx`/`uvx` launch in the
  locked-down profile (`--cap-drop ALL`, read-only rootfs, `--pids-limit`,
  `--memory`, no host FS). npm/uv caches redirect to the container tmpfs.
- **Secrets never enter the argv** — credential env vars forwarded by NAME only
  (`docker -e KEY`); nothing in `ps` or the pool key.
- `KITSUNE_SANDBOX` session policy: `community` sandboxes low-trust mounts,
  `all`/`1` sandboxes every local mount. Community trust gate now offers the
  caged path. Pre-flights fail fast (Docker missing / HTTP-hosted / non-npx-uvx)
  before the current form is shed.
- `DockerTransport._build_cmd` + new `sandbox_wrap_cmd()` share one
  `_hardened_docker_flags()`. New constants `SANDBOX_NPM_IMAGE` (node:22-slim) /
  `SANDBOX_PYPI_IMAGE` (astral uv). `tests/test_sandbox.py` (+28).
- Adds `sandbox` param → +37 schema tokens; lean floor **1,321 → 1,358**, forge
  3,216 → 3,253. Every derived figure regenerated (README tables, benchmarks.md,
  demo-script, article, token-cost SVGs, server.py docstring).

### 2. Trust-on-first-use (TOFU) version pinning — `c4b0a69`
Resolution-time pinning re-pins to "latest" every run, so it drifts across
sessions. New `kitsune_mcp/pins.py`:
- First mount records the exact version in `~/.kitsune/pins.json` (atomic,
  0600); later mounts reuse it. On drift, launches the PINNED version and warns
  `⚠️ pinned to X, registry now offers Y`. `KITSUNE_REPIN=1` adopts newer + updates.
- Applied before `server_args` and before the sandbox wrap (regression-tested:
  pinned spec flows through `sandbox_wrap_cmd`). **No tool-schema change** (env
  policy). `tests/test_pins.py` (+27). Corrected the README caveat that
  previously overclaimed cross-session immutability.

### 3. Strategic reframe (discussion, not yet in docs)
Agreed: the token-savings pitch is dead (native Tool Search / deferred loading
handles context bloat, and even Kitsune's own mounted schemas get deferred by a
modern client). Kitsune's durable value = **agent harness**: runtime reach into
the 130k long tail with no config/restart, live MCP dev, and supply-chain
safety (which the two commits above harden). Always-on is a strawman baseline.

### 4. `kitsune-improve` skill (shipped in marty-skills repo, pushed `6a50294`)
Decision: ship the "improve MCPs" capability as a **skill, not a Kitsune tool**,
to keep the gateway slim. Lives at
`martys-claude-tools/marty-skills/skills/kitsune-improve/`, symlinked into
`~/.claude/skills`, indexed in that repo's README. Drives existing tools
(`test`, `inspect`, lean `shapeshift`, `craft`) in a diagnose → improve → apply
loop; the agent is the improvement engine (no LLM inside Kitsune).

### OPEN FOLLOW-UPS
- [x] ~~**Open the PR**~~ — done 2026-07-16: **PR #61** (`feat/docker-sandbox-local-servers` → main).
- [x] ~~**Container E2E**~~ — done 2026-07-16 evening: `docker-e2e` CI job runs
  real-daemon E2E on every push (`tests/test_docker_e2e.py`). Its FIRST run
  caught the noexec-tmpfs bug that had silently broken every real sandboxed
  launch (see evening session above).
- [x] ~~sandbox-by-default for `auto()`/community `call()`~~ — done 2026-07-16 (`b30a6e0`, in PR #61).
- [x] **README reposition around the agent-harness loop** — done 2026-07-23:
  hero reframed as agent harness (reach + REPL + try-before-trust); honest
  Who it's for / not for; token math demoted to secondary with pointer to
  benchmarks; GATEWAY/Safety/Why Kitsune + `docs/article.md` + demo cold-open
  aligned. Old token-savings pitch no longer leads.
- [x] ~~regenerate the skills dashboard to list `kitsune-improve`~~ — done 2026-07-16
  (marty-skills `970d8b4`). marty-skills still has unrelated local WIP
  (`jetson-bench-remote/SKILL.md`) — NOT touched.

## SESSION 2026-07-16 — sandbox-by-default on the exec paths + housekeeping (PR #61, pushed, NOT merged)

Continuation of the 2026-07-15 branch. **801 tests pass (+14), ruff clean.**

### Done
- **Removed** two stale root reports (`GROK_BENCHMARK_REPORT.md`,
  `GROK_PRODUCTION_READINESS.md`, Jul-9 / v0.20.8) — deleted at user request.
- **Opened PR #61** — https://github.com/kaiser-data/kitsune-mcp/pull/61
  (9 commits, base `main`, summary + test plan; container-E2E box left open).
- **Regenerated the marty-skills dashboard** — `kitsune-improve` now listed
  (`docs/index.html`, commit `970d8b4`, only that file staged).
- **Sandbox-by-default on `auto()` / `call()` (ad-hoc) / `run()`** — `b30a6e0`:
  - New `_state` helpers: `_sandbox_default_for_exec(explicit, source)` (community
    /`npm`/`pypi`/`github` + unknown-source default on; medium/high-trust exempt;
    explicit `KITSUNE_SANDBOX` still layers on top), `sandboxed_stdio_transport`
    (run()'s ad-hoc path), `transport_for_exec` (auto()/call() routing).
  - **Best-effort** (user-chosen): Docker present → hardened `docker run` wrap
    (creds forwarded by name, same as `sandbox=True`); Docker absent → runs
    uncaged + one-line nudge note (`_UNCAGED_NOTE`), never hard-fails.
  - Key design seam: the **non-wrap path delegates to `_get_transport`** so all
    existing mocks (which patch `_state._get_transport`) still intercept — only
    the actual Docker-wrap bypasses it. Pooled `shapeshift` forms reused by
    `call()` are left as-is (shapeshift already applied policy).
  - `_sandbox_env_names(None)` now guarded (run()/unknown-package pass `srv=None`).
  - Fixed 2 pre-existing `run()` tests (`test_audit_fixes`) that asserted the old
    exact result — now force Docker absent + `startswith`. `tests/test_sandbox_default.py` (+14).
  - CHANGELOG `[Unreleased]` entry added.

### NOT done / next
- **README reposition** (see follow-up above) — the remaining half of pillar #3.
- Session ended at ~90% context / cost-critical; recommend `/compact` before the
  README rewrite. Everything above is committed + pushed — nothing uncommitted in
  KitsuneMCP.

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
