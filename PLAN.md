# KitsuneMCP — Implementation Plan (v0.12.0)

Generated after deep audit. Execute in order — each section is self-contained.
Start a fresh Claude Code session, say "implement PLAN.md" and work through the checklist.

---

## Current state

- Version: `0.11.0` (pyproject.toml + package.json) — needs bump to `0.12.0`
- Git: `main`, 6 commits ahead of `v0.11.0` tag, 405 tests green
- Entry points: `server.py` (lean, 9 tools ~650 tokens), `server_forge.py` (all tools ~1700 tokens)
- Open issue: #9 (parameter aliasing for convert_time — external server)
- Workflow rule: test → stage → commit → push as one motion. Never force-push.

---

## Item 1 — MCP Registry publish fix (SMALL — do first)

**Root cause:** `.github/workflows/publish.yml` pins `mcp-publisher` at `v1.5.0`.
The MCP Registry changed OIDC audience binding in `v1.7.6` (2026-04-30).
Every publish since v0.8.x has silently skipped the registry leg. PyPI and npm work fine.

**Fix:** In `.github/workflows/publish.yml`, find the line downloading
`mcp-publisher_linux_amd64.tar.gz` at version `v1.5.0` and bump it to the latest
release (check https://github.com/modelcontextprotocol/registry/releases).

**After tagging v0.12.0**, backfill all missing versions:
```bash
gh workflow run publish.yml --ref v0.9.0
gh workflow run publish.yml --ref v0.10.0
gh workflow run publish.yml --ref v0.10.1
gh workflow run publish.yml --ref v0.10.2
gh workflow run publish.yml --ref v0.11.0
gh workflow run publish.yml --ref v0.12.0
```
PyPI/npm legs have `skip-existing: true` — they no-op; only the registry leg runs.

---

## Item 2 — Merge Dependabot PRs (TRIVIAL)

Two open PRs:
- PR #1: `actions/setup-python` v5 → v6
- PR #2: `actions/checkout` v4 → v6

Both safe — no API-breaking changes, CI passes, SHA-pinned.

```bash
gh pr merge 1 --merge
gh pr merge 2 --merge
```

---

## Item 3 — SSRF protection in `fetch()` and `craft()` (SMALL — security)

**Problem:** `skill()` in `kitsune_mcp/tools/onboarding.py:32` has `_is_safe_url()`
blocking private IPs (127.x, 10.x, 192.168.x, 169.254.x). `fetch()` in `exec.py`
and the `_endpoint_proxy` closure in `craft()` (`morph.py`) have no such check —
inconsistency, not intentional design.

`_is_safe_url` is already defined at `kitsune_mcp/tools/onboarding.py:32`.

### Fix `fetch()` — `kitsune_mcp/tools/exec.py`

Add at the top of `fetch()` before the HTTP call:
```python
from kitsune_mcp.tools.onboarding import _is_safe_url
if not _is_safe_url(url) and not os.getenv("KITSUNE_ALLOW_LOCAL_FETCH"):
    return (
        f"Blocked: '{url}' resolves to a private/loopback address. "
        "Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow local URLs."
    )
```

### Fix `craft()` — `kitsune_mcp/tools/morph.py`

Add after the existing `url.startswith(...)` check (around line 424):
```python
from kitsune_mcp.tools.onboarding import _is_safe_url
if not _is_safe_url(url) and not os.getenv("KITSUNE_ALLOW_LOCAL_FETCH"):
    return (
        f"Blocked: '{url}' is a private/loopback address. "
        "Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow local URLs."
    )
```

### Tests
Add to `tests/test_ssrf.py` (new file):
- `fetch("http://127.0.0.1/")` → returns "Blocked"
- `fetch("http://169.254.169.254/latest/meta-data/")` → returns "Blocked"
- `fetch("https://example.com")` → passes (mock httpx)
- Same assertions for a crafted tool with a private URL

---

## Item 4 — Issue #9: Parameter aliasing in proxy_fn (SMALL — high user value)

**Problem:** `convert_time` from `mcp-server-time` expects `source_timezone` /
`target_timezone`. Users write `from_timezone` / `to_timezone`. The upstream server
can't be changed. This causes 2+ failed attempts for every new user of the time server.

**File:** `kitsune_mcp/shapeshift.py` — in `_make_proxy()`, the `proxy_fn` closure.

### Add alias map (module-level constant near top of shapeshift.py)

```python
# Common param name synonyms. Applied only when the key is absent from the
# tool schema — never overwrites a key the schema actually declares.
_PARAM_ALIASES: dict[str, str] = {
    "from": "source",
    "to": "target",
    "from_timezone": "source_timezone",
    "to_timezone": "target_timezone",
    "src": "source",
    "dst": "target",
    "dest": "target",
    "origin": "source",
    "destination": "target",
    "from_lang": "source_language",
    "to_lang": "target_language",
    "input_lang": "source_language",
    "output_lang": "target_language",
}
```

### Modify `proxy_fn` (after the None-cleaning and realpath steps, before execute)

```python
# Alias normalization — remap common synonyms when the original key is not
# in the schema but its alias is. Helps servers with non-intuitive param names
# (e.g. source_timezone vs from_timezone in mcp-server-time).
_schema_props = set(props.keys())  # props is already in scope from _make_proxy
if any(k in _PARAM_ALIASES and k not in _schema_props for k in cleaned):
    remapped = {}
    for k, v in cleaned.items():
        if k not in _schema_props and k in _PARAM_ALIASES:
            canonical = _PARAM_ALIASES[k]
            if canonical in _schema_props:
                remapped[canonical] = v
                continue
        remapped[k] = v
    cleaned = remapped
```

Note: `props` is already computed in `_make_proxy` at the outer scope — use it directly.

### Tests
Add to a new `tests/test_param_aliases.py`:
```python
def test_from_to_timezone_aliased():
    from kitsune_mcp.shapeshift import _PARAM_ALIASES
    # Simulate the alias logic
    props = {"source_timezone", "target_timezone", "time"}
    cleaned = {"from_timezone": "UTC", "to_timezone": "Asia/Tokyo", "time": "09:00"}
    remapped = {}
    for k, v in cleaned.items():
        if k not in props and k in _PARAM_ALIASES and _PARAM_ALIASES[k] in props:
            remapped[_PARAM_ALIASES[k]] = v
        else:
            remapped[k] = v
    assert remapped == {"source_timezone": "UTC", "target_timezone": "Asia/Tokyo", "time": "09:00"}

def test_alias_does_not_override_valid_key():
    # If user passes both "from" and "source", only "source" wins (it's in schema)
    props = {"source", "target"}
    cleaned = {"source": "A", "from": "B"}  # "source" is valid; "from" is alias
    # After aliasing: "from" -> "source" only if "source" not in cleaned
    # Since "source" is already there, "from" should be ignored or kept as-is
    ...
```

---

## Item 5 — Surface silent registration failures (SMALL — debuggability)

**Problem:** In `kitsune_mcp/shapeshift.py`, `_register_proxy_tools()` wraps
`mcp.add_tool()` in `except Exception: pass`. Tools silently fail to register.

**Fix:** Change `_register_proxy_tools()` to return `(list[str], list[tuple[str, str]])`.

### `kitsune_mcp/shapeshift.py` — change `_register_proxy_tools` return type

```python
def _register_proxy_tools(
    server_id: str, tools: list, transport, config: dict,
    base_tool_names: set = None,
    only: set[str] | None = None,
) -> tuple[list[str], list[tuple[str, str]]]:
    registered = []
    failed = []
    for tool_schema in tools:
        raw_name = tool_schema.get("name", "")
        if not raw_name:
            continue
        if only is not None and raw_name not in only:
            continue
        proxy_name = _proxy_name_for(server_id, raw_name, base_tool_names)
        proxy = _make_proxy(server_id, tool_schema, transport, config, proxy_name)
        try:
            mcp.add_tool(proxy)
            registered.append(proxy_name)
        except Exception as e:
            failed.append((raw_name, str(e)[:120]))
    return registered, failed
```

### `kitsune_mcp/tools/morph.py` — update `_commit_shapeshift`

Find where `_register_proxy_tools` is called (~line 48) and unpack both values:
```python
registered, reg_failures = _state._register_proxy_tools(
    server_id, tool_schemas, transport, resolved_config, _state._BASE_TOOL_NAMES, only
)
```

Then in the output block (after the tool list):
```python
if reg_failures:
    lines.append(f"\n⚠️  {len(reg_failures)} tool(s) failed to register:")
    for name, err in reg_failures:
        lines.append(f"  {name}: {err}")
```

Also update the pool-connection branch in `shapeshift()` which calls `_register_proxy_tools` directly — unpack and discard failures there (or surface them too).

---

## Item 6 — `auto()` prefers stdio over HTTP when all else equal (1 LINE)

**File:** `kitsune_mcp/tools/onboarding.py` — `_candidate_rank()` function (around line 183).

**Current:**
```python
return (has_missing, is_smithery_http, not is_official)
```

**Fix:**
```python
return (has_missing, is_smithery_http, not is_official, not (s.transport == "stdio"))
```

Effect: `mcp-server-time` (official, stdio, free) → `(False, False, False, False)` beats a
hypothetical official HTTP server `(False, False, False, True)`. One character, correct
server selection for all time/weather/utility queries where local and remote versions exist.

---

## Item 7 — Session persistence for crafted tools and connections (MEDIUM)

**Problem:** Everything in `session` is lost on restart except `skills`. Specifically:
- `crafted_tools` — user defined these HTTP endpoint tools with explicit effort
- `connections` metadata — user's named server aliases (sans PIDs, which are dead)

**What NOT to persist:** `current_form`, `shapeshift_tools` (process is dead), PIDs.

### `kitsune_mcp/session.py` — add save/load functions

```python
import json
from pathlib import Path

_KITSUNE_HOME = Path(os.getenv("KITSUNE_HOME", Path.home() / ".kitsune"))
_STATE_PATH = _KITSUNE_HOME / "state.json"

def _save_state() -> None:
    _KITSUNE_HOME.mkdir(parents=True, exist_ok=True)
    state = {
        "crafted_tools": session.get("crafted_tools", {}),
        # Strip runtime fields (pid, started_at) — they're dead after restart
        "connections": {
            k: {f: v for f, v in conn.items() if f not in ("pid", "started_at")}
            for k, conn in session.get("connections", {}).items()
        },
        # Cap explored history to 100 entries (keep most recent)
        "explored": dict(list(session.get("explored", {}).items())[-100:]),
    }
    try:
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass

def _load_state() -> None:
    try:
        with open(_STATE_PATH) as f:
            state = json.load(f)
        session.setdefault("crafted_tools", {}).update(state.get("crafted_tools", {}))
        session.setdefault("connections", {}).update(state.get("connections", {}))
        session.setdefault("explored", {}).update(state.get("explored", {}))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
```

### Hook into existing lifecycle

- Call `_load_state()` at the end of `_load_skills()` (which runs at module init)
- Call `_save_state()` at the end of `_save_skills()` (which runs when skills are modified)
- Call `_save_state()` in the `atexit` handler in `transport.py` alongside `_kill_all_pool_processes()`

### Re-register crafted tools on startup

After `_load_state()`, re-register loaded `crafted_tools` with the FastMCP app.
The `_endpoint_proxy` closure can be reconstructed from stored `url`, `method`, `description`, `params`.
Add a `_restore_crafted_tools()` function in `session.py` that calls `mcp.add_tool()` for each.
Call it from `server.py` after all imports (but the `mcp` import creates a circular dep risk — 
use a lazy import inside the function or move it to `app.py`).

### Tests

```python
def test_save_load_crafted_tools(tmp_path):
    # Mock _STATE_PATH to tmp_path / "state.json"
    session["crafted_tools"] = {"my_tool": {"url": "https://example.com", ...}}
    _save_state()
    session["crafted_tools"] = {}
    _load_state()
    assert "my_tool" in session["crafted_tools"]

def test_pids_not_persisted(tmp_path):
    session["connections"] = {"key": {"name": "test", "pid": 12345, "command": "npx foo"}}
    _save_state()
    session["connections"] = {}
    _load_state()
    assert "pid" not in session["connections"]["key"]
```

---

## Item 8 — CHANGELOG + version bump to v0.12.0 (MEDIUM — do last before tagging)

### Files to update

| File | Change |
|---|---|
| `CHANGELOG.md` | Prepend v0.12.0 section (see below) |
| `pyproject.toml` | `version = "0.11.0"` → `"0.12.0"` |
| `package.json` | `"version": "0.11.0"` → `"0.12.0"` |
| `server.json` | version field if present |

### Commits being documented (6 commits, 30+ issues fixed)

```
a6290d1  fix issues #23 #24 #25 #26 #27 #28 #29 #30 #31 #32
6ffdb0f  fix issues #17 #18 #19 #20 #21 #22
b221d90  fix: async lock on tool registry + pre-shed validation for source='local'
d28c660  fix #16: source='local' on HTTP-only servers + call() ignoring shapeshift transport
33e42fe  fix #10: tokens_sent in all transport execute() methods
88c6852  fix issues #12 #13 #14 #15 + README why-MCP section
```

### v0.12.0 CHANGELOG section — key points

**Security:**
- `fetch()` and `craft()` now block private/loopback URLs (SSRF protection, consistent with `skill()`). Override with `KITSUNE_ALLOW_LOCAL_FETCH=1`.

**New features:**
- `server_args` parameter on `shapeshift()` — pass CLI arguments to stdio servers (e.g. `shapeshift("server-filesystem", server_args=["/private/tmp"])`)
- Parameter aliasing in proxy tools — `from_timezone` is silently remapped to `source_timezone`, `to` to `target`, etc. Works for any MCP server with non-intuitive param names.
- Shapeshifted tool registration failures now surface in the output instead of being silently swallowed.
- `crafted_tools` and `connections` metadata now persist across server restarts in `~/.kitsune/state.json`.

**Reliability:**
- `_registry_lock` (`asyncio.Lock`) prevents concurrent shapeshifts from leaving orphaned tools in the registry. Without it, two concurrent shapeshifts could interleave shed and register, leaving both servers' tools mounted while session only tracked one.
- `atexit` handler kills all pooled processes on interpreter exit — fixes memory leak (#11) and "RuntimeError: Event loop is closed" teardown noise (#23).
- Probe processes from `inspect()`/`compare()` are killed immediately after `list_tools()` returns — each probe held 200-300MB idle.
- Registry paginated fetch no longer caches empty/partial results on transient failures — returns stale cache instead of poisoning TTL window.
- `shiftback(kill=True)` no longer mass-kills unrelated `connect()` sessions when pool key is missing — warns instead.
- `source='local'` on HTTP-only Smithery servers now returns a clear error BEFORE shedding the current form.
- `call()` uses the shapeshifted session's pooled transport instead of re-resolving from registry (which always picked HTTP for Smithery servers regardless of `shapeshift(source='local')`).

**UX:**
- `auto()` prefers official stdio servers over Smithery HTTP — `mcp-server-time` beats `timely` when no Smithery key is set.
- `auto()` surfaces registry fetch failures instead of silently returning "no tools listed".
- `compare()` shows `—` instead of `?` for unknown values; error labels are human-readable ("HTTP error" not "HTTPStatusError").
- `search()` warning uses actual exception class per registry, not hardcoded "timeout".
- `shapeshift()` output includes wall-clock timing — cold npm installs show "12.3s — warm calls will be instant".
- Filesystem server shapeshift proactively hints about `server_args` when no allowed dirs are passed.
- macOS `/tmp` → `/private/tmp` symlink resolved in proxy args before forwarding to inner server.
- `shlex.split()` used consistently in pool-connection shapeshift branch (was `str.split()`).
- httpx INFO logging suppressed by default (`KITSUNE_DEBUG_HTTP=1` to re-enable).

**Correctness:**
- `tokens_sent` now tracked in `StdioTransport`, `PersistentStdioTransport`, `WebSocketTransport` (was only `HTTPSSETransport`).
- `key()` masks secret value in response — raw value no longer appears in conversation context. `.env` written with `0o600` permissions.
- `_infer_args_from_task` returns `{}` when tool has multiple required string params — no partial fills.
- `__version__` exposed via `importlib.metadata`, shown as first line of `status()`.

**Testing:**
- 6 integration tests for lean vs forge tool surface (prevents silent profile drift).
- `_registry_lock` concurrency tests prove the race is eliminated.
- `tokens_sent` tests for all three previously-broken transports.
- SSRF tests for `fetch()` and `craft()`.
- Parameter alias tests for `proxy_fn`.

---

## Execution checklist

```
[ ] Item 1: Bump mcp-publisher version in .github/workflows/publish.yml
[ ] Item 2: Merge Dependabot PRs (#1 and #2)
[ ] Item 3: SSRF fix — fetch() and craft(), add tests/test_ssrf.py
[ ] Item 4: Parameter aliasing — shapeshift.py proxy_fn, close issue #9
[ ] Item 5: Surface registration failures — shapeshift.py + morph.py
[ ] Item 6: auto() ranking — add stdio preference (1 line in onboarding.py)
[ ] Item 7: Session persistence — session.py save/load, re-register crafted_tools
[ ] Item 8: CHANGELOG + version bump (pyproject.toml, package.json, server.json)
[ ] Run: python3 -m pytest tests/ -q  (should be 420+ passing)
[ ] Tag: git tag v0.12.0 && git push origin v0.12.0
[ ] Verify: pip install kitsune-mcp==0.12.0 && python3 -c "import kitsune_mcp; print(kitsune_mcp.__version__)"
[ ] Backfill MCP Registry for v0.9.0 through v0.12.0
[ ] Close issue #9
```

---

## Key files reference

| Area | File |
|---|---|
| Proxy tool creation, param aliasing | `kitsune_mcp/shapeshift.py` |
| shapeshift / shiftback / craft / connect | `kitsune_mcp/tools/morph.py` |
| auto() / key() / onboard() | `kitsune_mcp/tools/onboarding.py` |
| search / inspect / compare / status | `kitsune_mcp/tools/discovery.py` |
| call / run / fetch / test / bench | `kitsune_mcp/tools/exec.py` |
| Session state + persistence | `kitsune_mcp/session.py` |
| Transport / process pool / atexit | `kitsune_mcp/transport.py` |
| Registry fan-out + TTL cache | `kitsune_mcp/registry.py` |
| HTTP client / token estimate | `kitsune_mcp/utils.py` |
| FastMCP app + registry lock | `kitsune_mcp/app.py` |
| Lean profile + tool pruning | `server.py` |
| CI publish workflow | `.github/workflows/publish.yml` |
