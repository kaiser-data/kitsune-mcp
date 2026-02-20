# Smithery Lattice — Next Session Prompt

Paste this at the start of a new Claude session to resume.

---

## Context

Building **Smithery Lattice** — a self-assembling MCP network on top of Smithery's registry. Hackathon project.
Full spec: `/Users/marty/claude-projects/smithery-lattice/smithery_lattice_prompt.md`

---

## Progress Status

### ✅ Complete & Working

| Tool | Status | Notes |
|------|--------|-------|
| `explore(query)` | ✅ Working | Hits registry.smithery.ai, returns server list |
| `inspect(qualified_name)` | ✅ Working | Returns tools, credential schema, connection info |
| `inoculate_skill(qualified_name)` | ✅ Working | Fetches skill markdown, injects into context |
| `network_status()` | ✅ Working | Shows explored/grown nodes + context pressure |
| `set_key(env_var, value)` | ✅ Working | Writes to `.env` + sets in-process via os.environ |
| `grow(server, tool, args, config)` | ⚠️ Bug | See blocker below |
| `harvest(task, tool, args, hint, keys)` | ⚠️ Bug | Same blocker |

### ✅ Infrastructure (all confirmed working via direct Python tests)

- `_to_env_var(key)` — `exaApiKey` → `EXA_API_KEY`
- `_resolve_config(credentials, user_config)` — auto-fills creds from env vars
- `_save_to_env(env_var, value)` — persists to `.env` + sets in-process
- `_execute_tool_call(qualified_name, tool_name, arguments, config)` — HTTP+SSE MCP executor

### 📄 Also Done This Session

- `ARCHITECTURE.md` — Mermaid diagrams (system arch, tool pipeline, harvest sequence, credential flow)

---

## 🚨 Current Blocker: grow/harvest return "Authentication failed"

### Symptom

```
grow("exa", "web_search_exa", {"query": "test"})
→ 🔷 Authentication failed connecting to exa. Check your Smithery API key
```

Both `grow` and `harvest` produce this error for ALL calls.

### What We Know

**The code itself is correct.** Direct Python subprocess tests prove the entire
`_execute_tool_call` path works end-to-end:

```bash
# This works perfectly — returns real search results:
.venv/bin/python3 -c "
import asyncio, httpx, json, base64, os
from dotenv import load_dotenv
load_dotenv('.env')
# ... exact same code as _execute_tool_call ...
asyncio.run(main())  # → 200, real results
"
```

**The SMITHERY_API_KEY is correct.** `0d45e823-...` — verified:
- `explore()` works (hits registry.smithery.ai with same key) ✅
- Direct curl to `server.smithery.ai/exa` with same key → 200 ✅
- Direct Python test to `server.smithery.ai/exa` with same key → 200 ✅

**The exa server requires NO credentials.** Registry configSchema is empty.
Even without any config (`{}`), the direct test returns results. Exa works anonymously via Smithery.

**The error comes from exactly one place:**
```python
# server.py line 217–218
if r.status_code in (401, 403):
    raise PermissionError(f"HTTP {r.status_code}")
# → caught at line 248 → returns "Authentication failed..."
```

So the initialize call to `server.smithery.ai` IS returning 401/403 when made
from within the FastMCP server process, but returns 200 when made from a direct
Python subprocess.

### Root Cause Hypothesis

The MCP server process (started by Claude Code via `~/.claude/mcp.json`) makes
outgoing HTTP requests in a different network context than a fresh Python subprocess.
Possible causes, in order of likelihood:

1. **FastMCP event loop / httpx interaction** — httpx inside FastMCP's async
   context might behave differently. The FastMCP server uses its own asyncio
   event loop; `asyncio.wait_for` inside a tool handler might interact with
   SSL handshakes or connection setup differently.

2. **SMITHERY_API_KEY captured at wrong time** — The module-level variable
   `SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY")` is evaluated when the
   module loads. If the mcp.json env var wasn't in the environment at that exact
   moment, it would be `None`. But `_check_api_key()` would catch `None` —
   and we're getting "Authentication failed" not "No API key found". So the key
   IS set, but possibly set to a stale/wrong value from a previous load.

3. **httpx version or SSL certificate issue** — The venv's httpx version might
   behave differently in async contexts under load, or there may be an SSL
   verification difference.

### How to Fix

**Step 1: Add debug logging to capture the actual HTTP response.**

Modify `_execute_tool_call` in `server.py` to log the actual status code and
response body to a temp file when a 401/403 is received:

```python
# In _execute_tool_call, replace:
if r.status_code in (401, 403):
    raise PermissionError(f"HTTP {r.status_code}")

# With:
if r.status_code in (401, 403):
    import pathlib
    pathlib.Path("/tmp/lattice_debug.txt").write_text(
        f"status={r.status_code}\n"
        f"key_used={SMITHERY_API_KEY}\n"
        f"url={base_url[:120]}\n"
        f"body={r.text[:500]}\n"
    )
    raise PermissionError(f"HTTP {r.status_code}")
```

Then call `grow(...)`, read `/tmp/lattice_debug.txt`, and you'll know exactly
what key was used and what the server said.

**Step 2: After diagnosis, likely fixes:**

- If key is `None` or wrong → fix module-level loading:
  ```python
  # Replace module-level:
  SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY")
  # With dynamic lookup in the URL builder:
  # (use os.getenv("SMITHERY_API_KEY") at call time, not module load time)
  ```

- If key is correct but 401 persists → try moving `httpx.AsyncClient` creation
  outside `asyncio.wait_for` or use `anyio` instead of raw asyncio.

- If it's a FastMCP async context issue → call `_execute_tool_call` via
  `asyncio.get_event_loop().run_in_executor(None, ...)` to run in a thread pool.

**Step 3: After server.py fix → restart Claude** to reload the MCP process.

---

## What's Left (in priority order)

1. **Fix grow/harvest** — debug as described above, then restart Claude
2. **Test credential auto-load** — try `@smithery-ai/github` to confirm
   `set_key("GITHUB_TOKEN", "...") → harvest("create issue", ...)` works
3. **Write README** — needed for hackathon submission (not started yet)
4. **Demo polish** — rehearse the narrative: explore → inspect → harvest → network_status

---

## Key Files

```
server.py              # All 7 tools + helpers (~710 lines)
.env                   # SMITHERY_API_KEY + EXA_API_KEY (both set)
ARCHITECTURE.md        # Mermaid diagrams of the whole system
NEXT_SESSION.md        # This file
smithery_lattice_prompt.md  # Original hackathon brief
~/.claude/mcp.json     # smithery-lattice uses .venv/bin/python
```

## Environment

- Venv: `/Users/marty/claude-projects/smithery-lattice/.venv`
- Python: `.venv/bin/python`
- After any `server.py` change: **restart Claude** (not just the script)
- SMITHERY_API_KEY: `0d45e823-8fd8-411a-9026-d50c3437ea21` (in .env + mcp.json)
- EXA_API_KEY: in `.env` only (not in mcp.json — may be relevant to the bug)
