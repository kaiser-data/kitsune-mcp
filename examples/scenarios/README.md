# Scenarios — when Kitsune changes agent behavior

This folder collects real-world tasks where Kitsune's on-demand mount loop
(`search` → `shapeshift` → `call` → release) changes agent behavior compared
with the two common alternatives:

1. **Always-on MCP servers** — everything preconfigured (or deferred via Tool Search
   if already in config).
2. **CLI fallback** — agent shells out to `aws`, `gcloud`, `gh`, `kubectl` etc.
   and relies on training-data recall of flag syntax.

Kitsune shines when the server isn't already in config, the API surface is
long-tail / high-stakes, or you need to try community code without a permanent
install. Token deltas vs fully-mounted always-on are a secondary receipt — not
the primary reason to use the pattern.

## The pattern

A task is a good fit for Kitsune when it scores **3 of 4** on this DNA check:

| Trait | Why it matters |
|---|---|
| **Surgical** — uses a tiny slice of a large API surface | Schema mounting is cheaper than always-on |
| **Time-bounded** — minutes, not the whole session | `shiftback()` reclaims the context |
| **High accuracy stakes** — wrong call = real cost | MCP's schema validation beats CLI flag-guessing |
| **Long-tail surface** — outside the model's training-data sweet spot | Where CLI hallucination is worst |

The canonical example — rotating an AWS IAM key — hits all four. The scenarios
below all hit at least three.

## Scenarios

| # | Scenario | DNA traits |
|---|---|---|
| 01 | [Rotate an AWS IAM key](./01-rotate-iam-keys.md) | Surgical · Time-bounded · High-stakes · Long-tail |
| 02 | [Incident response sweep](./02-incident-response-sweep.md) (Datadog → PagerDuty → GitHub → Slack) | Surgical · Time-bounded · Cross-domain |
| 03 | [Quarterly access audit](./03-quarterly-access-audit.md) (Okta → AWS IAM → GitHub) | Surgical · Cross-domain · High-stakes |
| 04 | [Workspace switching](./04-workspace-switching.md) (Notion personal ↔ team) | Time-bounded · Identity boundary |
| 05 | [Try-before-you-trust](./05-try-before-you-trust.md) MCP server evaluation | Time-bounded · Sandboxed |
| 06 | [Capability-gated agent](./06-capability-gated-agent.md) (read-only by default, write on confirm) | Surgical · High-stakes · Security |
| 07 | [Internal MCP gateway](./07-internal-mcp-gateway.md) (company-private tools, on-demand) | Time-bounded · Enterprise |

## What makes a scenario worth writing

Each scenario should answer four questions concretely:

1. **What does the failure mode look like without Kitsune?** Show a literal
   transcript of CLI hallucination or always-on bloat.
2. **What does the Kitsune transcript look like?** Real tool calls, no
   pseudocode.
3. **What are the token receipts?** Baseline vs always-on vs Kitsune.
4. **When is this the wrong pattern?** Honest anti-example. Trust comes from
   ruling things out.

## When *not* to use Kitsune

These belong in the scenarios for honesty, not as filler:

- **You make 50+ calls to one server in a row.** Just shapeshift once and stay
  there. The mount cost amortizes; the shiftback churn doesn't help.
- **The server is your primary workflow.** GitHub MCP in a project where every
  task touches GitHub — keep it always-on, accept the ~10K token bill.
- **Headless CI / scripts.** No MCP host. Use the CLI.
- **Latency-critical paths.** Cold shapeshift = 1-15s. If you need sub-second,
  pre-mount or use the CLI.
