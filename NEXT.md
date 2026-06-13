# What's next — post v0.20.7

_Last updated: 2026-06-09. Running MCP confirmed on v0.20.7._

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
