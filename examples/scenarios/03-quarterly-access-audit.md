# Scenario 03 — Quarterly access audit

> *"It's quarter-end. Cross-reference who has prod-write access across Okta,
> AWS IAM, and GitHub. Flag anyone with stale access. Produce a CSV for the
> compliance team."*

This is an auditor-style workflow: many services, each used briefly, with the
output rolled up at the end. Kitsune shines because each service contributes a
small slice of structured data, and at no point does the agent need three
service schemas in context simultaneously.

DNA traits:
- **Surgical** — `list_users`, `list_policies`, `list_team_members` — that's it
- **Cross-domain** — three identity providers
- **High accuracy stakes** — compliance signoff
- (Time-bounded is partial — audits can run long, but the per-server window is
  short.)

## The failure mode — three always-on MCPs

Okta MCP (~30 tools), AWS IAM-specific MCP (~25 tools), GitHub MCP (~50 tools) =
~21K tokens of permanent overhead in every session, including the 99% that
aren't audit work. Plus, with all three loaded, the model is more likely to
pick the wrong "list users" tool — three services each have one.

## The failure mode — CLI-only

The agent shells out to `okta-cli`, `aws iam`, `gh`. Each has its own auth, its
own output format, and its own quirks. The agent has to:

- remember `okta-cli` exists and is installed (rare in training data)
- parse three different output formats
- handle three different pagination styles
- glue them together with `jq` or Python ad hoc

Most agents fall over on the parsing step. The output schemas drift, the model
guesses field names, and the final CSV has wrong columns.

## The Kitsune transcript

```python
# 1. Pull all users from Okta who have the "prod-engineer" group.
shapeshift("okta-mcp", tools=["list_group_members"])
okta_users = call("list_group_members", {
    "group_name": "prod-engineer",
    "fields": ["email", "status", "lastLogin"],
})
# → 47 users — structured list of {email, status, lastLogin}
shiftback()

# 2. Pull AWS IAM users with the "ProdWrite" managed policy attached.
shapeshift("aws-mcp", tools=["list_entities_for_policy"])
iam_users = call("list_entities_for_policy", {
    "policy_arn": "arn:aws:iam::123456789:policy/ProdWrite",
})
# → 31 users with the policy directly or via group
shiftback()

# 3. Pull GitHub members of the "infra" team with admin rights.
shapeshift("github-mcp", tools=["list_team_members"])
gh_admins = call("list_team_members", {
    "org": "acme", "team_slug": "infra", "role": "maintainer",
})
# → 18 maintainers
shiftback()

# 4. Roll up — done locally, no MCP server needed.
# Build a CSV of: email, in_okta, in_iam, in_github, last_login,
# is_stale (last_login > 90 days), needs_review.
#
# The model has structured JSON for all three sources in working memory now.
# No re-parsing of CLI output, no field-name guessing.
```

Three shapeshifts, three calls, three shiftbacks. Final step is pure local
analysis — the model already has the data.

## Token receipts

| Approach | Context overhead at peak |
|---|---:|
| Always-on (Okta + AWS-IAM + GitHub MCPs) | ~21,000 tok |
| CLI fallback | 0 + ~3-5K wasted on format-parsing retries |
| Kitsune | ~400-800 tok per mount, one at a time |

The structured-data-out advantage matters as much as the token math: the model
never has to *parse* CLI output, so the audit logic stays simple.

## What this scenario demonstrates

1. **Multi-service rollup without simultaneous mounting.** Three identity
   providers contribute to one output, but never share the agent's context.
2. **Structured-data interop.** Each MCP returns typed JSON the model can
   merge directly. No CLI output parsing.
3. **Repeatable audit.** The transcript itself is the audit log — every
   read is a named tool call with named args. Compliance-friendly.

## When this pattern is wrong

- **Real-time monitoring across services.** If you need to react every few
  seconds, the mount/unmount latency adds up. Stay mounted.
- **One-service audits.** "Who has GitHub admin?" — just `gh` it. No Kitsune
  needed.
- **You don't trust the underlying MCP server's auth scope.** Kitsune still
  delegates to the server's auth model — `auth("OKTA_API_TOKEN", "...")` has
  whatever scope the token has. Scope-down on the upstream side.
