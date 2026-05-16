# Scenario 07 — Internal MCP gateway (enterprise on-demand tools)

> *"Our platform team built MCP servers for our internal billing system,
> our feature-flag service, our deploy pipeline, and our incident tracker.
> Engineers want them available — but not always-on, because every engineer
> uses a different subset on a different day."*

This is the enterprise pitch: Kitsune as a single entry point to a fleet of
**internal, company-private** MCP servers, mounted only when needed. Same
model as the Glama / Smithery story, but the catalog is your own.

DNA traits:
- **Surgical** — engineers use a couple of tools at a time across the fleet
- **Time-bounded** — internal tools are typically per-task
- **Cross-domain** — billing, deploys, flags, incidents — all separate domains
- **Enterprise scale** — N teams × M servers compounds the always-on bill fast

## The failure mode — N servers × M engineers always-on

Suppose your platform team builds 10 internal MCP servers. Each engineer's
client config registers all of them, because they might need any of them.
Each server has ~20 tools at ~200 tokens of schema each. Per-engineer math:

```
10 servers × 20 tools × 200 tokens = 40,000 tokens
```

40K tokens of constant overhead, on every engineer's session, every turn —
for tools that any given engineer touches 0-2 of per day. Across a 1,000-eng
org running 5 sessions/day, that's 200M tokens of pure schema overhead
**per day**, never used.

## The failure mode — no MCP, just CLIs

Internal tooling rarely has the polish of `gh` or `aws`. The model has never
seen `acme-deploy` or `acme-flags` in training. CLI hallucination is at its
worst here — the success rate drops to single digits for unfamiliar internal
CLIs.

## The Kitsune transcript

Set up: one entry in every engineer's client config — `kitsune-mcp` — and one
internal registry endpoint (`KITSUNE_INTERNAL_REGISTRY=https://mcp.acme.com`).
Now every engineer has access to all 10 internal servers, paying schema cost
only for the ones they actually use.

```python
# Engineer A — flag debugging
search("feature flag")
# → acme-flags-mcp | internal | ✓ creds set
shapeshift("acme-flags-mcp", tools=["get_flag_state", "list_overrides"])
call("get_flag_state", {"flag": "checkout_v2", "env": "staging"})
shiftback()

# Engineer B — billing question
shapeshift("acme-billing-mcp", tools=["get_customer_invoice"])
call("get_customer_invoice", {"customer_id": "cus_abc123"})
shiftback()

# Engineer C — deploy log lookup
shapeshift("acme-deploy-mcp", tools=["get_deploy_log"])
call("get_deploy_log", {"service": "checkout-api", "env": "prod", "last": 5})
shiftback()
```

Three engineers, three internal tools, **none of them load the other 9 servers**.

## Token receipts

| Approach | Per-engineer steady state | Org-wide daily |
|---|---:|---:|
| All 10 internal MCPs always-on | ~40K tok / turn | hundreds of millions / day |
| Kitsune lean mount | ~400-800 tok during use, 0 otherwise | dominated by actual work |

## What this scenario demonstrates

1. **The "registry of registries" pattern.** Your internal MCP fleet becomes
   discoverable via `search()` exactly like the public Glama / Smithery
   catalogs. Engineers don't memorize URLs or server IDs.
2. **Onboarding flattens.** A new engineer's setup is one MCP entry, not
   ten. Adding a new internal server doesn't require every engineer to edit
   their config.
3. **Security and audit at the gateway.** All internal tool calls go through
   Kitsune — easy to plug in centralized auth (SSO), per-tool rate limits,
   and structured audit logs without modifying each downstream server.

## Architecture sketch

```
engineer-client (Cursor, Claude, ...)
       │
       └─→ Kitsune MCP (single config entry)
                │
                ├─ KITSUNE_INTERNAL_REGISTRY = https://mcp.acme.com
                │       │
                │       └─→ catalog of {acme-billing-mcp, acme-deploy-mcp, ...}
                │
                └─ (also serves public Smithery / Glama / npm / pypi via the
                   normal registry stack)
```

The internal registry exposes the same JSON shape the public registries do.
Kitsune doesn't care that it's internal — it's just another upstream source.

## When this pattern is wrong

- **A single internal tool dominates every workflow.** If 90% of every
  session touches `acme-deploy-mcp`, just put it directly in everyone's
  config. The hub indirection isn't earning its keep.
- **Your tools have heavy session state.** Tools that depend on prior calls
  in the same connection lose continuity across shiftback. Use `connect()` to
  hold a persistent connection across mounts.
- **Compliance forbids dynamic mounting.** Some regulated environments require
  the toolset to be statically declared in config. In that case, statically
  declare the subset of internal MCPs each role needs and skip the gateway.

## Procurement angle

This is also where Kitsune compounds: the security review for "add one MCP
entry to every engineer's IDE" is one review. The security review for "add
ten MCP entries, on a rolling basis, every quarter" is ten reviews. The
gateway model trades runtime indirection for a *flat onboarding/approval
cost*. That's usually the deciding factor in enterprise rollouts.
