# Kitsune MCP — Demo & Video Script

Video script for the launch demo covering three clients: Claude Code (developer),
Claude Desktop (everyday user), OpenClaw (power user).

---

## Short cut (60–90 s) — social / teaser

**[COLD OPEN — terminal, no music]**

```
status()
```

Output on screen:
```
GATEWAY
  ⚠  3 other server(s) active (~47 tools in context)
  Paying for them every turn, whether you use them or not
```

**TITLE CARD**: *"What if you only paid for what you actually use?"*

---

**[Claude Code — 8 s]**
```
shapeshift("brave-search", tools=["web_search"])
call("web_search", {"query": "anthropic MCP updates"})
shapeshift()   # context back to baseline
```
**CAPTION**: *Developer. One tool loaded. Done. Gone.*

---

**[Claude Desktop — 8 s]**

User types: `"search: best MCP servers for productivity"`

Tool call appears: `auto(task="search: best MCP servers")`

Result pops in. One turn. No setup.

**CAPTION**: *Everyday user. Zero config. Just ask.*

---

**[OpenClaw — 8 s]**
```
setup(action="harvest")   # pulls API keys from other servers
setup(action="absorb")    # registers them all for shapeshift()
```
**CAPTION**: *Power user. One command. All servers absorbed.*

---

**TITLE CARD**: *One config entry. 10,000+ servers. No restarts.*
```
pip install kitsune-mcp
```

---

## Long cut (3.5 min) — YouTube / README / product demo

### Act 1 — The problem (30 s)

**[Screen: Claude Desktop config file — 5 servers listed]**

**VO**: "Every MCP server you add loads all its tools, every turn, whether you use them or
not. Five servers — that's up to 43,000 tokens of overhead on every single message.
And it gets worse the more you add."

**VO**: "More tools in context means worse tool selection. The research is clear —
Gorilla (Patil et al. 2023) and Hsieh et al. 2023 both show 20–40% accuracy loss when
the model has to pick from a full catalog versus a retrieved subset.
The fix isn't a better model — it's a smaller menu."

---

### Act 2 — Claude Code: developer flow (60 s)

**[Claude Code terminal — clean prompt]**

**VO**: "Here's Kitsune in Claude Code. One entry in the config."

**[Show `~/.claude/mcp.json` — only Kitsune listed]**

```
status()
```

```
ACTIVE:  none
RESTING: ~500 tokens
GATEWAY: 2 other server(s) in claude-desktop (~24 tools)
```

**VO**: "The GATEWAY shows me what I'm paying for in other clients.
Now let's mount GitHub — but only one tool, not all 26."

```
shapeshift("@modelcontextprotocol/server-github",
           tools=["search_repositories"])
```
```
✓ Mounted 1 tool  (~300 tokens)   [full server = 4,229]
```

```
call("search_repositories", {"query": "MCP servers productivity"})
```

*Results appear — real GitHub data.*

```
shapeshift()
```
```
✓ Released. Back to ~500 tokens.
```

**VO**: "One tool. Real data. 93% fewer tokens than mounting the full server.
The next task starts clean."

---

### Act 3 — Claude Desktop: everyday user (50 s)

**[Claude Desktop — conversational UI]**

**VO**: "Claude Desktop — regular conversation mode. The user never thinks about servers."

**[User types]**: `"Find me the best open source MCP servers released this month"`

Tool call visible in UI: `auto(task="find best open source MCP servers this month")`

Kitsune finds the right server, mounts it, calls it, returns results — one turn.

**[User types]**: `"Now get the current time in Tokyo and Sydney"`

```
auto(task="current time Tokyo Sydney", server_hint="mcp-server-time")
```

Two results returned instantly.

**VO**: "Pin a server with server_hint when you know what you want.
Or just describe the task and let Kitsune route it."

---

### Act 4 — OpenClaw: power user (60 s)

**[OpenClaw — full tool-call transparency]**

```
status()
```

```
GATEWAY
  ⚠  claude-desktop: notion-hosted, brave-search, filesystem (~38 tools)
  ⚠  claude-code:    github (~22 tools)
  Run setup() to harvest and absorb.
```

**VO**: "The gateway sees every server your other clients are loading.
Watch what happens when we absorb them."

```
setup()   # preview
```
```
Found 4 harvestable servers:
  notion-hosted  → NOTION_API_KEY in claude-desktop config
  brave-search   → BRAVE_API_KEY in claude-desktop config
  github         → GITHUB_TOKEN in claude-code config
  filesystem     → no credentials needed
```

```
setup(action="harvest")
```
```
✓ Saved 3 API keys → ~/.kitsune/.env
```

```
setup(action="absorb")
```
```
✓ 4 servers registered for shapeshift()
```

```
setup(project=True)
```
```
✓ Written: .claude/mcp.json  (Kitsune only, this project)
```

**VO**: "One lean config. Everything still reachable. Zero redundancy."

---

### Act 5 — Close (20 s)

**[Split-screen: three clients]**

**VO**: "Claude Code for developers. Claude Desktop for everyday use.
OpenClaw for power users. One server. One install.
Every MCP server in the ecosystem, on demand."

```
pip install kitsune-mcp
```

**TITLE CARD**: `github.com/kaiser-data/kitsune-mcp`

---

## Live demo commands (Claude Code, reproducible)

Run these in order during a screen recording. All output is real — no mocking needed.

```python
# 1. Baseline
status()

# 2. Find a server
search("current time timezone", compare=True)

# 3. Mount and use
shapeshift("mcp-server-time")
call("get_current_time", arguments={"timezone": "Asia/Tokyo"})
call("convert_time", arguments={"source_timezone": "Asia/Tokyo",
                                "target_timezone": "America/New_York",
                                "time": "09:00"})
shapeshift()

# 4. Lean mount on GitHub — 1 tool from 26
shapeshift("@modelcontextprotocol/server-github",
           tools=["search_repositories"])
call("search_repositories", {"query": "MCP server productivity"})
shapeshift()

# 5. auto() — one shot
auto("current time in Berlin", server_hint="mcp-server-time")

# 6. Final stats
status()
```

---

## Token scorecard (for on-screen graphics)

### Per-server savings
| Server | Always-on | Lean mount | Saved |
|---|---|---|---|
| mcp-server-time | 261 | 261 | 0% |
| mcp-server-git | 1,242 | ~310 | 75% |
| server-filesystem | 3,207 | ~500 | 84% |
| server-github | 4,229 | ~300 | **93%** |
| notion-hosted | 13,707 | ~1,950 | 86% |

### Multi-server compounding
| Servers | Always-on/turn | Kitsune/turn | Saved |
|---|---|---|---|
| 3 | ~7,700 | 500 | 94% |
| 5 | ~43,700 | 500 | 98.9% |
| 10 | ~58,700 | 500 | **99.2%** |
| 20 | ~130,000 | 500 | **99.6%** |

### Headline for thumbnail
> "One server. 99%+ fewer tokens. Smarter tool selection."

---

## Narration notes

- Tone: measured, technical. Not hype.
- Pace: let the terminal output breathe — 1–2 s after each command before VO continues.
- Highlight: circle or zoom the token counts when they change.
- The GATEWAY section is the strongest first-run moment — give it 10 s of screen time.
