# Scenario 02 — Incident response sweep

> *"3:14am. PagerDuty fires. p99 latency on checkout-api crossed 1.2s
> for 5 minutes. Triage, ack, post a postmortem stub before going back to bed."*

This scenario showcases Kitsune as a **cadence-changer**: the agent picks up
exactly the right capability for the next 60 seconds, then drops it. Across a
single 5-minute incident, the agent might shapeshift 4 different times — into
4 different services — and never carry more than one server's schemas at once.

DNA traits:
- **Surgical** — one or two tools from each of 4 unrelated services
- **Time-bounded** — minutes per mount
- **Cross-domain** — Datadog, PagerDuty, GitHub, Slack all involved
- (Long-tail isn't the dominant trait here — accuracy comes from never having
  all four schemas in the same context, not from API obscurity.)

## The failure mode — always-on bloat

Loading all four MCPs permanently:

| Server | Tools | ~Tokens |
|---|---:|---:|
| datadog-mcp | ~40 | 8,000 |
| pagerduty-mcp | ~30 | 6,000 |
| github-mcp | ~50 | 10,000 |
| slack-mcp | ~25 | 5,000 |
| **Total** | **~145** | **~29,000** |

29K tokens of permanent context overhead, in every session, for the 99% of
sessions that aren't incident response. That's a *lot* of room you're not
giving the model for actual reasoning.

## The Kitsune transcript

```python
# 1. PagerDuty fires. Agent receives the alert.
shapeshift("pagerduty-mcp", tools=["get_incident", "acknowledge_incident"])
incident = call("get_incident", {"incident_id": "PXYZ123"})
# → Service: checkout-api  Severity: high  Triggered: 3:14am
#   Summary: p99 latency > 1.2s for 5 minutes (threshold 800ms)

call("acknowledge_incident", {"incident_id": "PXYZ123"})
# → ✓ Acknowledged. Paging suppressed for 30 min.
shiftback()

# 2. Datadog — pull the metric for the past hour.
shapeshift("datadog-mcp", tools=["query_metrics", "list_logs"])
call("query_metrics", {
    "query": "p99:trace.http.request{service:checkout-api}",
    "from": "now-1h", "to": "now",
})
# → 03:09  812ms  ▁
#   03:11  1.42s  ▆  ← spike start
#   03:14  1.81s  █  ← page fired
#   03:16  1.43s  ▆

call("list_logs", {
    "query": "service:checkout-api status:error",
    "from": "now-1h", "limit": 10,
})
# → 5 errors, all "stripe.connect_timeout" — downstream dependency
shiftback()

# 3. GitHub — file the post-mortem stub linked to the deploy log.
shapeshift("github-mcp", tools=["create_issue", "search_commits"])
call("search_commits", {
    "owner": "acme", "repo": "checkout-api",
    "query": "merged:>=2026-05-16T02:00", "per_page": 5,
})
# → No commits in the last 4h.  Symptom is not deploy-induced.

call("create_issue", {
    "owner": "acme", "repo": "checkout-api",
    "title": "Incident PXYZ123 — checkout-api p99 > 1.2s, Stripe connect timeouts",
    "body": "## Auto-summary\n- Page: 03:14\n- Metric: p99 1.42s (threshold 800ms)\n- Logs: 5 stripe.connect_timeout in last hour\n- Deploy history: no commits in 4h\n\n## Next steps\n- [ ] Check Stripe status page\n- [ ] Verify upstream rate-limit headers",
    "labels": ["incident", "postmortem-stub"],
})
# → ✓ Issue #4421 created
shiftback()

# 4. Slack — drop the issue link in #oncall.
shapeshift("slack-mcp", tools=["post_message"])
call("post_message", {
    "channel": "#oncall",
    "text": "PXYZ123 ack'd — see github.com/acme/checkout-api/issues/4421 — looks like Stripe upstream, not us. Going back to bed.",
})
shiftback()
```

Four servers, eight tool calls, ~4 minutes wall clock. Context overhead at
any one moment: **~2-3K tokens** (one server's lean mount), not 29K.

## Token receipts

| Approach | Steady-state context | Total tokens spent on this incident |
|---|---:|---:|
| Always-on (all 4 MCPs) | ~29,000 tok every turn | ~29K × 8 turns ≈ **232K tokens** |
| Kitsune sweep | ~2-3K (one server at a time) | ~16K total (mounts + calls) |

That's an order-of-magnitude difference for a single incident. Multiply across
the year and a single oncall engineer using always-on MCPs is burning hundreds
of millions of tokens on schemas that aren't being used.

## What this scenario demonstrates

1. **Cross-domain agility without context bloat.** Four unrelated services in
   one session, none of them resident.
2. **The model's working memory stays focused.** While drafting the GitHub
   issue body, the agent isn't being distracted by Datadog's 40 tool schemas.
   Better tool selection inside each step.
3. **Audit trail is implicit.** Each `shapeshift()` → `shiftback()` pair is a
   visible boundary of which service was touched when. Easier to review later.

## When this pattern is wrong

- **You're going to live in Datadog for an hour.** Stay shapeshifted — don't
  shiftback after every query.
- **You actually want the always-on context.** If the agent's job is "watch
  every incident across every service," permanent mounting is fine — you're
  paying the schema bill on every task anyway.
