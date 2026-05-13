# Kitsune v0.19 — Intent Router Plan

## Context and State

**What Kitsune is**: A shape-shifting MCP hub. One entry in your MCP config. Searches 7
registries (10,000+ servers), mounts any server at runtime via shapeshift(), relays tool
calls as a transparent proxy. No restarts. No config changes per server.

**Published version**: v0.18.3 (PyPI + npm). Lean profile: 5 tools — `status`, `search`,
`auth`, `shapeshift`, `call`. ~400 tokens overhead. Forge profile: all ~20 tools.

**Repo**: `/Users/marty/claude-projects/KitsuneMCP/`

**Key files**:
- `server.py` — entry point, `_LEAN_TOOLS` set on line 136
- `kitsune_mcp/tools/onboarding.py` — `auto()`, `auth()`, inference helpers
- `kitsune_mcp/tools/shapeshift.py` — `shapeshift()`, `_do_unmount()`
- `kitsune_mcp/tools/discovery.py` — `search()`, `status()`
- `kitsune_mcp/registry.py` — `MultiRegistry`, `_relevance_score()`, `_works_now_score`
- `kitsune_mcp/official_registry.py` — `_SEED_SERVERS` (hardcoded seed list)
- `kitsune_mcp/transport.py` — `PersistentStdioTransport`, `_process_pool`, atexit cleanup
- `kitsune_mcp/constants.py` — all timeouts, trust tiers, limits
- `tests/` — pytest suite, 489 passing

**What changed in v0.18.3 (this session)**:
- `_extract_timezone_from_nl()` added to onboarding.py — NL → IANA timezone
- `auth()` no longer invents `https://<name>.run.tools` when `srv.url` is None
- `_SEED_SERVERS` expanded with GitHub, Slack, Postgres, Google Maps, Brave Search
- Timezone test updated to expect extracted value not empty dict

---

## Vision for v0.19: Intent Router for All Tool Categories

**The plan** (from `/Users/marty/codex/kitsune-test/kitsune-simple-plan.md`):

> Make Kitsune a task-first MCP router with safe defaults, strong `auto()`, structured
> recovery, and minimal visible complexity. Compatible with all kinds of tools for
> working, automating and coding.

**The key shift**: Kitsune currently presents at the infrastructure layer (find server →
mount → call). v0.19 presents at the intent layer (describe task → Kitsune handles the
rest). `auto()` becomes the front door. Everything else becomes power-user tooling.

**Target tool categories** (all must work, not just a few curated servers):

| Category | Representative servers | Key pattern |
|---|---|---|
| **Web & search** | Brave, Exa, Linkup, Firecrawl, Puppeteer | `query` param, free API keys |
| **File & storage** | filesystem, git, S3, Drive | path params, roots needed |
| **Code & repos** | GitHub, GitLab, code search, terminal | PAT / OAuth, repo context |
| **Databases** | Postgres, SQLite, MySQL, MongoDB | connection string, SQL |
| **Shell & automation** | bash, shell, cron, n8n, Make | `command` param, no keys |
| **Productivity** | Notion, Linear, Jira, Asana, Confluence | OAuth / workspace tokens |
| **Communication** | Slack, Gmail, Teams, Discord | bot token / OAuth |
| **Cloud & infra** | AWS, GCP, Azure, Docker, Kubernetes | cloud credentials |
| **Memory & AI** | Mem0, knowledge graph, Context7 | init-first, search patterns |
| **Time & utilities** | mcp-server-time, weather, finance | structured params |

The architecture must work **generically** for unknown servers (via schema-driven
inference) and **excellently** for common servers (via category adapters).

---

## Architecture Decisions

### Decision 1: auto() moves to lean

`server.py:136`:
```python
_LEAN_TOOLS = {"status", "search", "auth", "shapeshift", "call"}
```
Change to:
```python
_LEAN_TOOLS = {"status", "search", "auth", "shapeshift", "call", "auto"}
```

This is one line. `auto()` already does everything the plan describes. It just isn't
exposed in lean. This is the single highest-ROI change in the entire plan.

Also update the guard inside `auto()` itself (`onboarding.py:150-152`):
```python
_KITSUNE_LEAN: frozenset[str] = frozenset({
    "auth", "call", "search", "shapeshift", "status",  # ← add "auto"
})
```

### Decision 2: Category-based intent routing

`auto()` currently uses keyword search to find servers. The problem: "run my test suite"
doesn't contain the word "github" or "shell", but the intent is clearly in the
code/automation category. A two-step approach:

1. **Classify intent** into a category using a lightweight keyword map
2. **Boost servers** of the matching category in ranking

Implementation: a new `_classify_task(task: str) -> str | None` function in
`onboarding.py` that returns a category name like `"web_search"`, `"file_ops"`,
`"code_ops"`, `"database"`, `"shell"`, `"productivity"`, `"communication"`,
`"memory"`, `"time_util"` or `None` (unknown).

Then in `_candidate_rank()`, add a category-match bonus so the right type of server
ranks higher when the task intent is clear.

### Decision 3: Schema-driven inference

The current `_infer_args_from_task()` works on parameter *names* (`query`, `timezone`,
`path`, etc.). This works for well-known param names but fails for servers that use
unusual names.

The fix: also analyze parameter *descriptions* and the overall *tool description* to
classify what kind of value each parameter needs, even when the name is unfamiliar.

A `sql_query: string` param with description "SQL query to execute" → treat as a code
param (not a search param, not a path).
A `command: string` param with description "Shell command to run" → treat as a command
param; only fill if task looks like a shell command (starts with a verb or program name).
A `repo: string` param with description "GitHub repository (owner/name)" → treat as a
repo identifier.

Implementation: a new `_classify_param(name: str, description: str, tool_description:
str) -> str` function that returns the semantic type of the parameter:
`"search_query"` | `"shell_command"` | `"sql_query"` | `"code"` | `"file_path"` |
`"url"` | `"identifier"` | `"free_text"` | `"unknown"`

Then `_infer_args_from_task()` uses the semantic type instead of just the name.

### Decision 4: Category-level adapter module

Instead of per-server adapters (which don't scale to 10,000+ servers), write
**category-level adapters** that define common argument patterns, required setup, and
error recovery for an entire class of servers.

New module: `kitsune_mcp/adapters/`
```
kitsune_mcp/adapters/
    __init__.py       — adapter registry, lookup by category or server ID
    _base.py          — Adapter base class / protocol
    web_search.py     — web/search servers (Brave, Exa, Linkup, Firecrawl)
    file_ops.py       — filesystem, git, S3 (path params, roots, permissions)
    code_ops.py       — GitHub, GitLab, shell, terminal (PAT, repo context)
    database.py       — Postgres, SQLite, MySQL (connection string, SQL)
    productivity.py   — Notion, Linear, Jira, Slack (OAuth / workspace patterns)
    memory.py         — Mem0, knowledge graph (init-first, add/search pattern)
    time_util.py      — mcp-server-time, weather, finance (structured params)
```

Each adapter exports:
```python
CATEGORY: str                              # e.g. "web_search"
KNOWN_IDS: set[str]                        # exact server IDs this adapter handles
KEYWORDS: frozenset[str]                   # task keywords that suggest this category
CREDENTIAL_PATTERN: str                    # e.g. "API_KEY", "OAUTH", "CONNECTION_STRING"

def infer_args(task: str, tool_schema: dict) -> dict | None:
    """Return inferred args or None to fall through to generic inference."""
    ...

def setup_hint(server_id: str, missing_creds: list[str]) -> str:
    """Return category-appropriate setup guidance."""
    ...

def error_hint(server_id: str, error: str) -> str | None:
    """Translate a server error to a human/agent-readable hint. None = no match."""
    ...
```

The `web_search.py` adapter, for example, would handle both Brave and Exa (different
`query`-style tools) and know that their API keys are free-tier (link to signup in hint).

### Decision 5: Standardized blocked-message format

Every error path in every tool should use the same helper:

```python
def _blocked(what: str, why: str, fix: str, fallback: str = "") -> str:
    lines = [f"✗ Blocked: {what}", f"  Why: {why}", f"  Fix: {fix}"]
    if fallback:
        lines.append(f"  Alt:  {fallback}")
    return "\n".join(lines)
```

Apply to: `auto()` missing creds block (onboarding.py:211-222), `auto()` no tools
block (onboarding.py:237-252), `auth()` no URL block (onboarding.py:714-718),
`shapeshift()` trust gate, filesystem root hint (shapeshift.py:149-152).

### Decision 6: Works-now ranking signal (v0.19 or v0.20)

Add `_works_now_score(srv: ServerInfo) -> float` to `registry.py`. Returns 0.0–1.0.

Signals (can be combined):
- Credentials: all required creds set in env → +0.4
- Source tier: official → +0.3, mcpregistry/glama → +0.2, smithery → +0.1, npm/pypi → 0
- Transport: stdio (local, free) → +0.1 over http
- Token cost: low token_cost → small bonus (penalize >5K token servers)
- No docker required → +0.1 (Docker not always available)

`auto()` already has `_candidate_rank()` which approximates this. Refactor it to use
`_works_now_score()` so the same logic is available to `search()` display ordering too.

### Decision 7: Structured output footer (v0.20, optional)

Every major operation appends a machine-readable JSON block when
`KITSUNE_STRUCTURED=1` is set:

```
✓ Mounted 3 tools from mcp-server-time.

---
{"ok":true,"server":"mcp-server-time","tools":["get_current_time"],"confidence":1.0,"next":null}
```

For blocked states:
```
✗ Blocked: filesystem server needs allowed directories.

---
{"ok":false,"blocked_reason":"no_roots","fix":"shapeshift(\"@modelcontextprotocol/server-filesystem\", server_args=[\"/tmp\"])","retryable":true}
```

Gate on env var initially. Decide in v0.20 whether to always include it.
Fields: `ok`, `server`, `tool`, `tools`, `confidence`, `blocked_reason`, `fix`,
`fallback`, `retryable`, `next`.

---

## Implementation Phases

### Phase 1 — The unlock (v0.19, ~2 hours)

**Changes:**
1. `server.py:136` — add `"auto"` to `_LEAN_TOOLS`
2. `onboarding.py:150` — add `"auto"` to `_KITSUNE_LEAN` guard inside `auto()`
3. `onboarding.py` — add `_blocked()` helper, apply to 4 error paths in auto() and auth()
4. `shapeshift.py:149` — convert filesystem root hint to use `_blocked()` format
5. `pyproject.toml` + `package.json` — bump to `0.19.0`
6. `README.md` — show `auto()` as first tool in lean surface table

**What this achieves**: A new user with only Kitsune in their config gets `auto()` in
lean. They can `auto("what time is it in UTC")` and get a result. Or `auto("fetch
https://...")` and get a result. Or `auto("list files in /tmp")` and get either a result
or a single exact next step.

**Tests to add**: `tests/test_v019_intent_router.py`
- `test_auto_in_lean_profile()` — verify "auto" is in LEAN_TOOLS
- `test_blocked_format_consistency()` — verify _blocked() is used in key paths
- `test_auto_utc_time()` — integration: auto("what time is it in UTC") works

### Phase 2 — Category routing + schema inference (v0.19, ~4 hours)

**New function: `_classify_task(task: str) -> str | None`**

```python
_CATEGORY_KEYWORDS: dict[str, frozenset[str]] = {
    "web_search": frozenset({
        "search", "find", "look up", "google", "web", "internet", "news",
        "results", "query", "browse",
    }),
    "file_ops": frozenset({
        "file", "files", "directory", "folder", "path", "read", "write",
        "list", "filesystem", "disk", "local",
    }),
    "code_ops": frozenset({
        "github", "gitlab", "repo", "repository", "commit", "pull request",
        "pr", "issue", "branch", "code", "git", "diff", "merge",
    }),
    "shell": frozenset({
        "run", "execute", "shell", "bash", "command", "terminal", "script",
        "process", "install", "build", "compile", "test", "deploy",
    }),
    "database": frozenset({
        "sql", "query", "database", "db", "postgres", "mysql", "sqlite",
        "table", "select", "insert", "update", "schema",
    }),
    "productivity": frozenset({
        "notion", "linear", "jira", "asana", "task", "project", "ticket",
        "document", "page", "workspace", "note",
    }),
    "communication": frozenset({
        "slack", "email", "gmail", "message", "send", "notify", "channel",
        "team", "chat", "discord",
    }),
    "memory": frozenset({
        "remember", "recall", "memory", "store", "retrieve", "note",
        "knowledge", "context", "history",
    }),
    "time_util": frozenset({
        "time", "timezone", "clock", "date", "weather", "currency",
        "convert", "calculate",
    }),
}

def _classify_task(task: str) -> str | None:
    task_lc = task.lower()
    scores: dict[str, int] = {}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in task_lc)
        if score > 0:
            scores[category] = score
    if not scores:
        return None
    return max(scores, key=scores.__getitem__)
```

**New function: `_classify_param(name: str, desc: str, tool_desc: str) -> str`**

```python
def _classify_param(name: str, desc: str, tool_desc: str) -> str:
    combined = f"{name} {desc} {tool_desc}".lower()
    if any(w in combined for w in ("sql", "query sql", "sql query", "execute query")):
        return "sql_query"
    if any(w in combined for w in ("shell", "bash", "command to run", "execute command")):
        return "shell_command"
    if any(w in combined for w in ("repository", "repo", "owner/repo", "github.com")):
        return "repo_identifier"
    if any(w in combined for w in ("connection string", "database url", "dsn", "conn_str")):
        return "connection_string"
    if name in _PATH_PARAM_NAMES:
        return "file_path"
    if name in _SEARCH_PARAM_NAMES:
        return "search_query"
    if name in _STRUCTURED_PARAM_NAMES:
        return "structured_identifier"
    return "free_text"
```

Wire both into `_infer_args_from_task()` and `_candidate_rank()`.

**Files changed**: `kitsune_mcp/tools/onboarding.py`

### Phase 3 — Adapter module (v0.19 or v0.20, ~1 day)

Create `kitsune_mcp/adapters/` module. Start with the three highest-friction categories:

**`file_ops.py`** (covers @modelcontextprotocol/server-filesystem, mcp-server-git):
- `infer_args`: extract path from task ("read /tmp/foo.txt" → `{"path": "/tmp/foo.txt"}`)
- `setup_hint`: "filesystem server needs allowed directories. Fix: shapeshift(\"...\",
  server_args=[\"/your/path\"])"
- `error_hint`: detect "Access denied" / "not allowed" → show root-path fix

**`code_ops.py`** (covers GitHub, GitLab, git):
- `infer_args`: extract owner/repo from task ("check issues in kaiser-data/kitsune-mcp"
  → `{"owner": "kaiser-data", "repo": "kitsune-mcp"}`)
- `setup_hint`: "GitHub server needs GITHUB_PERSONAL_ACCESS_TOKEN. Get one at
  github.com/settings/tokens"
- `error_hint`: 401 → show auth() command

**`database.py`** (covers Postgres, SQLite, MySQL):
- `infer_args`: if task looks like SQL, pass it directly; if NL, refuse and hint
- `setup_hint`: connection string format per DB type
- `error_hint`: connection refused → check connection string / server running

**`web_search.py`** (covers Brave, Exa, Linkup, Firecrawl):
- `infer_args`: pass full NL query directly (search params are free text)
- `setup_hint`: "Brave API key is free at brave.com/search/api"
- `error_hint`: 401 → show auth() command with link

**`shell.py`** (covers shell/terminal/bash servers):
- `infer_args`: if task looks imperative (starts with verb/program), pass as command
- `setup_hint`: no typical credentials needed; check server is available
- `error_hint`: permission denied → check shell server config

Adapter lookup in `auto()`:
```python
# onboarding.py, inside auto(), before _infer_args_from_task()
from kitsune_mcp.adapters import get_adapter
adapter = get_adapter(server_id) or get_adapter_for_category(_classify_task(task))
if adapter:
    inferred = adapter.infer_args(task, selected_tool_schema)
    if inferred is not None:
        arguments = inferred
```

**Files changed**: new `kitsune_mcp/adapters/` directory, `kitsune_mcp/tools/onboarding.py`

### Phase 4 — Works-now ranking (v0.19 or v0.20, ~2 hours)

Add to `registry.py`:

```python
def _works_now_score(srv: "ServerInfo") -> float:
    """Higher = more likely to work right now without setup."""
    from kitsune_mcp.credentials import _resolve_config
    score = 0.0
    # All required creds set → big boost
    _, missing = _resolve_config(srv.credentials or {}, {})
    if not missing:
        score += 0.4
    # Source tier
    tier_bonus = {
        "official": 0.3, "mcpregistry": 0.2, "glama": 0.2,
        "smithery": 0.1, "npm": 0.05, "pypi": 0.05,
    }
    score += tier_bonus.get(srv.source, 0.0)
    # Local stdio preferred over HTTP (no API key, no rate limits)
    if srv.transport == "stdio":
        score += 0.1
    # Penalize very high token cost servers
    if srv.token_cost and srv.token_cost > 5000:
        score -= 0.05
    return min(score, 1.0)
```

Refactor `_candidate_rank()` in `auto()` to call `_works_now_score()`. Add a flag to
`MultiRegistry.search()` that optionally sorts by works-now score instead of relevance.

### Phase 5 — Structured output (v0.20)

Implement after Phase 1–4 are stable and real usage shows which fields agents actually
need. Gate on `KITSUNE_STRUCTURED=1` env var initially.

---

## Success Criteria

A fresh user (or a Codex agent) with only `kitsune-mcp` in their MCP config should be
able to complete all of these with `auto()` — either completing on first try or returning
exactly one actionable next step:

| Task | Expected outcome |
|---|---|
| `auto("what time is it in UTC")` | Returns current UTC time |
| `auto("fetch https://modelcontextprotocol.io")` | Returns page content |
| `auto("list files in /tmp")` | Returns listing OR → `shapeshift("...", server_args=["/tmp"])` |
| `auto("search the web for MCP protocol 2025")` | Returns results OR → `auth("BRAVE_API_KEY", "...")` |
| `auto("search memory for project notes")` | Returns memory OR → `shapeshift("memory")` first |
| `auto("find a GitHub MCP server")` | Returns GitHub server info + setup steps |
| `auto("run git log in /my/repo")` | Returns log OR → connect command |
| `auto("query my postgres database for users")` | Returns hint about connection string |
| `auto("send a slack message to #general")` | Returns token setup guide |

Each result either completes or gives one exact next step. No raw MCP errors. No
unexplained failures.

---

## What NOT to Do

- **Do not** add server adapters for every server individually — use category adapters
- **Do not** change the shapeshift/call primitive tools — they stay in lean for manual control
- **Do not** implement the Gateway Mode (credential harvest from other configs) in this
  version — that's v0.20 (plan at `/Users/marty/.claude/plans/cozy-hugging-crane.md`)
- **Do not** remove `shapeshift` and `call` from lean — they are still needed for explicit
  control and for servers where auto() can't infer enough context
- **Do not** add telemetry infrastructure — session-level tracking in `session["stats"]`
  is sufficient for v0.19

---

## Version Targets

| Version | Scope |
|---|---|
| v0.19.0 | Phase 1 (auto in lean + _blocked format) + Phase 2 (category routing) |
| v0.19.1 | Phase 3 (adapter module: file_ops, code_ops, web_search, database, shell) |
| v0.19.2 | Phase 4 (works-now ranking) |
| v0.20.0 | Gateway Mode (cozy-hugging-crane.md plan) + structured output |

---

## Build and Test Commands

```bash
# Lint
ruff check server.py server_forge.py kitsune_mcp/ tests/

# Tests
python3 -m pytest tests/ -x -q

# Build
python3 -m build

# Publish PyPI (need fresh token scoped to kitsune-mcp)
python3 -m twine upload dist/kitsune_mcp-0.19.0* --username __token__ --password pypi-<token>

# Publish npm (need npm login first)
npm login
npm publish
```

---

## Notes on Current Codebase Quirks

- `_state.py` re-exports: all `# noqa: F401` comments are intentional — ruff must NOT
  remove them. Tests mock via `mock.patch("kitsune_mcp.tools._state.X")`. Never run
  `ruff --fix` on `_state.py` without reviewing removals.
- `shapeshift()` with no args = unmount (calls `_do_unmount()` → `shiftback()`).
  `shiftback` is still available in forge for explicit control with kill/uninstall flags.
- Smithery gate: `shapeshift.py:287` fires when `srv_source == "smithery"` and
  `SMITHERY_API_KEY` is not set. Tests that use smithery-sourced servers must mock
  `_state._smithery_available` to return True.
- `~/.kitsune/.env` is loaded at startup and wins over CWD `.env`. See `server.py:26-27`.
- `importlib.metadata.version("kitsune-mcp")` reads the *installed* package version,
  not `pyproject.toml`. Version shown in `status()` = installed version. After bumping
  pyproject.toml, run `pip install -e .` or reinstall to pick it up.
