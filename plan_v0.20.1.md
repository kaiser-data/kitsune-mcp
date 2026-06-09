# Kitsune v0.20.1 — Implementation Plan

> **For a new Claude session**: Read this file, then implement directly. All context, current code, and exact changes are self-contained below. No exploration needed.

---

## Project context

**KitsuneMCP** (`/Users/marty/claude-projects/KitsuneMCP`) — shape-shifting MCP hub. One config entry, any server on demand. Core tools: `status`, `search`, `auth`, `shapeshift`, `call`, `auto`. All logic in `kitsune_mcp/` package; entry point `server.py`.

**Current version**: `0.20.0` (in `pyproject.toml` and `package.json`)  
**Target version**: `0.20.1`

**Test command**: `python3 -m pytest tests/ -q`  
**Lint command**: `ruff check kitsune_mcp/ server.py tests/`  
**Install**: `pip install -e ".[dev]" -q`

---

## Why these changes

Live eval of v0.20.0 found three bugs and one documentation gap:

1. **`auth()` footgun** — `auth("notion-hosted", "logout")` silently writes `NOTION_HOSTED=logout` into `~/.kitsune/.env`, corrupting the credential store.
2. **`auto()` bad ranking** — without `server_hint`, picks semantically wrong servers (e.g. `simulate-research-query` for "search the web") because it only ranks by operability, not relevance.
3. **OAuth logout not wired** — `delete_tokens()` exists in `oauth.py` but `auth()` never calls it.
4. **README stuck at v0.18.1** — Gateway, auto(), 6-tool surface all need to be documented.

What works and must NOT change: GATEWAY status section, `auto()` with `server_hint`, `shapeshift`/`call` loop, credential harvest, absorbed registry.

---

## Fix 1 — `auth()` footgun + OAuth logout

**File**: `kitsune_mcp/tools/onboarding.py`

### Current code (lines 979–991)

```python
    name = server_id_or_var

    # Value provided → always store as env var regardless of name format
    if value:
        var = name.upper().replace(" ", "_").replace("-", "_")
        _save_to_env(var, value)
        _state._registry.bust_cache()
        preview = value[:4] + "***" + value[-2:] if len(value) > 6 else "***"
        return f"Saved: {var} = {preview} written to .env (mode 0o600) and active for this session."

    # ALL_CAPS pattern → env var status check
    if re.match(r'^[A-Z][A-Z0-9_]*$', name):
```

### Replace with

```python
    name = server_id_or_var

    # Value provided — guard: names with - / @ are server IDs, not env var names
    if value:
        if re.search(r'[-/@]', name):
            # Looks like a server ID — route to logout or reject
            if value.lower() in ("logout", "signout", "clear", "revoke"):
                srv_logout = await _state._registry.get_server(name)
                if srv_logout and srv_logout.transport == "http" and srv_logout.url:
                    from kitsune_mcp import oauth
                    oauth.delete_tokens(oauth._origin(srv_logout.url))
                    return (
                        f"✓ OAuth tokens cleared for '{name}'.\n"
                        f"  Next: auth('{name}') to re-authenticate."
                    )
                return f"'{name}' is not an OAuth server — no tokens to clear."
            suggested = _to_env_var(name)
            return "\n".join([
                f"✗ '{name}' looks like a server ID, not an env var name.",
                f"  To store a credential:  auth('{suggested}', '{value}')",
                f"  To check server auth:   auth('{name}')",
                f"  To revoke OAuth tokens: auth('{name}', 'logout')",
            ])
        var = name.upper().replace(" ", "_").replace("-", "_")
        _save_to_env(var, value)
        _state._registry.bust_cache()
        preview = value[:4] + "***" + value[-2:] if len(value) > 6 else "***"
        return f"Saved: {var} = {preview} written to .env (mode 0o600) and active for this session."

    # ALL_CAPS pattern → env var status check
    if re.match(r'^[A-Z][A-Z0-9_]*$', name):
```

**Key functions already available**:
- `_to_env_var(name)` — imported at top of `onboarding.py` from `kitsune_mcp.credentials`
- `oauth._origin(base_url)` — `oauth.py:71`, converts URL to filesystem-safe key
- `oauth.delete_tokens(origin)` — `oauth.py:413`, deletes token file for that origin

---

## Fix 2 — `auto()` composite ranking

**File**: `kitsune_mcp/tools/onboarding.py`

### Current import (line 25)

```python
from kitsune_mcp.registry import REGISTRY_BASE, _works_now_score
```

### Change to

```python
from kitsune_mcp.registry import REGISTRY_BASE, _relevance_score, _works_now_score
```

### Current ranking (line 200)

```python
        candidates.sort(key=_works_now_score, reverse=True)
```

### Replace with

```python
        candidates.sort(
            key=lambda s: _relevance_score(s, search_query) * 10.0 + _works_now_score(s),
            reverse=True,
        )
```

**Why**: `_relevance_score` returns 0–100+ (name match = +50, description = +5). `_works_now_score` returns 0.0–1.0. Multiplying relevance ×10 makes it the primary discriminator. Works-now only breaks ties among equally relevant servers. `simulate-research-query` has relevance ≈ 0 for "search the web" → drops to the bottom regardless of its operability.

**`search_query` is already in scope** at line 200 — computed at line 192 (`search_query = _search_query_for(task)`). No restructuring needed.

**`_relevance_score` signature** (in `registry.py:593`):
```python
def _relevance_score(srv: ServerInfo, query: str) -> float:
```

---

## Fix 3 — README update

**File**: `README.md`

### Change A — Version header (line 20)

```markdown
## What's new in v0.18.1
```
→
```markdown
## What's new in v0.20
```

Replace the bullet list body with:
```markdown
- **GATEWAY** — `status()` detects other MCP servers active in your client configs and shows their context cost. `setup()` harvests their API keys and absorbs the servers for `shapeshift()`.
- **6-tool lean profile** — `status`, `search`, `auth`, `shapeshift`, `call`, `auto`. `auto()` is now first-class in the lean surface, not forge-only.
- **`auto()` with `server_hint`** — one-shot task execution: `auto("current time in Tokyo", server_hint="mcp-server-time")` infers args and returns the result directly. Arg extraction infers "Tokyo" → "Asia/Tokyo" automatically.
- **`setup()` wizard** — `setup(action="harvest")` extracts API keys from other servers' configs into `~/.kitsune/.env`. `setup(action="absorb")` registers those servers for `shapeshift()`. `setup(project=True)` writes a lean `.claude/mcp.json` for this project only.

See [CHANGELOG.md](CHANGELOG.md) for the full list.
```

### Change B — Add GATEWAY section

Add a new `## GATEWAY — see what you're paying for` section **after** `## The problem: static tool loading`. Content:

```markdown
## GATEWAY — see what you're paying for

Once Kitsune is running, call `status()` to see what other MCP servers your clients are loading:

```
GATEWAY
  ⚠  2 other server(s) active in claude-desktop (~16 extra tools in context)
     Run setup() to harvest their credentials and reduce bloat
  ⚠  1 other server(s) active in claude-code (~8 extra tools in context)
```

Kitsune can absorb those servers so you get a single lean config with everything still accessible on demand:

```
setup()                    # preview what can be harvested
setup(action="harvest")    # extract API keys → ~/.kitsune/.env  (non-destructive)
setup(action="absorb")     # register servers for shapeshift()   (non-destructive)
setup(project=True)        # write .claude/mcp.json with only Kitsune (this project only)
```
```

### Change C — auto() quickstart pattern

In `## Quick Start`, add alongside the shapeshift+call pattern:

```markdown
```
# One-shot: describe task + pin the server
auto("current time in Tokyo", server_hint="mcp-server-time")
auto("search: anthropic news May 2026", server_hint="exa")

# Multi-step: inspect / lean-mount / hold mount for several calls
shapeshift("mcp-server-time")
call("get_current_time", {"timezone": "Asia/Tokyo"})
shapeshift()
```

Use `auto()` with `server_hint` for single-call flows. Use `shapeshift + call` when you want to inspect first, mount specific tools, or run multiple calls on the same server.
```

---

## Fix 4 — Version bump

**`pyproject.toml`**: `version = "0.20.0"` → `version = "0.20.1"`  
**`package.json`**: `"version": "0.20.0"` → `"version": "0.20.1"`

---

## New tests

**File**: `tests/test_v0201_fixes.py`

```python
"""Tests for v0.20.1 — auth() server-ID guard and auto() composite ranking."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestAuthServerIdGuard:
    """auth() must not write server IDs as env var names."""

    async def _call(self, name, value=""):
        from kitsune_mcp.tools.onboarding import auth
        return await auth(name, value)

    async def test_server_id_with_value_returns_error(self):
        result = await self._call("notion-hosted", "sk-abc")
        assert "looks like a server ID" in result
        assert "NOTION_HOSTED" not in result or "Saved" not in result

    async def test_server_id_with_value_does_not_write_env(self):
        original = os.environ.get("NOTION_HOSTED")
        await self._call("notion-hosted", "some-garbage")
        assert os.environ.get("NOTION_HOSTED") == original

    async def test_server_id_logout_does_not_write_env(self):
        original = os.environ.get("NOTION_HOSTED")
        result = await self._call("notion-hosted", "logout")
        assert os.environ.get("NOTION_HOSTED") == original
        # Response should NOT say "Saved"
        assert "Saved" not in result

    async def test_plain_env_var_all_caps_still_saves(self, tmp_path, monkeypatch):
        from unittest.mock import patch
        with patch("kitsune_mcp.credentials._KITSUNE_HOME", tmp_path):
            (tmp_path / ".env").touch()
            result = await self._call("MY_API_KEY", "test-value")
        assert "Saved" in result or "MY_API_KEY" in result

    def test_env_var_no_hyphen_passes_guard(self):
        import re
        # The guard fires on re.search(r'[-/@]', name)
        assert not re.search(r'[-/@]', "BRAVE_API_KEY")
        assert not re.search(r'[-/@]', "MY_TOKEN")
        assert re.search(r'[-/@]', "notion-hosted")
        assert re.search(r'[-/@]', "@scope/server")


class TestAutoCompositeRank:
    """Composite rank = _relevance_score × 10 + _works_now_score."""

    def _score(self, srv, query):
        from kitsune_mcp.registry import _relevance_score, _works_now_score
        return _relevance_score(srv, query) * 10.0 + _works_now_score(srv)

    def _srv(self, **kwargs):
        from kitsune_mcp.registry import ServerInfo
        defaults = dict(
            id="test", name="Test", description="",
            source="official", transport="stdio",
            credentials={}, tools=[], token_cost=0, url="", install_cmd=[],
        )
        defaults.update(kwargs)
        return ServerInfo(**defaults)

    def test_relevant_beats_merely_operable(self):
        # High-relevance server with creds needed
        relevant = self._srv(
            id="brave-search", name="Brave Web Search",
            description="search the web",
            source="smithery", credentials={"BRAVE_API_KEY": "required"},
        )
        # High-operability server with unrelated purpose
        operable = self._srv(
            id="simulate-research", name="Simulate Research Query",
            description="simulation tasks",
            source="official", credentials={},
        )
        assert self._score(relevant, "search the web") > self._score(operable, "search the web")

    def test_works_now_breaks_ties_among_equally_relevant(self):
        # Same name/description, different operability
        no_creds = self._srv(name="Time Server", description="time queries", credentials={})
        with_creds = self._srv(
            name="Time Server", description="time queries",
            credentials={"TIME_KEY": "required"},
        )
        assert self._score(no_creds, "time") > self._score(with_creds, "time")

    def test_exact_name_match_dominates(self):
        exact = self._srv(id="exa", name="exa", description="web search")
        partial = self._srv(id="exa-2", name="exa web search extended", description="searches")
        # Both relevant to "exa" but exact match should win
        assert self._score(exact, "exa") > self._score(partial, "exa")
```

---

## Execution order

1. Edit `kitsune_mcp/tools/onboarding.py` — Fix 1 (auth guard, lines ~979–991) and Fix 2 (import line 25, sort line ~200)
2. Edit `README.md` — Fix 3 (version header, GATEWAY section, quickstart)
3. Edit `pyproject.toml` and `package.json` — Fix 4 (version bump)
4. Create `tests/test_v0201_fixes.py` — new test file
5. Run `python3 -m pytest tests/ -q` — all tests must pass
6. Run `ruff check kitsune_mcp/tools/onboarding.py tests/test_v0201_fixes.py`
7. Commit and push

## Verification

```bash
# Smoke test Fix 1 — server ID must NOT be written as env var
python3 -c "
import asyncio, os
os.environ.pop('NOTION_HOSTED', None)
from kitsune_mcp.tools.onboarding import auth
result = asyncio.run(auth('notion-hosted', 'some-garbage'))
print(result)
assert os.getenv('NOTION_HOSTED') is None, 'FOOTGUN still present'
print('PASS: server ID not saved as env var')
"

# Run new tests
python3 -m pytest tests/test_v0201_fixes.py -v

# Full suite
python3 -m pytest tests/ -q
ruff check kitsune_mcp/ server.py tests/
```
