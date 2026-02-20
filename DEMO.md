# Smithery Lattice — Demo Script

Step-by-step prompts to type in Claude Code CLI during the presentation.

---

## Step 1 — Show what's available

```
explore("web search")
```

Shows verified MCP servers for web search (exa, brave, etc.) with descriptions and credential requirements.

---

## Step 2 — Inspect a node before connecting

```
inspect("exa")
```

Shows all tools, required keys, and estimated context cost for the Exa node.

---

## Step 3 — Connect and use it

```
grow("exa", "web_search_exa", {"query": "your topic here"})
```

Connects live to the Exa server and runs a real web search. No config needed.

---

## Step 4 — Show a second tool on the same node

```
grow("exa", "company_research_exa", {"companyName": "Smithery AI"})
```

Same node, different tool — company intelligence.

---

## Step 5 — Show the lattice state

```
network_status()
```

Shows which nodes are active, how many calls were made, and context pressure.

---

## Bonus — Full auto pipeline (no manual steps)

```
harvest("web search", "web_search_exa", {"query": "your topic"}, server_hint="exa")
```

Discover → connect → call in one command.

---

## If asked about credentials

```
set_key("BRAVE_API_KEY", "your-key")
```

Saves to `.env` — auto-loaded in all future calls. No need to pass it manually again.
