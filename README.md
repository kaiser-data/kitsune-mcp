# Smithery Lattice

**The self-assembling MCP network — built on Smithery's registry**

Every other MCP aggregator is static. Smithery Lattice is the first where Claude discovers, inspects, and orchestrates MCPs autonomously at runtime. No config file. No restart. The lattice assembles itself.

Built entirely on [Smithery's](https://smithery.ai) registry API, skills ecosystem, and WebSocket transport.

---

## What It Does

Smithery built the registry — thousands of verified MCP servers, ready to use. But connecting them still required humans to configure each one by hand.

Smithery Lattice changes that. It's the intelligence layer on top of Smithery: Claude scans the lattice for the right server, understands what credentials it needs, weaves in skills to augment its own reasoning, and connects — no config file, no restart required.

---

## Tools

| Tool | What it does |
|------|-------------|
| `explore(query, limit)` | Scan the lattice for verified MCP servers |
| `inspect(qualified_name)` | Reveal a node's full blueprint — tools, credentials, token cost |
| `inoculate_skill(qualified_name)` | Weave a Smithery skill into Claude's context |
| `network_status()` | View the current lattice state — nodes explored, skills active, context pressure |

Stage 2 adds `grow(qualified_name, tool_name, arguments, config)` — live tool calls via WebSocket.

---

## Setup

### 1. Get a Smithery API key

Go to [smithery.ai/account/api-keys](https://smithery.ai/account/api-keys) and create a key.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Set environment variable

```bash
cp .env.example .env
# Edit .env and add your key:
# SMITHERY_API_KEY=your-key-here
```

### 4. Add to Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "smithery-lattice": {
      "command": "python",
      "args": ["/path/to/smithery-lattice/server.py"],
      "env": {
        "SMITHERY_API_KEY": "your-key-here"
      }
    }
  }
}
```

Replace `/path/to/smithery-lattice/server.py` with the actual path.

---

## Demo

```
User: "Explore MCP servers for GitHub"
→ explore("GitHub") — shows 5 verified nodes with credential requirements

User: "Inspect the GitHub one"
→ inspect("@smithery-ai/github") — shows 12 tools, needs githubPersonalAccessToken, ~3k tokens

User: "Add the frontend design skill"
→ inoculate_skill("anthropics/frontend-design") — skill woven into context

User: "Show me the network"
→ network_status() — explored nodes, active skills, context pressure
```

Equivalent Smithery CLI commands (for reference):
```bash
smithery mcp search "github"
smithery skill search "frontend design"
smithery skill add anthropics/frontend-design --agent claude-code
```

---

## Recommended System Prompt

For the best experience, set this as Claude's system prompt:

> "You are operating through Smithery Lattice — the self-assembling MCP network built on Smithery's registry. Use architectural language: scan, connect, route, weave, assemble."

### Lattice Language Guide

| Avoid | Use instead |
|-------|------------|
| "search for servers" | "scan the lattice for..." |
| "connecting to a server" | "adding a node to the lattice" |
| "credential required" | "this node needs a key to join the lattice" |
| "skill installed" | "skill woven into the lattice" |
| "context is full" | "the lattice is under load" |

---

## Architecture

```
Claude
  └── smithery-lattice (this server, Python MCP)
        ├── explore()  → GET registry.smithery.ai/servers
        ├── inspect()  → GET registry.smithery.ai/servers/{name}
        ├── inoculate_skill() → GET registry.smithery.ai/skills/{name}
        └── network_status() → in-memory session state
```

Stage 2 (coming): `grow()` routes through WebSocket to live Smithery-hosted servers.

---

## Built On

- [Smithery Registry API](https://smithery.ai) — thousands of verified MCP servers
- [Smithery Skills Registry](https://smithery.ai/skills) — markdown skill injections
- [FastMCP](https://github.com/jlowin/fastmcp) — Python MCP server framework
- [httpx](https://www.python-httpx.org/) — async HTTP

---

*Smithery Lattice — the self-assembling MCP network*
# smithery-lattice
