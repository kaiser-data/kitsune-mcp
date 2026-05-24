# What's next — post v0.20.7

_Last updated: 2026-05-24. Running MCP confirmed on v0.20.7._

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

### npm — ⚠️ stale at 0.20.1 — BLOCKED on one-time npmjs.com setup (user action)
- `npx kitsune-mcp` resolves to **0.20.1**; PyPI is 7 patch releases ahead.
- Triggered `gh workflow run publish.yml -f publish_npm=true` (run 26371569186, 2026-05-24).
  The npm job failed at publish with:
  ```
  npm error 404 Not Found - PUT https://registry.npmjs.org/kitsune-mcp
  The requested resource 'kitsune-mcp@0.20.8' could not be found or you do not
  have permission to access it.
  ```
  Provenance signed fine (sigstore logIndex 1625051052); the 404-on-PUT is npm's
  misleading "OIDC rejected — no Trusted Publisher registered" error. No token is used.
- **Fix (only the package owner can do this, web UI):**
  1. https://www.npmjs.com/package/kitsune-mcp/access → **Trusted Publisher** / Publishing access.
  2. Add GitHub Actions publisher:
     - Organization or user: `kaiser-data`
     - Repository: `kitsune-mcp`
     - Workflow filename: `publish.yml`
     - Environment: **leave blank** (the npm job in publish.yml declares no `environment:`).
  3. Re-run: `gh workflow run publish.yml -f publish_npm=true`
- After npm is live, MCP Registry publish (also gated) can run:
  `gh workflow run publish.yml -f publish_registry=true` (needs both PyPI + npm entries live).

## Follow-ups from the v0.20.5 issue audit

### 2. ✅ DONE in v0.20.8 — #44 completed for Smithery servers
- Implemented option (a): `_commit_shapeshift` refetches the live schema via
  `transport.list_tools()` when the registry listing is thin (`_schemas_missing_required`).
  Fixes both proxy registration and the hint. 2 tests added; verified live against context7.

### 3. #43 logout — unit-tested, not yet live-verified end-to-end
- Code + 5 unit tests landed (RFC 7009 revoke + `prompt=login` flag). Needs one real
  OAuth round-trip to confirm the browser actually re-prompts:
  `auth("notion-hosted")` → `auth("notion-hosted", "logout")` → `shapeshift("notion-hosted")`
  should open a browser, not silently reuse `fe5fb9ad…`.

### 4. #34 — auto() capability filter (commented, not implemented)
- Added the `taskSupport: required ⊄ client_capabilities` filter idea as a comment on #34.
- Still open: the ranker does not deprioritize servers whose declared required features the
  connecting client can't satisfy. `auto("search the web …")` without a hint still risks
  routing to `simulate-research-query`.

## Docs polish (non-blocking)

### 5. README example-block "Peak" comments omit the floor
- Lines ~336–361 show surgical-mount-only figures (e.g. `# Peak: ~1,300 tokens vs 6,516
  always-on`). These exclude the ~1,321 floor, so they understate true context. Either add the
  floor or relabel as "mount cost" for consistency with the now-honest baseline framing.

### 6. token-cost SVG vs README Performance table drift
- SVG (`docs/token-cost-{light,dark}.svg`) multi-server saved labels are 62 / 74–81 / 89–94.
- README Performance table (corrected this session) is 62 / 77–81 / 87–93.
- Minor; reconcile the SVGs to the recomputed table next time the graphics are regenerated.

## Done this session (v0.20.7, verified live on running MCP)
- ✅ #42 savings counter — `status()` now shows `~2,661 tokens [1 mounted server(s) + 2
  inspected schema(s)]` after a single memory mount (was stuck at ~46).
- ✅ #45 HTTP unmount — no more "pool key missing" warning (context7 + memory unmounts clean).
- ✅ #44 for official/stdio servers — `server-memory` hint shows `{'entities': []}`.
- ✅ README baseline framing rewritten to be explicit that Kitsune has a fixed ~1,321-token
  floor (never zero), with a break-even note and corrected Performance tables.
