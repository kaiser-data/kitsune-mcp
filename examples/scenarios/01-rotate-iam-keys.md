# Scenario 01 — Rotate an AWS IAM key

> *"A developer's laptop was stolen overnight. Rotate her IAM access keys
> on the prod account before standup."*

This is the canonical Kitsune scenario. It hits all four DNA traits:

- **Surgical** — uses 4 of the ~9,000 `aws` CLI subcommands
- **Time-bounded** — 30 seconds of actual work, then forgotten
- **High accuracy stakes** — wrong call = security incident
- **Long-tail surface** — outside the model's strong sweet spot for `aws`

## The failure mode — CLI fallback

The agent shells out. The model recalls `aws iam` syntax from training. Long-tail
subcommands are where training-data recall degrades sharply.

```bash
$ aws iam list-access-key --user sarah
# usage: aws [options] <command> <subcommand> [<subcommand> ...] [parameters]
# To see help text, you can run:  aws help
# aws: error: argument operation: Invalid choice, valid choices are: ...
# (list-access-keys — plural — is correct. Model hallucinated singular.)

$ aws iam list-access-keys --user sarah
# usage: aws iam list-access-keys [--user-name <value>] ...
# aws: error: argument --user-name is required
# (--user vs --user-name. Another guess.)

$ aws iam list-access-keys --user-name sarah
# { "AccessKeyMetadata": [ ... ] }
# Finally. Three turns wasted.

$ aws iam update-access-key --user-name sarah \
    --access-key-id AKIAxxxxx --status inactive
# An error occurred (ValidationError) when calling the UpdateAccessKey operation:
# Value 'inactive' at 'status' failed to satisfy constraint:
# Member must satisfy enum value set: [Active, Inactive]
# (Case-sensitive enum. Fourth flag-guess.)
```

Four turns of trial-and-error. ~800-1500 tokens of wasted retries. And this is
on a *common* `aws iam` flow — the failure mode is worse for `aws redshift-data`,
`aws iot-data`, `aws application-autoscaling`, etc.

## The failure mode — always-on MCP server

Mounting the full `aws-mcp` server permanently solves accuracy but at a cost:

- ~200 tools registered → **~12,000 tokens of schema** in every turn's context,
  forever, for the 99% of conversations that have nothing to do with AWS.
- Plus the latency of the host re-validating that surface each turn.

## The Kitsune transcript

```python
# 1. Locate the right server (1 call, ~500 tokens of context).
search("aws iam")
# → aws-mcp | AWS API surface via boto3 | smithery/stdio | ✓ creds set
# → ... 3 more results

# 2. Surgical mount — only the four tools we need.
shapeshift(
    "aws-mcp",
    tools=["list_access_keys", "create_access_key",
           "update_access_key", "delete_access_key"],
    confirm=True,
)
# → Shapeshifted into 'aws-mcp' (lean: 4 tools) — 4 tool(s) registered.
# → ~1,600 tokens added to context (4 × ~400 each)

# 3. Read current state.
call("list_access_keys", {"user_name": "sarah"})
# → AccessKeyMetadata:
#     - AccessKeyId: AKIAOLDKEY...  CreateDate: 2024-08-12  Status: Active
#     - AccessKeyId: AKIANEWKEY...  CreateDate: 2026-04-01  Status: Active

# 4. Deactivate the compromised key (the one tied to the stolen laptop).
call("update_access_key", {
    "user_name": "sarah",
    "access_key_id": "AKIAOLDKEY...",
    "status": "Inactive",     # schema enum: Active | Inactive — validated
})
# → ✓ AccessKey AKIAOLDKEY... marked Inactive

# 5. Hard-delete it after 24h grace (or now, if policy says immediate).
call("delete_access_key", {
    "user_name": "sarah",
    "access_key_id": "AKIAOLDKEY...",
})
# → ✓ AccessKey AKIAOLDKEY... deleted

# 6. Unmount. The 4 tools disappear from context.
shiftback()
# → Shifted back from 'aws-mcp'. Released: aws-mcp (PID 71234)
```

Five tool calls, zero hallucinations, ~1,600 tokens of context overhead for
the 30 seconds the agent was actually doing IAM work.

## Token receipts

| Approach | Context overhead | Wasted retries | Total for this task |
|---|---:|---:|---:|
| Always-on `aws-mcp` (200 tools) | ~12,000 tok every turn | 0 | **~12,000+** per turn × N turns |
| CLI fallback (`aws iam ...`) | 0 | ~800-1,500 tok | **~1,000-2,000**, plus risk |
| Kitsune lean mount (4 tools) | ~1,600 tok (mount → unmount) | 0 | **~1,600** total |

The Kitsune mount pays for itself the moment you cross **one** retry on the
CLI path, and stays cheap regardless of how big the underlying API is —
mounting `tools=[a, b, c, d]` costs the same whether the server has 4 tools or
4,000.

## Accuracy delta

Rough numbers on `aws iam` specifically (sonnet/opus-class models):

- CLI fallback: ~70% first-call success on common verbs, ~30-50% on long-tail.
- Schema-driven MCP call: ~95%+ across the whole exposed surface.

The Kitsune mount inherits the MCP accuracy without inheriting the always-on
schema bill.

## When this pattern is the wrong choice

- **You're going to make 30 IAM calls in a row** (bulk user migration, audit).
  Just `shapeshift("aws-mcp")` (full mount) and stay there. The shiftback
  churn doesn't help when the work is bounded by a single domain.
- **You're in a script / CI pipeline.** Use the AWS CLI with explicit flags;
  no agent in the loop means no hallucination risk to mitigate.
- **The whole agent's job is AWS.** Always-on `aws-mcp` is fine — you're going
  to pay the schema bill on every task anyway.

## What this scenario demonstrates

1. **On-demand mounting changes the unit of cost** from "the size of the API
   surface" to "the number of operations you actually need."
2. **Surgical `tools=[...]` lean mounts** make the cost independent of server
   size — a 4-tool slice of a 4,000-tool server costs the same as a 4-tool
   server.
3. **Schema validation eliminates a whole class of CLI failure** (singular vs
   plural flags, case-sensitive enums, version-drift flag renames) without
   requiring the agent to be omniscient about every CLI it might touch.
