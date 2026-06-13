# LinkedIn Post — Kitsune MCP

> Voice: measured, technical, no hype. Lead with the problem, show the mechanism,
> end with one honest number. ~150 words — LinkedIn truncates after ~3 lines, so
> the hook must land before "…see more".

---

**Most AI agents load every tool they might ever need, on every single turn.**

Five MCP servers in your config? That's ~25,000 tokens of tool schemas riding along on every message — whether the task touches them or not. And it gets worse: more tools in context measurably degrades tool selection (Gorilla, Patil et al. 2023). You pay twice — in tokens and in accuracy.

Kitsune MCP flips it. One server in your config. 130,000+ servers reachable. Mount only the tools the task needs, then release them:

```
shapeshift("github", tools=["search_repositories"])   # 1 tool, not 26
call("search_repositories", {"query": "mcp servers"})
shapeshift()                                           # released — context back to floor
```

It's not free at rest — Kitsune's own 6 tools cost ~1,321 tokens. But that floor stays flat while always-on servers stack linearly. Past one medium server, you win: ~62% fewer tokens on GitHub alone, 87–93% across five servers.

Lean agent. Honest math. Open source.

`pip install kitsune-mcp` · github.com/kaiser-data/kitsune-mcp
