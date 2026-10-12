# KitsuneMCP v0.18.0 — 5-Tool Lean Surface Redesign

## Context

The lean profile has grown to 10 tools across two parallel paradigms (NL-first `auto` vs explicit pipeline), creating decision fatigue for agents. `auto` without `server_hint` is unreliable (Issue #34). The goal is a 5-tool lean surface where every tool is deterministic, the mental model is a single linear flow, and agents never have to decide "which of these 3 similar tools do I pick?"

**Flow after this change:** `status → search → auth → shapeshift → call → shapeshift()`

---

## New Lean Profile (5 tools)

| Tool | Replaces / absorbs |
|------|-------------------|
| `status()` | unchanged + inline first-run guide (replaces `onboard()` pointer) |
| `search(query, compare=False)` | absorbs `compare()` via flag |
| `auth(server_id_or_var, value="")` | NEW — replaces `key` + `login` |
| `shapeshift(server_id="", keep=False, ...)` | combined mount + unmount (replaces `shiftback` in lean) |
| `call(tool, arguments)` | unchanged |

**Forge-only** (still fully functional, just not default): `auto`, `inspect`, `compare`, `key`, `onboard`, `shiftback`, `login`, all existing forge tools.

---

## Key Behaviors

### `shapeshift(server_id="", keep=False)`
- `server_id` non-empty → **mount** (existing logic unchanged)
- `server_id` empty → **unmount**:
  - Default (`keep=False`): kill process + uninstall package (clean slate, next mount always fresh)
  - `keep=True`: unmount tools from surface, keep pool warm + package cached (re-attach soon)
- `shiftback()` stays in forge with its existing `kill=False, uninstall=False` defaults for backward compat

### `auth(server_id_or_var, value="")`
- `value` provided → store as env var (same as `key()`): `auth("EXA_API_KEY", "sk-...")`
- Name is ALL_CAPS → env var status check + prompt: `auth("EXA_API_KEY")` → "not set, use auth('EXA_API_KEY', 'val')"
- Name is lowercase/hyphenated → server ID:
  - stdio with credentials → list missing vars + guide
  - stdio without credentials → "no auth needed, ready to shapeshift"
  - http transport → OAuth: call `ensure_token(base_url)` (handles refresh, full flow if needed)
  - Not found → `search("name")` suggestion

### `search(query, compare=False)`
- `compare=False` (default): ranked list (existing search behavior)
- `compare=True`: side-by-side table (existing compare behavior, calls extracted `_run_compare()`)
- New footer: `auth('<id>') to check credentials | shapeshift('<id>') to mount`

### `status()` first-run
- Replace `"✨ New here? Run onboard() for the 3-step quickstart."` with inline quickstart:
  ```
  ✨ Quick start:
    1. shapeshift("mcp-server-time")
    2. call("get_current_time", {"timezone": "UTC"})
    3. shapeshift()
    More: search("what you need") | auth("SMITHERY_API_KEY", "sm-...") for 3000+ servers
  ```

---

## Files to Modify

### 1. `kitsune_mcp/tools/morph.py` → rename to `kitsune_mcp/tools/shapeshift.py`
- **Rename file**: `git mv kitsune_mcp/tools/morph.py kitsune_mcp/tools/shapeshift.py`
- Update `kitsune_mcp/tools/__init__.py`: change `from kitsune_mcp.tools.morph import ...` → `from kitsune_mcp.tools.shapeshift import ...`
  - Note: no conflict with `kitsune_mcp/shapeshift.py` (top-level proxy module) — this lives in `tools/`
- Change `shapeshift(server_id: str, ctx, ...)` → `shapeshift(server_id: str = "", ctx, keep: bool = False, ...)`
- Add branch at top: `if not server_id: return await _do_unmount(ctx, keep=keep)`
- Add `_do_unmount(ctx, keep)` helper:
  - `keep=True`: run existing `shiftback()` body with `kill=False, uninstall=False`
  - `keep=False`: run existing `shiftback()` body with `kill=True, uninstall=True`
  - Update "still cached" hint: `"To clean up: shapeshift()"` instead of `"shiftback(uninstall=True)"`
- Keep `shiftback()` unchanged (forge backward compat)

### 2. `kitsune_mcp/tools/onboarding.py`
- Remove `login()` (never wired to server.py)
- Add `auth()` (new tool, see behavior above)
- Update `_KITSUNE_LEAN` frozenset inside `auto()`:
  `frozenset({"auth", "call", "search", "shapeshift", "status"})`
- Update `_KITSUNE_FORGE` to include: `"auto", "compare", "inspect", "key", "login", "onboard", "shiftback"`
- Keep `key()` unchanged (forge)

### 3. `kitsune_mcp/tools/discovery.py`
- `search()`: add `compare: bool = False` param; when True delegate to `_run_compare(query, limit)`
- Extract `compare()` body → private `_run_compare(query, limit, probe=False)`
- `compare()` becomes: `return await _run_compare(query, limit, probe)`
- Update `search()` footer: `inspect('<id>') for details` → `auth('<id>') to check credentials | shapeshift('<id>') to mount`
- Update `status()` first-run block: inline quickstart (no `onboard()` pointer)
- Update all `key("FOO", "...")` hint strings → `auth("FOO", "...")`  (in `_compare_probe` action strings + `inspect()` next-step hints)

### 4. `kitsune_mcp/tools/_state.py`
- Add `"auth"` to `_BASE_TOOL_NAMES` set
- Keep `"login"` in `_BASE_TOOL_NAMES` for backward compat (won't be registered if not in profile)

### 5. `kitsune_mcp/tools/__init__.py`
- Change morph import → shapeshift import (step 1 above)
- Add `auth` to import line: `from kitsune_mcp.tools.onboarding import auth, auto, key, onboard, setup, skill`
- Remove `login` (not exported)

### 6. `server.py`
- `_LEAN_TOOLS = {"status", "search", "auth", "shapeshift", "call"}`
- Add `auth` to the import block
- Update header docstring: lean profile now 5 tools (~400 tokens)

### 7. `tests/test_tool_surface.py`
- `LEAN_REQUIRED = {"shapeshift", "search", "auth", "call", "status"}`
- `FORGE_ONLY` add: `"shiftback", "auto", "inspect", "compare", "key", "onboard"`
- Remove `test_compare_is_in_lean()` test
- Update count assertion: `len(_LEAN_TOOLS) == 5`

### 8. Test assertion updates (search-replace)

| File | Old | New |
|------|-----|-----|
| `tests/test_ux_changes.py:188` | `"onboard()" in result` | `"shapeshift(" in result` |
| `tests/test_ux_changes.py:655` | `"shiftback(uninstall=True)" in result` | `"shapeshift()" in result` |
| `tests/test_ux_changes.py:874` | `'key("API_KEY"' in result` | `'auth("API_KEY"' in result` |
| `tests/test_ux_changes.py:1293` | `'key("NOTION_LOCAL_OPS_WORKSPACE_ROOT"' in result` | `'auth("NOTION_LOCAL_OPS_WORKSPACE_ROOT"' in result` |
| `tests/test_probe.py:193` | `'key("EXA_API_KEY"' in result` | `'auth("EXA_API_KEY"' in result` |
| `tests/test_issues_12_13_14_15.py:156` | `"key(" in result` | `"auth(" in result` |
| `tests/test_tools.py:115` | `"key(" in result` | `"auth(" in result` |
| `tests/test_tools.py:614` | `"key(" in result` | `"auth(" in result` |
| `tests/test_v014_fixes.py:158` | `"onboard()" in result` | `"shapeshift(" in result` |
| `tests/test_v014_fixes.py:220` | `"onboard" in result.lower()` | `"search(" in result or "auth(" in result` |

---

## Version & Wiring

- Bump `pyproject.toml` to `0.18.0`
- Add `login` to `_BASE_TOOL_NAMES` for completeness but don't register it
- `auth` in `_KITSUNE_BUILTINS` guard inside `auto()` prevents `auto("auth")` routing to an external server

---

## Verification

```bash
# 1. All tests pass
python3 -m pytest tests/ -x -q

# 2. Lean surface is exactly 5 tools
python3 -c "from server import _LEAN_TOOLS; print(sorted(_LEAN_TOOLS))"
# Expected: ['auth', 'call', 'search', 'shapeshift', 'status']

# 3. Restart MCP server, then via MCP tools:
status()                                      # first-run quickstart shows inline
search("time zones")                          # ranked list
search("time zones", compare=True)            # table view
auth("mcp-server-time")                       # → "no auth needed"
auth("SMITHERY_API_KEY", "sm-...")            # → "Saved: ..."
shapeshift("mcp-server-time")                 # mount
call("get_current_time", {"timezone": "UTC"}) # use
shapeshift()                                  # unmount + kill + uninstall (default)
shapeshift("mcp-server-time")                 # re-mount pulls fresh version
shapeshift(keep=True)                         # unmount but keep warm
```
