# Token Benchmark Methodology

## How to run

```bash
python examples/benchmark.py
```

No network access required. All measurements use actual registered tool schemas from the running package.

## What it measures

| Section | What |
|---------|------|
| **Profile sizes** | Token cost of the lean (9-tool) and forge (22-tool) profiles as registered by MCPServer |
| **Savings vs always-on** | Kitsune's total cost vs loading N servers permanently |
| **Per-tool breakdown** | Token cost of each individual tool schema |

## Token count formula

```python
token_count = len(json.dumps(schema)) // 4
```

This matches `_estimate_tokens()` in `kitsune_mcp/utils.py` — the same heuristic used throughout the codebase. It approximates the common 4 chars/token rule of thumb used for Claude/GPT models.

**Caveats:**
- Actual token counts vary slightly by model and tokenizer (±10–20%)
- The "always-on baseline" uses a representative 8-tool server (97 tokens/tool avg)
- Real savings depend on the actual servers in your use case

## Interpreting the savings table

The comparison shows kitsune's total overhead **including one active mounted server** vs loading N servers all at once:

- **Kitsune lean** = 10 lean tools (incl. the connect/release/reload REPL trio and test()) + 1 mounted server (best case per task)
- **Kitsune forge** = 21 full tools + 1 mounted server
- **Always-on baseline** = N × 8 tools × 97 tokens permanently in context

Lean mode becomes more cost-effective than always-on at 4+ typical servers (at 2–3 servers it costs more). Forge becomes cost-effective at 6+ servers. Note: on clients with native Tool Search these comparisons are largely moot — see the README caveat; the lean REPL trio is worth its context for the develop-live loop, not for token math.

## Reference output (lean: REPL trio + test(), 2026-11-27)

```
==============================================================
  Kitsune MCP — Token Overhead Benchmark
==============================================================

=== Profile sizes (actual registered schemas) ===
  lean  (10 tools / default):   1895 tokens
  forge (21 tools / full):     3510 tokens

=== Savings: kitsune vs always-on N servers ===
  Baseline: 8 tools/server × 97 tokens/tool (representative avg)

  2 servers — always-on baseline:  1552 tokens
    kitsune lean:      2671 tokens  (costs 72% more)
    kitsune forge:     4286 tokens  (costs 176% more)

  5 servers — always-on baseline:  3880 tokens
    kitsune lean:      2671 tokens  (saves 31%)
    kitsune forge:     4286 tokens  (costs 10% more)

  10 servers — always-on baseline:  7760 tokens
    kitsune lean:      2671 tokens  (saves 65%)
    kitsune forge:     4286 tokens  (saves 44%)

=== Per-tool breakdown ===
  Tool                         Tokens  Profile
  --------------------------------------------
  shapeshift                      376  lean + forge
  call                            345  lean + forge
  search                          325  lean + forge
  setup                           294  forge only
  prewarm                         258  forge only
  auto                            194  lean + forge
  craft                           181  forge only
  auth                            151  lean + forge
  reload                          143  lean + forge
  compare                         137  forge only
  inspect                         136  forge only
  bench                           133  forge only
  connect                         128  lean + forge
  test                            125  lean + forge
  run                             116  forge only
  onboard                         110  forge only
  shiftback                        88  forge only
  key                              79  forge only
  fetch                            78  forge only
  release                          55  lean + forge
  status                           49  lean + forge

Methodology: token_count = len(json.dumps(schema)) // 4
See docs/benchmarks.md for interpretation and caveats.
```
