# Scenario 06 — Capability-gated agent (read-by-default, write-on-confirm)

> *"My support agent should be able to look up any customer in our database.
> It should NOT be able to delete or modify rows unless I explicitly confirm
> the operation. And I want that boundary enforced at the tool layer, not
> just in the system prompt."*

System prompts that say "do not delete" are a wish, not a guarantee. The model
*can* still call `delete_row` — it's just trying not to. Kitsune lets you make
the wish structural: the destructive tools aren't even in the agent's context
until the user explicitly authorizes them.

DNA traits:
- **Surgical** — read tools always available, write tools mounted on demand
- **High accuracy stakes** — destructive operations
- **Security boundary** — capability separation enforced at runtime
- (Time-bounded comes for free — the write window auto-closes on `shiftback()`.)

## The failure mode — prompt-only gating

```
SYSTEM: You are a support agent. Never delete or modify customer data.
Always confirm destructive operations with the user before running.

USER: Sarah's account is wrong, can you fix her email to s@new.com?

MODEL: <calls update_user(email="s@new.com")>
```

The model genuinely tried to be helpful. The system prompt said "always
confirm," but the user phrasing implied consent ("can you fix..."). The
guardrail leaked. This is the well-documented "prompt injection / jailbreak /
overhelpful agent" failure mode — orthogonal to safety training.

## The failure mode — always-on with write tools

If both `get_user` and `delete_user` are in context, the model can call either
at any time. The only barrier is its own restraint, which is unreliable under
adversarial or confused prompts.

## The Kitsune transcript

```python
# 1. Start the session with READ-ONLY mount.
shapeshift("postgres-mcp", tools=["select_query", "describe_table"])
# → 2 tool(s) registered: select_query, describe_table
# The agent literally cannot call delete_query or update_query — they aren't
# in its menu.

# 2. Normal operation — read-only is fine.
call("select_query", {
    "sql": "SELECT id, email, status FROM users WHERE email = 's@old.com'",
})
# → {id: 4421, email: "s@old.com", status: "active"}

# 3. User asks for a write. The agent CANNOT execute it.
# Instead, it surfaces an explicit confirmation step:
#
#   AGENT: "I can update Sarah's email from s@old.com to s@new.com. This
#           requires write access, which is currently disabled. Reply
#           'authorize update' to enable the write tools for this operation."

# 4. User confirms. Only now does the agent mount write capability.
#    Critically: this is a NEW shapeshift, not an upgrade — the schema for
#    the write tool only enters context after user authorization.
shapeshift("postgres-mcp", tools=["update_query"])
# → Previous form's tools dropped. 1 tool(s) registered: update_query

call("update_query", {
    "sql": "UPDATE users SET email = 's@new.com' WHERE id = 4421",
})

# 5. Immediately drop back to read-only.
shapeshift("postgres-mcp", tools=["select_query", "describe_table"])
# → write tools removed from context
```

The write capability has a *temporal* boundary: it existed for exactly one
operation, by explicit user authorization, and was then taken away.

## Token receipts

This isn't primarily a token story — it's a *capability* story. But for
completeness:

| Phase | Tools in context | Tokens |
|---|---|---:|
| Read phase | select_query, describe_table | ~600 |
| Write phase (user-authorized, ~30s) | update_query | ~300 |
| Back to read phase | select_query, describe_table | ~600 |

vs. always-on with all 6 postgres tools: ~1,800 tokens of permanent context,
and the model can call any of them at any time.

## What this scenario demonstrates

1. **Schema-level capability enforcement.** Tools that aren't mounted cannot
   be called. Period. No prompt-injection bypass, no model overconfidence.
2. **Authorization is a tool call.** The user's "authorize update" sentence
   triggers an explicit `shapeshift(tools=[...])` — visible in the audit log.
3. **Time-boxed write capability.** The write tool exists for the duration of
   one operation, then disappears. No "I forgot to revoke the permission" bugs.

## Implementation note — the lean mount is the security primitive

Kitsune's `tools=[...]` allowlist is the mechanism that makes this work. Most
MCP clients only support "mount the whole server." Kitsune's per-tool lean
mount lets you treat individual tools as separately-grantable capabilities —
even when they live on the same underlying server.

## When this pattern is wrong

- **The agent does heavy write-mode work.** If 80% of the agent's job is
  modifying data, the constant shapeshift dance is friction without benefit.
  Use upstream RBAC instead.
- **You need cryptographic non-repudiation.** This pattern is a *runtime*
  capability boundary, not a tamper-evident audit log. Pair with structured
  logging if compliance requires it.
- **The destructive tool isn't separable.** Some servers bundle read+write
  into a single tool (e.g., one `query` tool that accepts arbitrary SQL).
  In that case, scope the upstream credentials instead (read-only DB user
  by default, write user issued by `auth()` on demand).
