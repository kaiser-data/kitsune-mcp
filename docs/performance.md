# Performance

## Connection latency (what you feel)

Warm pool re-attach within a session: **0 ms**.

| Transport | Cold start | Warm |
|---|---|---|
| HTTP / Smithery | 0–1.4 s | 0.0 s |
| Local `npx` | 1.7–6.3 s | 0.0 s |
| Local `uvx` | 1.0–5.2 s | 0.0 s |

Use `prewarm` (forge) when you know you'll need a server soon.

## Token overhead (secondary)

> Real vs **fully-mounted always-on** or clients **without** Tool Search. On Claude Code 2.1.7+ with native deferral, this is mostly not a Kitsune-specific win. Product pitch is reach + REPL above — not this table.

Every Kitsune figure **includes** the ~1,774 floor. Reproduce: `python examples/benchmark.py`. Methodology: [`benchmarks.md`](benchmarks.md).

<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"
            srcset="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/token-cost-dark.svg"/>
    <img src="https://raw.githubusercontent.com/kaiser-data/kitsune-mcp/main/docs/token-cost-light.svg"
         alt="Token cost comparison: always-on vs Kitsune" width="700"/>
  </picture>
</div>

| Server | Always-on | Surgical + floor | vs always-on |
|---|---:|---:|---:|
| `mcp-server-time` | 261 | ~2,035 | always-on cheaper ¹ |
| `mcp-server-git` | 1,242 | ~2,084 | always-on cheaper ¹ |
| `server-memory` | 2,615 | ~2,354 | 10% |
| `server-filesystem` | 3,207 | ~2,464 | 23% |
| `brave` | 3,612 | ~2,224 | 38% |
| `server-github` | 4,229 | ~2,074 | 51% |
| `notion-hosted` | 13,707 | ~3,724 | 73% |

¹ Break-even: Kitsune pays off past one medium server, or two-plus small ones sharing the single floor. Multi-server stack (GitHub+fs+git → Notion suite): **~72–85%** vs fully-mounted always-on — same caveat as above.

Fewer visible tools also helps selection reliability (Gorilla / ToolBench); on modern clients Tool Search delivers much of that focus for *configured* servers. Kitsune-specific accuracy bench: not yet — contributions welcome.

---

[← README](../README.md)
