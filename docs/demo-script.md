# Kitsune MCP — Demo & Video Script

Video script for the launch demo covering three clients: Claude Code (developer),
Claude Desktop (everyday user), OpenClaw (power user).

---

## Short cut (60–90 s) — social / teaser

**[COLD OPEN — terminal, no music]**

```
search("pdf extract")
shapeshift("mcp-pdf-tools", confirm=True, sandbox=True)
```

Output on screen: tools appear live. No config edit. No restart.

**TITLE CARD**: *"What if your agent could borrow any MCP — mid-session?"*

---

**[Claude Code — 8 s]**
```
shapeshift("brave-search", tools=["web_search"])
call("web_search", {"query": "anthropic MCP updates"})
shapeshift()   # form dropped — session intact
```
**CAPTION**: *Developer. One tool borrowed. Done. Gone.*

---

**[Claude Desktop — 8 s]**

User types: `"search: best MCP servers for productivity"`

Tool call appears: `auto(task="search: best MCP servers", server_hint="…")`

Result pops in. One turn. No setup.

**CAPTION**: *Everyday user. Zero config. Just ask.*

---

**[OpenClaw — 8 s]**
```
setup(action="harvest")   # pulls API keys from other servers
setup(action="absorb")    # registers them all for shapeshift()
```
**CAPTION**: *Power user. One gateway. Whole catalog on demand.*

---

**TITLE CARD**: *One config entry. 130,000+ servers. No restarts.*
```
pip install kitsune-mcp
```

---

## Long cut (3.5 min) — YouTube / README / product demo

### Act 1 — The problem (30 s)

**[Screen: Claude Desktop config file — 5 servers listed]**

**VO**: "Adding an MCP server still means editing your config and restarting the
client. You lose the session to gain a tool. And if you're *building* an MCP
server, you restart on every edit."

**VO**: "Native Tool Search already helps with servers you've configured —
schemas stay deferred until needed. What it doesn't solve: the long tail you
haven't installed, the server you're writing right now, and community code you
want to try without wiring it in permanently."

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
RESTING: ~1,358 tokens   (Kitsune's own 6 tools — the fixed floor)
GATEWAY: 2 other server(s) in claude-desktop (~24 tools)
```

**VO**: "Status shows the floor — Kitsune isn't free at rest — and which other
clients still have always-on servers. The point of this demo isn't saving those
tokens. It's mounting something I never put in the config."

```
shapeshift("@modelcontextprotocol/server-github",
           tools=["search_repositories"])
```
```
✓ Mounted 1 tool  (~300 tokens)   [full server always-on = 4,229]
```

```
call("search_repositories", {"query": "MCP servers productivity"})
```

*Results appear — real GitHub data.*

```
shapeshift()
```
```
✓ Released. Session intact. Back to lean form.
```

**VO**: "One tool, real data, no restart. That's the harness: borrow a capability,
use it, put it back — conversation continues."

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

## Token scorecard (secondary — for on-screen graphics if needed)

**Secondary metric only.** Real vs fully-mounted always-on / clients without Tool
Search. Do not lead the video on these numbers — lead on reach + REPL.
Every Kitsune figure includes the fixed ~1,358-token floor.

### Per-server (floor included)
| Server | Always-on | 1,358 floor + surgical | Saved |
|---|---:|---:|---:|
| mcp-server-time (2 tools) | 261 | ~1,619 | — ¹ |
| mcp-server-git (12) | 1,242 | ~1,668 | — ¹ |
| server-memory (9) | 2,615 | ~1,938 | 26% |
| server-filesystem (14) | 3,207 | ~2,048 | 36% |
| brave (8) | 3,612 | ~1,808 | 50% |
| server-github (26) | 4,229 | ~1,658 | **61%** |
| notion-hosted (14) | 13,707 | ~3,308 | 76% |

¹ For a **single** server smaller than the 1,358 floor (time, git), always-on is
cheaper — Kitsune only pays off past one medium server, or two-plus small ones.

### Multi-server compounding (floor stays flat; always-on stacks)
| Servers always-on | Always-on/turn | Kitsune/turn | Saved |
|---|---:|---:|---:|
| GitHub | 4,229 | ~1,658 | 61% |
| GitHub + filesystem + git | 8,678 | ~1,668–2,048 | 76–81% |
| Notion + GitHub + filesystem + git + memory | 25,000 | ~1,668–3,308 | **87–93%** |

### Headline for thumbnail (prefer reach, not tokens)
> "One config. Any MCP. Mid-session — no restart."

Alternate (legacy baseline only): *"Up to ~90% fewer tokens vs fully-mounted always-on."*

---

## Narration notes

- Tone: measured, technical. Not hype.
- Pace: let the terminal output breathe — 1–2 s after each command before VO continues.
- Highlight: circle or zoom the token counts when they change.
- The GATEWAY section is the strongest first-run moment — give it 10 s of screen time.
