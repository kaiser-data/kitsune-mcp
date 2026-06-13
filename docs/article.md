# The Tool Tax: Why Your AI Agent Pays for Tools It Never Uses

*A technical write-up of Kitsune MCP — what it does, the honest numbers, and what I got wrong the first time.*

---

## The problem nobody prices

The Model Context Protocol (MCP) made it trivial to give an AI agent tools: a GitHub server, a filesystem server, a Notion server, a web-search server. Add them to your config, restart the client, done.

What the config screen doesn't show you is the bill. **Every MCP server you connect injects all of its tool schemas into the model's context on every single turn** — names, descriptions, JSON Schemas for every parameter — whether the current message uses that server or not. A mid-sized GitHub server is ~4,200 tokens. Five typical servers is ~25,000 tokens. That rides along on *every* message in the conversation.

And it's not only a token bill. There's a measured accuracy cost. When a model has to select from a large catalog of tools instead of a small retrieved subset, tool-selection accuracy drops — Patil et al.'s Gorilla work (2023) and related retrieval studies put the degradation at 20–40% on large surfaces. The fix for *that* isn't a bigger model; it's a smaller menu.

So you pay twice: tokens on every turn, and worse decisions when it matters.

## The hub model

Kitsune MCP is a single MCP server that sits between your client and the entire ecosystem. You put **one** entry in your config. Behind it sit 130,000+ servers across the official registry, Smithery, npm, PyPI, and Glama — reachable on demand, none of them loaded until you ask.

The core verb is `shapeshift()`: mount a server's tools at runtime, use them, then release them so the context returns to baseline.

```python
status()                                               # what am I paying for right now?

shapeshift("github", tools=["search_repositories"])    # mount ONE tool, not all 26
call("search_repositories", {"query": "mcp servers"})  # real call, real data
shapeshift()                                            # release — tools gone, process killed
```

Don't know which server you need? `auto()` does discovery, ranking, and the call in one step:

```python
auto("what time is it in Tokyo")
auto("search the web for the latest python release")   # routes to a real web-search server
```

That's the whole idea: **a lean agent that reaches the entire ecosystem, but only ever holds the tools the current task needs.**

## The honest numbers

Here's where I have to correct my own earlier marketing, because the first version of this story was inflated — and the real numbers are still good enough that the honesty costs nothing.

**Kitsune is not free at rest.** It is itself an always-on MCP server. Its six lean-profile tools (`status`, `search`, `shapeshift`, `call`, `auto`, `auth`) cost **~1,321 tokens** in every turn, measured, whether you use them or not. That is a fixed floor — it never drops to zero. Any comparison that hides this floor is lying to you.

The win isn't that Kitsune is weightless. It's that **the floor stays flat while always-on servers stack linearly.** Every figure below already includes the 1,321-token floor:

| Always-on servers | Always-on / turn | Kitsune / turn | Saved |
|---|---:|---:|---:|
| GitHub (26 tools) | 4,229 | ~1,621 | **62%** |
| GitHub + filesystem + git | 8,678 | ~1,631–2,011 | **77–81%** |
| Notion + GitHub + filesystem + git + memory | 25,000 | ~1,631–3,271 | **87–93%** |

And the break-even, stated plainly: **if you only ever run one small server** — say `mcp-server-time` at ~261 tokens — always-on is *cheaper* than Kitsune's 1,321 floor. Kitsune pays off the moment the always-on alternative exceeds that floor: one medium server, or two-plus small ones. The bigger and more numerous your servers, the bigger the win.

That break-even note is the part most "10x token savings!" pitches leave out. Including it is the difference between a benchmark and an honest tool.

## "But the CLI is free at rest too"

A fair objection: shelling out to `aws`, `gh`, or `kubectl` from a Bash tool also costs ~0 tokens at rest. So why MCP at all?

Because long-tail CLI commands fail. LLMs have excellent recall on the top ~20 commands of a CLI they've seen in training (`git status`, `gh pr list`) and steeply degraded recall on everything else. For a surface the size of `aws` (~9,000 subcommands), first-call success on long-tail operations drops to 30–50% — wrong flag names, singular-vs-plural verbs, case-sensitive enums, silently-deprecated options. Each miss costs a retry turn, and the worst failures aren't errors — they're *plausible-looking wrong calls that succeed.*

That's the structural argument for the hub: **CLI-cheap at rest, schema-validated when accuracy matters.** For a one-off on a CLI the model knows cold, `gh` is fine. For unfamiliar APIs, internal tooling, or any operation where a wrong call has real cost — production infra changes, billing, security flows — schema validation without the always-on tax is the point.

## What's under the hood

A few things I think are worth a developer's attention:

- **Intent-aware routing.** `auto()` without a server hint used to misroute "search the web" tasks to fetch tools and chat-forwarders — anything whose description happened to contain "search." It now strips generic intent verbs from the registry query and filters candidates to those that actually advertise a matching capability, so a search task routes to a search server, not a URL-fetcher.
- **Real OAuth, real logout.** Servers behind OAuth 2.1 (Notion, etc.) get full Dynamic Client Registration + PKCE. `auth(server, "logout")` doesn't just delete the local token — it hits the provider's RFC 7009 revocation endpoint and forces a genuine browser re-login on the next auth, so workspace switching actually works. (I verified this end-to-end against live Notion; the subtle trap was that Notion re-issues tokens with a *stable prefix*, so "same prefix" looked like "didn't log out" when in fact a fresh token had been minted. Verify by expiry, not by eyeballing the prefix.)
- **Surgical mounting.** `shapeshift("github", tools=["search_repositories"])` mounts one tool out of twenty-six. You're not trading "all of GitHub" for "none of GitHub" — you take exactly the slice the task needs.
- **It's tested.** 683 tests, and I smoke-test the live tool surface (discover → mount → call → unmount) against the running server, not just the unit suite.

## Try it

```bash
pip install kitsune-mcp
```

Add one entry to your MCP config:

```json
{ "mcpServers": { "kitsune": { "command": "kitsune-mcp" } } }
```

Restart your client and run `status()`. It'll show you what your *other* servers are costing you right now — which, the first time, is usually the moment the whole thing clicks.

Source, issues, and the full token methodology: **github.com/kaiser-data/kitsune-mcp**
