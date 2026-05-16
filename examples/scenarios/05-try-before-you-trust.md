# Scenario 05 — Try-before-you-trust MCP evaluation

> *"A new vector-db MCP server just landed on Glama. Five-star reviews. I want
> to poke at it for ten minutes before adding it to my permanent client config."*

This is the MCP equivalent of running `npx` instead of `npm install -g`:
sandboxed, time-bounded, no persistent footprint.

DNA traits:
- **Time-bounded** — by definition, you're evaluating
- **Surgical** — you only test the 2-3 tools you care about
- **Trust gate** — community servers should not silently become part of your
  resident toolset
- (Long-tail is occasionally relevant; new servers are by definition outside
  the model's training data.)

## The failure mode — npm install -g approach

The traditional way to evaluate a new MCP server:

1. Edit `~/.cursor/mcp.json` (or `claude_desktop_config.json`) to add the server.
2. Restart the client.
3. Try it out.
4. If you don't like it: edit the config again, remove the entry, restart again.

For each evaluation you pay: two config edits + two restarts + the schema-bill
overhead of permanently mounting an unproven server. Most people don't bother —
which means good new servers get under-tried and bad ones get over-trusted.

## The Kitsune transcript

```python
# 1. Find the candidate.
search("vector database", limit=5)
# → pinecone-mcp       | smithery/http   | ✓ creds set
# → chroma-local       | npm/stdio       | ⚠ community
# → qdrant-mcp         | mcpregistry/stdio | ✓
# → ...

# 2. Inspect before mounting — see the tool surface and trust tier.
inspect("chroma-local")
# → Source: npm | Transport: stdio
#   Credentials: none required
#   RUN: npx -y chroma-local-mcp
#   TOOLS (live, community):
#     create_collection(name, dimension)
#     upsert(collection, ids, vectors, metadatas)
#     query(collection, vector, top_k)
#   Token cost: ~340 tokens (measured)

# 3. Mount with explicit community-trust confirmation.
shapeshift("chroma-local", confirm=True)
# → ⚠ Source: npm (community — not verified by the official MCP registry)
#   3 tool(s) registered: create_collection, upsert, query

# 4. Run real evaluation calls.
call("create_collection", {"name": "test", "dimension": 384})
call("upsert", {"collection": "test", "ids": ["a","b"], ...})
call("query", {"collection": "test", "vector": [...], "top_k": 5})

# 5a. Hate it: uninstall completely.
shiftback(uninstall=True)
# → Shifted back from 'chroma-local'.
#   Uninstalled: chroma-local-mcp (npx cache will auto-expire)

# 5b. Love it: leave the cache warm and ship a permanent entry to your
# real client config from a clean known-good baseline.
shiftback()  # uses new kill=True default — frees memory, keeps npx cache
```

Ten minutes of evaluation, zero edits to your real client config, zero
restarts, and the server is gone afterwards unless you explicitly adopt it.

## Token receipts

| Approach | Permanent footprint | Setup latency |
|---|---|---|
| Edit-config-and-restart | Pays schema cost in every session forever | Restart × 2 |
| Kitsune evaluation | Zero permanent cost | ~5-15s cold mount |

## What this scenario demonstrates

1. **Evaluation has a cost; the cost should be bounded.** Kitsune makes the
   cost = the duration of the evaluation itself.
2. **Trust gating is enforced at mount time.** Community sources need `confirm=True`
   or `KITSUNE_TRUST=community`. You can't accidentally mount a sketchy server.
3. **The agent can do this.** A human-curated config edit isn't required —
   the agent can evaluate options on the user's behalf, then surface a
   recommendation. *"I tried three vector-db MCPs; chroma-local is the
   simplest. Want me to keep it mounted for the rest of this session?"*

## When this pattern is wrong

- **You've already vetted the server.** If it's known-good, just add it to
  your client config permanently.
- **You need persistent state across sessions.** Some servers (databases,
  long-running agents) lose meaningful state on shiftback. Adopt them
  permanently or use `connect()` for persistent connections.
- **You're evaluating to publish reliability claims.** Kitsune's `test()`
  scoring is a starting point but not a substitute for production traffic.
  Treat the evaluation as a smoke test, not certification.

## Bonus pattern: parallel A/B evaluation

```python
# Compare three candidates side by side on the same query.
compare("vector database", limit=3, probe=True)
# → Probes ALL candidates in parallel, returns a ranked table:
#   tokens  tools  src        status     id
#       340      3  npm        live       chroma-local
#       680      6  smithery   live       pinecone-mcp
#       450      4  mcpregistry live      qdrant-mcp
```

This is a *competition*-style evaluation — pick the winner from real probe
results, not from README claims.
