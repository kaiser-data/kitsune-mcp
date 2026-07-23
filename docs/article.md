# Reach Without Restart: What Kitsune MCP Is Actually For

*A technical write-up of Kitsune MCP — the agent harness pitch, the honest limits, and what I got wrong the first time.*

---

## The problem that still isn't solved

The Model Context Protocol made it trivial to give an AI agent tools: add a server to your config, restart the client, done.

What that workflow still cannot do:

1. **Reach a server you've never configured** without editing JSON and restarting (and losing the session).
2. **Iterate on a server you're writing** without the same restart loop on every schema change.
3. **Try community MCP code** without permanently wiring arbitrary packages into your always-on tool surface.

Native Tool Search (Claude Code 2.1.7+) already defers schemas for *configured* servers — so "save tokens by not loading GitHub's 26 tools every turn" is largely a solved client problem. Kitsune does not win by competing with Tool Search. It wins by covering the servers Tool Search never sees.

## The harness model

Kitsune is a single always-on MCP gateway. One config entry. Behind it: 130,000+ servers across official registries, Smithery, npm, PyPI, and Glama — reachable on demand, none of them loaded until you ask.

The core verb is `shapeshift()`: mount a server's tools at runtime, use them, release them.

```python
status()                                               # what form am I in?

shapeshift("github", tools=["search_repositories"])    # mount ONE tool, not all 26
call("search_repositories", {"query": "mcp servers"})  # real call, real data
shapeshift()                                            # release — tools gone, process killed
```

Don't know which server you need? Prefer `search()` first, or `auto(..., server_hint=...)` when you already know the id:

```python
auto("current time in Tokyo", server_hint="mcp-server-time")
```

That's the idea: **an agent that can borrow any MCP capability mid-session — then put it back.**

## Three things that shine

| | Loop | Why it matters |
|---|---|---|
| **MCP REPL** | `connect` → edit → `reload` → `call` | Develop your own server without restarting the client (all lean tools) |
| **Long-tail reach** | `search` → `shapeshift` → `call` → drop | One-offs without permanent config |
| **Try-before-you-trust** | `confirm=True` + optional `sandbox=True` + TOFU pins | Community catalog without blind always-on installs |

## The honest numbers (secondary)

Kitsune is **not free at rest**. Its nine lean tools cost **~1,685 tokens every turn**. Against a client with native deferral, that floor is *additive* — do not install Kitsune to save tokens.

Where token math still applies: comparing against **fully-mounted always-on** stacks, or clients without Tool Search. Full tables: [`benchmarks.md`](./benchmarks.md) and the README Performance section.

**Break-even (always-on, no deferral):** one small server (e.g. time ~261 tokens) is cheaper always-on than Kitsune's floor. Kitsune pays off once the alternative exceeds ~1,685 tokens.

## "But the CLI is free at rest too"

Fair. Shelling out to `aws` / `gh` / `kubectl` also costs ~0 at rest.

Long-tail CLI commands still fail. Models nail the top ~20 trained commands and degrade hard elsewhere — wrong flags, silent wrong success. MCP schemas fix that; Kitsune mounts those schemas only while you need them, without a restart to add the server.

## What's under the hood (worth a developer's attention)

- **Surgical mounting.** `shapeshift("github", tools=["search_repositories"])` — one tool out of twenty-six.
- **Real OAuth + logout.** OAuth 2.1 + PKCE; `auth(server, "logout")` hits RFC 7009 revocation.
- **Docker sandbox for community mounts.** `sandbox=True` / `KITSUNE_SANDBOX=community` — not a marketing checkbox; read the Safety model limits.
- **Tested.** Large pytest suite + live smoke of discover → mount → call → unmount.

## Who should skip it

- You only need a few trusted always-on servers → configure them natively.
- Unattended prod with admin/billing credentials → don't (default local mode = your user permissions).
- Sub-second path → cold mount is seconds; prewarm or always-on.

## Try it

```bash
pip install kitsune-mcp
```

```json
{ "mcpServers": { "kitsune": { "command": "kitsune-mcp" } } }
```

Restart your client and run `status()`. Then `search` for something you've never installed — that's the moment it clicks.

Source: **github.com/kaiser-data/kitsune-mcp**
