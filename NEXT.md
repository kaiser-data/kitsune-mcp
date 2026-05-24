# What's next — post v0.20.7

_Last updated: 2026-05-24. Running MCP confirmed on v0.20.7._

## Blocking / ship-critical

### 1. PyPI publish is broken — v0.20.6 and v0.20.7 are NOT on PyPI
- `~/.pypirc` holds a **project-scoped token for a different project**; upload 403s with
  `Invalid API Token: project-scoped token is not valid for project: 'kitsune-mcp'`.
- Consequence: `pip install kitsune-mcp` / `uvx kitsune-mcp` / `npx kitsune-mcp` users are
  still on **0.20.5** and do NOT have the process-tree kill (#zombie) or the four issue fixes.
- Fix: generate a project-scoped token for `kitsune-mcp` at
  https://pypi.org/manage/account/token/, replace the `password` under `[pypi]` in `~/.pypirc`,
  then:
  ```
  python3 -m build
  python3 -m twine upload dist/kitsune_mcp-0.20.7*
  ```
- npm publish (`package.json` 0.20.7) and MCP Registry (`server.json` 0.20.7) also still need
  pushing once PyPI is green.

## Follow-ups from the v0.20.5 issue audit

### 2. #44 is only half-fixed — Smithery mounts still show `arguments={}`
- Root cause confirmed: Smithery's registry listing returns `inputSchema` with `type` +
  `properties` but **no `required` array** (verified for `@upstash/context7-mcp`:
  `resolve-library-id`, `query-docs` both have `required: None`).
- The v0.20.7 hint loop fills every entry in `required` — works for official/stdio servers
  (verified: `server-memory` hint correctly shows `{'entities': []}`), but Smithery servers
  have an empty `required`, so the hint stays `{}`.
- Decision needed (pick one):
  - **(a)** When `required` is absent but `properties` exist, fetch the live schema via
    `transport.list_tools()` before building the hint. Most correct; adds one round-trip to
    Smithery mounts. Recommend gating it to *only* the hint path (don't slow proxy registration).
  - **(b)** Fall back to showing all `properties` keys with a note like
    `# params: query, libraryName (see inspect())` — cheap, but can't distinguish required
    from optional.
  - **(c)** Omit the example line entirely when `required` can't be determined.
- Recommendation: (a), since the live `list_tools()` schema is the source of truth the proxy
  already routes against.

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
