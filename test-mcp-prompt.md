# Smithery Lattice MCP — Test Session Prompt

Use this prompt at the start of a new Claude Code session to verify the MCP is working.

---

## Paste this into a new session:

```
I want to test the smithery-lattice MCP server. Please run through these steps in order and report what you get back from each tool call:

1. Call network_status() — should show an empty lattice (0 explored, 0 skills, 0 grown)

2. Call explore("github") with limit=3 — should return 3 verified GitHub-related MCP servers from the Smithery registry

3. Take one of the qualifiedNames from step 2 and call inspect("<qualifiedName>") — should return full details: description, connection type, credentials needed, tools list, token estimate

4. Call network_status() again — should now show the servers from steps 2-3 in the explored list

After each step, tell me exactly what was returned and whether it looks correct. If any step fails, show me the error message.
```

---

## What to look for

| Step | Expected | Failure sign |
|------|----------|-------------|
| `network_status()` | Empty lattice output | Error / no tool found |
| `explore("github")` | 3 server cards with names, descriptions, credential info | 401 = bad API key / network error |
| `inspect(...)` | Full blueprint with tools list and token estimate | 404 = wrong qualified name |
| `network_status()` again | Explored servers listed | State not persisted (process restarted) |

## If the MCP doesn't appear

Run `/mcp` in the session — smithery-lattice should be listed as connected. If it shows "Failed to connect", run:

```bash
cd /Users/marty/claude-projects/smithery-lattice
./add-mcp.sh
```

Then start a new Claude Code session.
