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

### npm — ⚠️ stale at 0.20.1 (the real gap)
- `npx kitsune-mcp` resolves to **0.20.1**; PyPI is 7 patch releases ahead.
- The npm job in `publish.yml` is gated behind a `workflow_dispatch` input
  ("Also publish to npm — needs one-time Trusted Publisher on npmjs.com"), so tag pushes do
  NOT publish npm automatically.
- To ship npm: (1) one-time — configure a Trusted Publisher for `kitsune-mcp` on npmjs.com
  pointing at this repo's `publish.yml`; (2) run the workflow via `workflow_dispatch` with the
  npm flag enabled (or `gh workflow run publish.yml -f npm=true`). MCP Registry publish is
  similarly gated and needs both PyPI + npm live first.

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
