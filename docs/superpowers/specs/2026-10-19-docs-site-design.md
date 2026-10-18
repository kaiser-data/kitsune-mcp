# Docs site and homepage — design

Date: 2026-10-19 · Status: approved by the user in chat

## Goal

Give Kitsune MCP a professional homepage and documentation site, and point
PyPI, npm, the MCP Registry and the GitHub repo at it. Adoption is the
bottleneck (0 stars); the site exists to turn a PyPI/HN/LinkedIn visitor into
an installer and a star.

## Decisions

- **Host:** GitHub Pages at `https://kaiser-data.github.io/kitsune-mcp/`,
  deployed by GitHub Actions on every push to `main`. A custom domain can be
  added later without changing the build.
- **Tool:** MkDocs Material. One system for homepage and docs; Python, so it
  fits the repo. Dependencies live in a `docs` dependency group in
  `pyproject.toml`, so the published package does not change.
- **Content:** refine the existing `docs/` (approx. 1,500 lines) rather than
  rewrite. Fix stale API names against the current tool surface.

## Homepage (`/`)

Custom template (`overrides/home.html`), not a docs page:

1. Hero: logo, "Let your agent test the MCP server it's building", the demo
   GIF, install tabs (Claude Code / other clients / pip / npx), buttons
   "Get started" and "Star on GitHub".
2. Three cards: MCP REPL (hot-reload), borrow a server from 7 registries,
   try community code caged in Docker.
3. "When not to use it" (from the README).
4. Footer links: PyPI, npm, MCP Registry, license.

The GIF is referenced by its raw GitHub URL (`docs/demo-hot-reload.gif`,
added in PR #74).

## Navigation

- **Get started:** Installation, Quickstart, Hot-reload tutorial
- **Guides:** Agent patterns, Configuration, Transports, Safety, Performance
- **Reference:** Tools, Client compatibility, Benchmarks
- **Project:** Changelog, Contributing, Security

Not published: `docs/internal/`, `docs/superpowers/`, `docs/article.md`,
`docs/demo-script.md`, `docs/demo-realtime.md` (marketing/internal drafts).

## Metadata

`Homepage` and `Documentation` URLs in `pyproject.toml`, `homepage` in
`package.json`, `websiteUrl` in `server.json`, and the GitHub repo homepage
point at the site. PyPI picks these up with the next release.

## Verification

- `mkdocs build --strict` passes locally and in the deploy workflow (broken
  links fail the build).
- Every code example on the site uses tools that exist in the current tool
  surface (`kitsune_mcp/tools/`).
- Rendered pages checked by screenshot in light and dark mode at desktop and
  phone width.

## Out of scope

Custom domain, blog, versioned docs, i18n.

## Needs the user

- Enabling GitHub Pages with source "GitHub Actions" (one `gh api` call, needs
  approval).
- Uploading the social preview image (browser only).
