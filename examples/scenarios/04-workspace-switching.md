# Scenario 04 — Workspace switching (Notion personal ↔ team)

> *"I want my agent to read from my personal Notion to pick up a research
> note, then post a polished version into my company's team Notion."*

Same server. Same tools. Two different identities. Kitsune's `auth(...,
"logout")` + re-shapeshift gives you a clean identity boundary inside one
session — without editing config files or restarting the client.

DNA traits:
- **Time-bounded** — each identity is active for one phase of the task
- **Identity boundary** — strict separation between personal and team data
- **Surgical** — Notion's `search` + `get_page` + `create_page` are the only
  tools needed
- (Long-tail / high-stakes are minor here — the value is mostly the auth
  switching.)

## The failure mode — always-on with two configs

The "old" way to do this in MCP land is to register two different MCP servers
in your client config:

```json
{
  "notion-personal": { ... auth env A ... },
  "notion-team":     { ... auth env B ... }
}
```

This works, but:
- Both servers' tools are *both* in context all the time. ~6K × 2 = ~12K tokens
  for a workflow that uses one at a time.
- The model has to pick `notion-team.get_page` vs `notion-personal.get_page` —
  and it picks wrong sometimes, especially under ambiguous prompts.
- Adding a third workspace requires another config edit + restart.

## The failure mode — manual auth file deletion

Before Kitsune v0.20.2 (issue #37), the only way to switch the OAuth token for
the same server was:

```bash
rm -rf ~/.kitsune/oauth/notion.so
```

A user-hostile path. The agent couldn't do this on its own.

## The Kitsune transcript

```python
# 1. Authenticate as the personal workspace.
auth("notion-hosted")            # opens browser → pick personal workspace
# → Authenticated 'notion-hosted'. Token: a1b2c3d4...
#   Next: shapeshift("notion-hosted")

shapeshift("notion-hosted")
note = call("search", {"query": "Q2 strategy draft"})
content = call("get_page", {"page_id": note["pages"][0]["id"]})
shiftback()

# 2. Swap identity — clear the cached OAuth token.
auth("notion-hosted", "logout")
# → ✓ OAuth tokens cleared for 'notion-hosted'.
#   Next: auth('notion-hosted') to re-authenticate.

# 3. Authenticate again — this time the browser flow picks the team workspace.
auth("notion-hosted")            # browser → pick "acme team" workspace
# → Authenticated 'notion-hosted'. Token: e5f6g7h8...

# 4. Mount again and write into the team space.
shapeshift("notion-hosted", tools=["create_page"])
call("create_page", {
    "parent_id": "<team-strategy-page-id>",
    "title": "Q2 strategy — distilled",
    "content": polish(content),     # model-side text transform
})
shiftback()
```

One server config, one MCP entry in your client, two identities — cleanly
separated by an explicit `auth(..., "logout")` boundary in the transcript.

## Token receipts

| Approach | Context overhead | Identity safety |
|---|---:|---|
| Two MCP servers configured | ~12K constant | Possible cross-workspace tool misfire |
| Single Kitsune + `auth(..., "logout")` | ~3-5K per phase, one at a time | Strict — old token gone before new mount |

## What this scenario demonstrates

1. **Identity is a runtime concern, not a config concern.** You can switch
   workspaces, tenants, environments mid-session by clearing one token.
2. **The audit trail is explicit.** Every identity change is a visible
   `auth(..., "logout")` call in the transcript — no implicit "oh the agent
   silently used the wrong account."
3. **Replaces the two-server hack.** No need to register "notion-prod" and
   "notion-dev" separately in your client config.

## When this pattern is wrong

- **You need both identities active in the same step.** (Diffing a personal
  doc against a team doc, for instance.) Then two-server config is the right
  call — you genuinely want simultaneous access.
- **You're switching identities every few seconds.** Browser re-auth has
  human-in-the-loop latency. For high-frequency identity swaps, pre-issue
  per-tenant API tokens and switch with `auth("API_KEY", "value")` instead.
- **The server doesn't use OAuth.** `auth(..., "logout")` only clears OAuth
  tokens. For API-key servers, just `auth("API_KEY", "<new-value>")` —
  overwriting is the switch.

## Related issues this resolves

- [#37](https://github.com/kaiser-data/kitsune-mcp/issues/37) — `auth()` can't
  clear OAuth tokens (closed in v0.20.1, documented here for v0.20.2).
