# Smithery Lattice — Claude Code Build Prompt
### The self-assembling MCP network — hackathon-feasible, grounded in real Smithery APIs

---

## Context for Claude Code

You are building **Smithery Lattice** — a Python MCP server that lets Claude autonomously discover, inspect, and connect to other MCP servers via the Smithery ecosystem. A lattice is the underlying structure everything else grows through: Smithery Lattice is the self-assembling intelligence layer on top of Smithery's registry.

This is a hackathon project. Build it in stages. **Stage 1 must work perfectly before Stage 2 is attempted.**

---

## What Makes This Novel

Every existing MCP aggregator (MetaMCP, mcp-proxy, mcp.run) requires a human to pre-configure which servers to include. **Smithery Lattice is the first where Claude discovers, installs, and orchestrates MCPs autonomously at runtime.** No config file. No restart. The lattice assembles itself.

Smithery (smithery.ai) is the world's largest MCP registry with thousands of servers. It has a proper Registry API, a TypeScript SDK with `createTransport`, a Skills Registry, and a CLI. We are building Smithery Lattice on top of all of this.

---

## Smithery Infrastructure (Read Carefully)

### Registry API — confirmed, documented
Base URL: `https://registry.smithery.ai`
Auth: `Authorization: Bearer {SMITHERY_API_KEY}` on all requests
API keys: https://smithery.ai/account/api-keys

**Search servers:**
```
GET https://registry.smithery.ai/servers?q={query}&page=1&pageSize=10
```
Supports semantic search. Special filters:
- `is:verified` — verified servers only (ALWAYS add this for safety)
- `is:deployed` — has a live remote deployment
- `owner:smithery-ai` — filter by org
- Combine: `is:verified is:deployed web search`

Returns: `{ servers: [ { qualifiedName, displayName, description, remote, deploymentUrl, ... } ] }`

**Get server detail:**
```
GET https://registry.smithery.ai/servers/{qualifiedName}
```
Returns full object including:
```json
{
  "qualifiedName": "@smithery-ai/github",
  "displayName": "GitHub",
  "description": "...",
  "remote": true,
  "deploymentUrl": "https://server.smithery.ai/@smithery-ai/github",
  "connections": [{
    "type": "stdio",
    "configSchema": { "properties": { "githubPersonalAccessToken": {...} } }
  }],
  "security": { "scanPassed": true },
  "tools": [{ "name": "create_issue", "description": "...", "inputSchema": {...} }]
}
```

**The `configSchema`** tells you exactly what credentials/config the server needs. Parse it to inform the user what to provide.

### Smithery SDK — for calling remote servers (Stage 2)
TypeScript/JS SDK. The pattern for calling a remote Smithery-hosted server:
```typescript
import { createTransport } from "@smithery/sdk/transport.js"
import { Client } from "@modelcontextprotocol/sdk/client/index.js"

const transport = createTransport(
  "https://server.smithery.ai/@smithery-ai/github",
  { "githubPersonalAccessToken": "YOUR_TOKEN" },
  "YOUR_SMITHERY_API_KEY"
)
const client = new Client({ name: "smithery-lattice", version: "1.0.0" })
await client.connect(transport)
const tools = await client.listTools()
const result = await client.callTool("create_issue", { title: "...", body: "..." })
```

Note: The SDK is TypeScript. For our Python MCP server, we will replicate this pattern using Python's `websockets` library and the MCP JSON-RPC protocol directly (see Stage 2). The SDK reveals the URL pattern: `https://server.smithery.ai/{qualifiedName}` with config passed as base64url-encoded JSON query param.

### WebSocket URL pattern (for Stage 2)
```python
import base64, json
config_json = json.dumps(config)
config_b64 = base64.urlsafe_b64encode(config_json.encode()).decode().rstrip("=")
ws_url = f"wss://server.smithery.ai/{qualified_name}/ws?config={config_b64}&api_key={smithery_api_key}"
```

### Smithery CLI — reference only, not used at runtime
```bash
smithery mcp search "github"
smithery mcp add https://server.smithery.ai/exa --id exa
smithery tool call exa search '{"query": "latest news"}'
smithery skill search "frontend design"
smithery skill add anthropics/frontend-design --agent claude-code
```
Use CLI commands in README examples but don't shell out to them from Python (too slow, auth complications).

### Skills Registry
URL: `https://smithery.ai/skills`
API: `https://registry.smithery.ai/skills?q={query}` (same auth pattern)
Skills are markdown documents injected into context — they change how Claude behaves for a topic. Example: `anthropics/frontend-design` teaches Claude to build beautiful UIs.

---

## Stage 1 — Core Demo (Build This First, ~1-2 hours)

**Goal:** Claude can discover what's in the Smithery ecosystem, understand a server deeply, and fetch a skill to augment itself. Zero subprocess. Zero WebSocket. Pure HTTPS. Guaranteed to work.

### Tools to implement:

#### 1. `explore(query: str, limit: int = 5) -> str`
Search the Smithery registry for MCP servers.

- Call `GET https://registry.smithery.ai/servers?q={query} is:verified&pageSize={limit}`
- For each result, format:
  ```
  🔷 @smithery-ai/github
     GitHub — Manage repos, issues, PRs via GitHub API
     Remote: ✓  |  Security scan: ✓  |  Tools: 12
     Needs: githubPersonalAccessToken
  ```
- Extract credential names from `connections[0].configSchema.properties` keys
- End with: `"Use inspect('<qualifiedName>') to see full tool details."`

#### 2. `inspect(qualified_name: str) -> str`
Get deep detail on a specific server.

- Call `GET https://registry.smithery.ai/servers/{qualified_name}`
- Format a rich summary:
  ```
  🔷 GitHub MCP Server (@smithery-ai/github)
  
  DESCRIPTION
  Manage GitHub repositories, issues, pull requests, and more.
  
  CONNECTION
  Type: Remote (hosted on Smithery)
  Security scan: PASSED ✓
  
  NUTRIENTS REQUIRED (credentials)
  • githubPersonalAccessToken — Your GitHub PAT with repo scope
  
  TOOLS (12)
  • create_issue(title, body, labels) — Create a new issue
  • list_repos(org) — List repositories
  • create_pr(title, body, base, head) — Open a pull request
  ... (show all)
  
  CONTEXT COST (estimated)
  Tool schemas: ~2,400 tokens
  
  To grow this server: provide githubPersonalAccessToken, then call grow(...)
  ```
- Parse all tool names + descriptions from `tools[]`
- Estimate token cost: total chars in tool schemas / 4

#### 3. `inoculate_skill(qualified_name: str) -> str`
Fetch a skill from Smithery's skills registry and inject it into context.

- Call `GET https://registry.smithery.ai/skills/{qualified_name}` to get skill metadata + content URL
- Fetch the skill markdown content (likely a raw GitHub URL or CDN URL in the response)
- Return the full skill markdown as the tool result — Claude will automatically incorporate it
- Also show: skill name, description, estimated token cost
- Track in memory: `active_skills[qualified_name] = { content, tokens, installed_at }`

#### 4. `network_status() -> str`
Show what the network looks like this session.

- Pure in-memory. Track a dict of `explored_servers` and `active_skills`.
- Format:
  ```
  🔷 SMITHERY LATTICE STATUS
  
  EXPLORED THIS SESSION (3)
  • @smithery-ai/github — inspected
  • @exa-ai/exa — explored
  • brave/brave-search — explored
  
  ACTIVE SKILLS (1)
  • anthropics/frontend-design — ~1,200 tokens
  
  TOTAL CONTEXT PRESSURE: ~1,200 tokens
  ⚠️  Consider metabolizing skills if context grows heavy.
  ```

### Stage 1 file structure:
```
smithery-lattice/
  server.py          # Single file MCP server
  requirements.txt   # mcp, httpx
  README.md
  .env.example       # SMITHERY_API_KEY=
```

### server.py skeleton:
```python
import asyncio, os, json, base64
from datetime import datetime
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("smithery-lattice")

SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY")
REGISTRY_BASE = "https://registry.smithery.ai"

# Session state
session = {
    "explored": {},   # qualifiedName -> summary
    "skills": {},     # qualifiedName -> {content, tokens}
    "grown": {},      # qualifiedName -> {tools, credentials, status} — Stage 2
}

def registry_headers():
    return {
        "Authorization": f"Bearer {SMITHERY_API_KEY}",
        "Accept": "application/json"
    }

@mcp.tool()
async def explore(query: str, limit: int = 5) -> str:
    """Search the Smithery MCP registry for servers matching your intent."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{REGISTRY_BASE}/servers",
            params={"q": f"{query} is:verified", "pageSize": limit},
            headers=registry_headers(),
            timeout=15.0
        )
        r.raise_for_status()
        data = r.json()
    # ... format and return

@mcp.tool()
async def inspect(qualified_name: str) -> str:
    """Inspect a specific Smithery MCP server — tools, credentials needed, token cost."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{REGISTRY_BASE}/servers/{qualified_name}",
            headers=registry_headers(),
            timeout=15.0
        )
        r.raise_for_status()
        server = r.json()
    # ... format and return

@mcp.tool()
async def inoculate_skill(qualified_name: str) -> str:
    """Fetch and inject a Smithery skill into your context — changes how Claude thinks."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{REGISTRY_BASE}/skills/{qualified_name}",
            headers=registry_headers(),
            timeout=15.0
        )
        r.raise_for_status()
        skill = r.json()
    # fetch skill content from skill["contentUrl"] or similar field
    # store in session["skills"]
    # return the full markdown — Claude injects it automatically

@mcp.tool()
async def network_status() -> str:
    """Show the current state of the Smithery Lattice — connected nodes and active skills."""
    # pure in-memory summary from session dict

if __name__ == "__main__":
    mcp.run()
```

---

## Stage 2 — Live Tool Calling via WebSocket (~1 hour extra, only if Stage 1 is solid)

**Goal:** Actually call tools on remote Smithery servers in real-time.

#### 5. `grow(qualified_name: str, tool_name: str, arguments: dict, config: dict) -> str`
Call a tool on a remote Smithery-hosted MCP server.

**How it works:**
1. Build WebSocket URL with base64-encoded config:
   ```python
   config_b64 = base64.urlsafe_b64encode(
       json.dumps(config).encode()
   ).decode().rstrip("=")
   ws_url = f"wss://server.smithery.ai/{qualified_name}/ws?config={config_b64}&api_key={SMITHERY_API_KEY}"
   ```
2. Connect via `websockets.connect(ws_url)`
3. Send MCP JSON-RPC initialization handshake:
   ```json
   {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smithery-lattice","version":"1.0.0"}}}
   ```
4. Wait for initialize response, send initialized notification:
   ```json
   {"jsonrpc":"2.0","method":"notifications/initialized","params":{}}
   ```
5. Send tool call:
   ```json
   {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"{tool_name}","arguments":{...}}}
   ```
6. Wait for response, extract `result.content[0].text`
7. Close connection

**Timeout:** 30 seconds total. Catch all exceptions gracefully.

Store in `session["grown"][qualified_name] = { "last_tool": tool_name, "calls": N, "status": "active" }`

Add `websockets` to requirements.txt.

**Test first with:** `@modelcontextprotocol/fetch` or `exa` (well-known, simple schemas).

---

## Stage 3 — Quick Polish (~30 min, cosmetic)

Only add if Stages 1+2 are working:

#### 6. `prune(qualified_name: str) -> str`
Remove a grown server from session state. Just clears the dict entry and returns confirmation. If there's an open WebSocket, close it.

#### 7. `metabolize(skill_name: str) -> str`
Remove a skill from context (remove from `session["skills"]`). The tokens are freed on next turn.

---

## Claude Desktop Config

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

---

## Demo Script (Hackathon)

```
User: "Explore MCP servers for GitHub"
→ explore("GitHub") — shows 5 verified results with credential needs

User: "Inspect the GitHub one"
→ inspect("@smithery-ai/github") — shows 12 tools, needs githubPersonalAccessToken, ~3k tokens

User: "Add the frontend design skill"
→ inoculate_skill("anthropics/frontend-design") — fetches markdown, Claude now builds better UIs

User: "Show me the network"
→ network_status() — shows explored servers, active skills, token pressure

[If Stage 2 ready:]
User: "Search for 'MCP hackathon Berlin' using Exa"
→ grow("exa", "search", {"query":"MCP hackathon Berlin"}, {"exaApiKey": "..."})
→ Live results from Exa appear — installed and called in real time
```

---

## Smithery Lattice Language Guide

When Claude uses these tools, it should speak in Smithery Lattice's voice — architectural, structural, precise:

| Avoid | Use instead |
|-------|------------|
| "search for servers" | "scan the lattice for..." |
| "connecting to a server" | "adding a node to the lattice" |
| "credential required" | "this node needs a key to join the lattice" |
| "calling the API" | "routing through the lattice to..." |
| "skill installed" | "skill woven into the lattice" |
| "disconnecting" | "removing the node" |
| "context is full" | "the lattice is under load" |
| "server not found" | "no node found matching..." |

Add a system prompt note to README recommending users set a custom Claude system prompt:
> "You are operating through Smithery Lattice — the self-assembling MCP network built on Smithery's registry. Use architectural language: scan, connect, route, weave, assemble."

---

## Error Handling Patterns

```python
# Registry unavailable
"🔷 Smithery Lattice couldn't reach Smithery registry. Check your API key or network."

# Server not found
"🔷 No server found for '{qualified_name}'. Try explore() to find the right qualified name."

# WebSocket timeout (Stage 2)
"🔷 The connection to {qualified_name} went silent. The server may be sleeping. Try again or prune and regrow."

# Missing SMITHERY_API_KEY
"🔷 No API key found — set SMITHERY_API_KEY environment variable to feed the network."
```

---

## What NOT to Build (Scope Cuts)

- ❌ Local server subprocess installation (`uvx`/`npx`) — too fragile for hackathon
- ❌ Stdio MCP protocol over subprocess — skip entirely
- ❌ Multiple skill sources — Smithery registry only
- ❌ `regenerate()` — not needed for demo
- ❌ Persistent storage — in-memory session only
- ❌ Docker sandboxing — mention in pitch as "production roadmap"

---

## The Pitch (30 seconds)

> "Smithery built the registry — thousands of verified MCP servers, ready to use. But connecting them still requires humans to configure each one by hand.
>
> Smithery Lattice changes that. It's the self-assembling intelligence layer on top of Smithery: Claude discovers the right server, understands what credentials it needs, and connects — no config file, no restart.
>
> Every other MCP aggregator is static. Smithery Lattice is the first where the infrastructure builds itself."

**Tagline:** *Smithery Lattice — the self-assembling MCP network*

**Awards target:**
- **Impact Award** — solves MCP discovery for the whole Smithery ecosystem; a natural next layer on top of their platform
- **Elegance Award** — built entirely on Smithery's own registry API, skills system, and WebSocket transport; zero external dependencies

---

## Requirements Files

**requirements.txt:**
```
mcp
httpx
websockets  # add for Stage 2
python-dotenv
```

**README.md should include:**
- What Smithery Lattice does (one paragraph)
- Smithery attribution and link
- Demo GIF placeholder
- Claude Desktop config snippet
- `smithery skill search` and `smithery mcp search` equivalents shown as inspiration
- Note: "Built on Smithery's registry API and skills ecosystem"
