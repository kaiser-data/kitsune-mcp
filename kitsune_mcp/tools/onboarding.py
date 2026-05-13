"""Onboarding tools: skill, key, auth, auto, setup."""

import asyncio
import contextlib
import json
import os
import re
from datetime import UTC, datetime

import httpx

from kitsune_mcp.app import mcp
from kitsune_mcp.constants import (
    TIMEOUT_FETCH_URL,
    TIMEOUT_STDIO_INIT,
)
from kitsune_mcp.credentials import (
    _registry_headers,
    _save_to_env,
    _smithery_available,
    _to_env_var,
)
from kitsune_mcp.probe import _format_setup_guide
from kitsune_mcp.registry import REGISTRY_BASE
from kitsune_mcp.session import _save_skills, session
from kitsune_mcp.tools import _state
from kitsune_mcp.transport import BaseTransport
from kitsune_mcp.utils import _get_http_client, _is_safe_url


@mcp.tool()
async def skill(qualified_name: str, forget: bool = False) -> str:
    """Load a Smithery skill into context. forget=True removes it."""
    # --- forget / uninstall ---
    if forget:
        if qualified_name in session["skills"]:
            name = session["skills"][qualified_name].get("name", qualified_name)
            del session["skills"][qualified_name]
            _save_skills()
            return f"Skill removed: {name} ({qualified_name})"
        return f"Skill '{qualified_name}' is not installed."

    # --- serve from cache if already loaded ---
    cached = session["skills"].get(qualified_name)
    if cached and cached.get("content"):
        content = cached["content"]
        skill_name = cached.get("name", qualified_name)
        token_estimate = cached.get("tokens", len(content) // 4)
        lines = [
            f"Skill injected (cached): {skill_name} ({qualified_name})",
            f"Context cost: ~{token_estimate:,} tokens",
            "", "--- SKILL CONTENT ---", "", content,
        ]
        return "\n".join(lines)

    # --- fetch from Smithery API ---
    if not _state._smithery_available():
        return "No SMITHERY_API_KEY set. Run: auth('SMITHERY_API_KEY', 'your-key')"

    try:
        r = await _get_http_client().get(
            f"{REGISTRY_BASE}/skills/{qualified_name}",
            headers=_registry_headers(),
            timeout=TIMEOUT_FETCH_URL,
        )
        r.raise_for_status()
        skill_meta = r.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return f"Skill '{qualified_name}' not found."
        return f"Registry error: {e.response.status_code}"
    except Exception as e:
        return f"Failed to fetch skill: {e}"

    skill_name = skill_meta.get("name") or skill_meta.get("displayName") or qualified_name
    skill_desc = (skill_meta.get("description") or "").strip()

    content = None
    content_url = (skill_meta.get("contentUrl") or skill_meta.get("url")
                   or skill_meta.get("content_url"))
    if content_url and _is_safe_url(content_url):
        try:
            rc = await _get_http_client().get(content_url, timeout=TIMEOUT_FETCH_URL)
            rc.raise_for_status()
            content = rc.text
        except Exception:
            content = None

    if not content:
        content = (skill_meta.get("content") or skill_meta.get("markdown")
                   or skill_meta.get("text"))

    if not content:
        return "\n".join([
            f"Skill: {skill_name} ({qualified_name})",
            f"Description: {skill_desc}" if skill_desc else "",
            "Warning: could not fetch skill content.",
            json.dumps(skill_meta, indent=2),
        ])

    token_estimate = len(content) // 4
    session["skills"][qualified_name] = {
        "name": skill_name,
        "content": content,
        "tokens": token_estimate,
        "installed_at": datetime.now(UTC).isoformat(),
    }
    _save_skills()

    lines = [
        f"Skill injected: {skill_name} ({qualified_name})",
        f"Context cost: ~{token_estimate:,} tokens",
    ]
    if skill_desc:
        lines.append(f"Description: {skill_desc}")
    lines += ["", "--- SKILL CONTENT ---", "", content]
    return "\n".join(lines)


@mcp.tool()
async def key(env_var: str, value: str) -> str:
    """Save an API key to .env for persistent use. e.g. key('EXA_API_KEY', 'sk-...')"""
    var = env_var.upper().replace(" ", "_")
    _save_to_env(var, value)
    _state._registry.bust_cache()  # credentials changed — invalidate cached server records
    preview = value[:4] + "***" + value[-2:] if len(value) > 6 else "***"
    return f"Saved: {var} = {preview} written to .env (mode 0o600) and active for this session."


@mcp.tool()
async def auto(
    task: str,
    tool_name: str = "",
    arguments: dict | None = None,
    server_hint: str = "",
    keys: dict | None = None,
) -> str:
    """Search → pick best server → call tool in one step."""
    if arguments is None:
        arguments = {}
    if keys is None:
        keys = {}
    for env_var, value in keys.items():
        _save_to_env(env_var.upper(), str(value))

    # Guard: built-in Kitsune tool names must be called directly, not routed
    # to an external MCP server. auto("onboard") would otherwise search the
    # registry for a server named "onboard" and fail confusingly.
    # Core lean-profile tools always available; forge extras only with KITSUNE_TOOLS=all
    _KITSUNE_LEAN: frozenset[str] = frozenset({
        "auth", "call", "search", "shapeshift", "status",
    })
    _KITSUNE_FORGE: frozenset[str] = frozenset({
        "auto", "bench", "compare", "connect", "craft", "fetch",
        "inspect", "key", "login", "onboard", "release", "run",
        "setup", "shiftback", "skill", "test",
    })
    _KITSUNE_BUILTINS = _KITSUNE_LEAN | _KITSUNE_FORGE
    task_stripped = task.strip().lower()
    if task_stripped in _KITSUNE_BUILTINS:
        note = "" if task_stripped in _KITSUNE_LEAN else " (forge profile — set KITSUNE_TOOLS=all)"
        return (
            f"'{task}' is a built-in Kitsune tool — call it directly{note}.\n"
            f"Example: {task_stripped}()"
        )

    # When the caller pins a server, single-shot. Otherwise search and try
    # candidates in order, skipping ones that are unreachable due to missing
    # creds we can't fill. The user asked for "web search" — they don't care
    # which provider answers, only that one of them does.
    candidates: list = []  # list[ServerInfo] from registry, or [] if server_hint path
    if server_hint:
        srv = await _state._registry.get_server(server_hint)
        if srv:
            server_id, server_name, credentials = srv.id, srv.name, srv.credentials
        else:
            server_id, server_name, credentials = server_hint, server_hint, {}
    else:
        # Extract registry-friendly keywords from a NL task. Raw NL queries like
        # "what time is it in Tokyo" only match Smithery (server-side full-text
        # search), leaving official/McpRegistry servers out. Keyword extraction
        # gives every registry the right signal to find free official servers first.
        search_query = _search_query_for(task)
        candidates = list(await _state._registry.search(search_query, limit=5))
        if not candidates and search_query != task:
            # Keyword extraction may have over-stripped — fall back to raw task
            candidates = list(await _state._registry.search(task, limit=5))
        if not candidates:
            return f"No servers found for '{task}'. Use search() or provide server_hint."
        # Rank candidates: prefer local (stdio + no missing creds) over Smithery HTTP.
        # This avoids routing to a Smithery server when a free local alternative exists.
        def _candidate_rank(s) -> tuple:
            _, missing = _state._resolve_config(s.credentials, {})
            has_missing = bool(missing)
            is_smithery_http = s.source == "smithery" and s.transport == "http"
            is_official = s.source in ("official", "mcpregistry")
            # Lower tuple = higher priority
            return (has_missing, is_smithery_http, not is_official, s.transport != "stdio")
        candidates.sort(key=_candidate_rank)
        chosen = candidates[0]
        server_id, server_name, credentials = chosen.id, chosen.name, chosen.credentials
        # Remove the chosen one from the fallback queue
        candidates = [s for s in candidates if s.id != chosen.id]
        session["explored"][server_id] = {
            "name": server_name, "desc": chosen.description, "status": "harvested"
        }

    resolved_config, missing = _state._resolve_config(credentials, {})
    if missing:
        missing_vars = {_to_env_var(k): v for k, v in missing.items()}
        lines = [f"Server '{server_id}' needs keys:", ""]
        for ev, desc in missing_vars.items():
            lines.append(f"  {ev}" + (f": {desc[:60]}" if desc else ""))
        args_repr = json.dumps(arguments) if arguments else "{}"
        lines += [
            "",
            "Retry:",
            f'  auto("{task}", "{tool_name}", {args_repr},',
            f'    server_hint="{server_id}",',
            '    keys={' + ", ".join(f'"{k}": "val"' for k in missing_vars) + '})',
        ]
        return "\n".join(lines)

    selected_tool_schema: dict | None = None
    if not tool_name:
        srv = await _state._registry.get_server(server_id)
        tools = (srv.tools if srv else []) or []

        # For stdio servers with no registry tools, fetch live schemas
        if not tools and srv and srv.transport == "stdio":
            cmd = srv.install_cmd or ["npx", "-y", server_id]
            with contextlib.suppress(Exception):
                tools = await asyncio.wait_for(
                    _state.PersistentStdioTransport(cmd).list_tools(), timeout=TIMEOUT_STDIO_INIT
                )

        if not tools:
            reg_errors = getattr(_state._registry, "last_registry_errors", {})
            lines = [f"{server_id} — could not fetch tool schema."]
            if reg_errors:
                err_summary = ", ".join(f"{n} {e}" for n, e in reg_errors.items())
                lines.append(f"Registry fetch failures: {err_summary}.")
            from kitsune_mcp.credentials import _smithery_available
            if srv and getattr(srv, "source", None) == "smithery" and not _smithery_available():
                lines += [
                    "This server is Smithery-hosted and requires SMITHERY_API_KEY.",
                    "→ auth('SMITHERY_API_KEY', 'sm-...') then retry,"
                    " or search() for a free alternative.",
                ]
            else:
                lines.append("Use call() to invoke tools directly if the server is running.")
            return "\n".join(lines)

        # Auto-select: only one tool → use it; multiple → pick best match for task
        if len(tools) == 1:
            tool_name = tools[0]["name"]
            selected_tool_schema = tools[0]
        else:
            task_lc = task.lower()
            task_words = set(re.split(r'\W+', task_lc))

            def _tool_score(t: dict) -> float:
                n = (t.get("name") or "").lower()
                d = (t.get("description") or "").lower()
                score = 0.0
                if task_lc in n:
                    score += 10.0
                score += sum(2.0 for w in task_words if w and w in n)
                score += sum(1.0 for w in task_words if w and w in d)
                return score

            scored = sorted(tools, key=_tool_score, reverse=True)
            best_score = _tool_score(scored[0])
            if best_score > 0:
                tool_name = scored[0]["name"]
                selected_tool_schema = scored[0]
            else:
                # No match — list tools and ask user to pick
                tool_lines = [f"  {t['name']} — {(t.get('description') or '')[:80]}" for t in tools]
                return "\n".join([
                    f"{server_name} ({server_id}) ready. Available tools:",
                    "",
                    *tool_lines,
                    "",
                    f'Call: auto("{task}", "<tool>", args, server_hint="{server_id}")',
                ])

    # If caller picked a tool implicitly and supplied no arguments, fill the
    # primary required string param from `task`. Common case: auto("web search")
    # with auto-selected `search(query: string)` — without this, every search
    # tool fails with "query: undefined". Only triggers when arguments is empty
    # AND we have a schema to inspect AND there's exactly one obvious string
    # field to fill.
    if not arguments and selected_tool_schema:
        arguments = _infer_args_from_task(selected_tool_schema, task)
        # When inference correctly returns {} (structured/path param with NL task),
        # surface a helpful retry message before the inner server emits an opaque
        # "'timezone' is a required property" validation error.
        if not arguments:
            hint = _build_inference_hint(selected_tool_schema, task, server_id, tool_name)
            if hint:
                return hint

    # Execute with fallback: if the chosen server returns an auth-failure
    # response and the caller didn't pin via server_hint, try the next candidate.
    # Wall-clock cap of 5s per provider is enforced by transport timeouts already.
    attempted: list[tuple[str, str]] = []
    last_result: str = ""
    while True:
        srv = await _state._registry.get_server(server_id)
        transport: BaseTransport = _state._get_transport(server_id, srv)
        last_result = await transport.execute(tool_name, arguments, resolved_config)
        _state._track_call(server_id, tool_name)
        attempted.append((server_id, tool_name))

        # Auth-failure detection — surfaces from the inner server's text response
        # (which arrives via Kitsune's transport.execute as a string body).
        # We only fall back when the caller didn't pin a server AND there are
        # candidates left.
        is_auth_fail = any(
            kw in last_result.lower()
            for kw in ("auth failed", "unauthorized", "401", "403", "invalid token", "smithery_api_key")
        )
        if not is_auth_fail or not candidates:
            break

        # Try the next candidate
        nxt = candidates.pop(0)
        # Skip candidates whose creds we still can't satisfy
        cfg2, missing2 = _state._resolve_config(nxt.credentials, {})
        if missing2:
            continue
        server_id, server_name, credentials = nxt.id, nxt.name, nxt.credentials
        resolved_config = cfg2
        # If a different server is chosen, the previously picked tool_name may
        # not exist there. Reset selection so the loop's tool-pick logic runs
        # again — but that logic is in the section above the loop. Simpler:
        # retry only when the new server has a same-named tool. Otherwise stop
        # and report what we tried.
        new_srv = await _state._registry.get_server(server_id)
        new_tools = (new_srv.tools if new_srv else []) or []
        if not any(t.get("name") == tool_name for t in new_tools):
            # Different schema — append a hint to the failure response
            attempted_str = ", ".join(f"{sid}/{t}" for sid, t in attempted)
            return (
                f"{last_result}\n\n"
                f"⚠️  auto() tried {attempted_str}; remaining candidates have different tool names. "
                f'Retry with: auto("{task}", server_hint="<id>")'
            )

    return last_result


# Param names that semantically take a free-text query — always safe to fill
# from the raw task string regardless of how the task is phrased.
_SEARCH_PARAM_NAMES: frozenset[str] = frozenset({
    "query", "q", "text", "prompt", "input", "search", "term",
    "message", "content", "question", "request", "task",
    "description", "user_question", "user_input", "user_prompt",
})

# Structured params whose value is a code/identifier (timezone name, currency
# code, language tag, etc.) — must NOT receive a full NL sentence verbatim.
# Used by Rule 2 in _infer_args_from_task when the task starts with a
# NL question/context word.
_STRUCTURED_PARAM_NAMES: frozenset[str] = frozenset({
    "timezone", "time_zone", "source_timezone", "target_timezone",
    "from_timezone", "to_timezone",
    "language", "lang", "locale", "source_language", "target_language",
    "currency", "symbol", "ticker", "from_currency", "to_currency",
    "base_currency", "target_currency",
    "city", "country", "region", "location", "address",
    "path", "file", "directory", "filename", "url", "uri",
    "format", "mode", "type", "encoding",
})

# Path-like params that must receive a filesystem path value. If the task
# doesn't look like a path, these params are never filled — a bare task like
# "web search for X" must not become path="/Users/.../web search for X".
_PATH_PARAM_NAMES: frozenset[str] = frozenset({
    "path", "file", "directory", "dir", "filename", "filepath",
    "folder", "root", "base_path", "target_path", "source_path",
})

# Words that signal the task is a natural-language phrase rather than a bare
# value. Used only when the matched param is in _STRUCTURED_PARAM_NAMES.
_NL_STARTERS: frozenset[str] = frozenset({
    "what", "whats", "when", "where", "who", "how", "why",
    "tell", "show", "find", "is", "are", "does", "can", "could",
    "give", "get", "list", "fetch", "check",
    # Context/state queries — "current time", "current weather", "latest price"
    "current", "latest", "today", "now", "todays",
})

# Timezone abbreviations → IANA identifiers, for auto() NL extraction.
_TZ_ABBREVS: dict[str, str] = {
    "UTC": "UTC", "GMT": "GMT",
    "EST": "America/New_York", "EDT": "America/New_York",
    "CST": "America/Chicago", "CDT": "America/Chicago",
    "MST": "America/Denver", "MDT": "America/Denver",
    "PST": "America/Los_Angeles", "PDT": "America/Los_Angeles",
    "CET": "Europe/Berlin", "CEST": "Europe/Berlin",
    "BST": "Europe/London", "WET": "Europe/Lisbon",
    "IST": "Asia/Kolkata", "JST": "Asia/Tokyo",
    "CST_CN": "Asia/Shanghai", "KST": "Asia/Seoul",
    "AEST": "Australia/Sydney", "AEDT": "Australia/Sydney",
    "NZST": "Pacific/Auckland",
}

# Common city/location names → IANA timezone identifiers.
_CITY_TO_TZ: dict[str, str] = {
    "new york": "America/New_York", "new york city": "America/New_York", "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "seattle": "America/Los_Angeles",
    "chicago": "America/Chicago", "houston": "America/Chicago", "dallas": "America/Chicago",
    "denver": "America/Denver", "phoenix": "America/Phoenix",
    "toronto": "America/Toronto", "montreal": "America/Toronto",
    "vancouver": "America/Vancouver",
    "mexico city": "America/Mexico_City",
    "sao paulo": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "london": "Europe/London", "uk": "Europe/London",
    "paris": "Europe/Paris", "france": "Europe/Paris",
    "berlin": "Europe/Berlin", "germany": "Europe/Berlin",
    "madrid": "Europe/Madrid", "spain": "Europe/Madrid",
    "rome": "Europe/Rome", "italy": "Europe/Rome",
    "amsterdam": "Europe/Amsterdam",
    "zurich": "Europe/Zurich", "switzerland": "Europe/Zurich",
    "stockholm": "Europe/Stockholm", "oslo": "Europe/Oslo", "helsinki": "Europe/Helsinki",
    "moscow": "Europe/Moscow", "russia": "Europe/Moscow",
    "istanbul": "Europe/Istanbul", "turkey": "Europe/Istanbul",
    "dubai": "Asia/Dubai", "uae": "Asia/Dubai",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "india": "Asia/Kolkata",
    "singapore": "Asia/Singapore",
    "tokyo": "Asia/Tokyo", "japan": "Asia/Tokyo",
    "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai", "china": "Asia/Shanghai",
    "hong kong": "Asia/Hong_Kong",
    "seoul": "Asia/Seoul", "korea": "Asia/Seoul",
    "bangkok": "Asia/Bangkok", "thailand": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta", "indonesia": "Asia/Jakarta",
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "australia": "Australia/Sydney",
    "auckland": "Pacific/Auckland", "new zealand": "Pacific/Auckland",
    "cairo": "Africa/Cairo", "egypt": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg", "south africa": "Africa/Johannesburg",
    "nairobi": "Africa/Nairobi", "kenya": "Africa/Nairobi",
    "lagos": "Africa/Lagos", "nigeria": "Africa/Lagos",
}


def _extract_timezone_from_nl(task: str) -> str | None:
    """Try to pull a timezone identifier from a natural-language task string.

    "what time is it in UTC"      → "UTC"
    "current time in New York"    → "America/New_York"
    "what time is it in Berlin"   → "Europe/Berlin"
    Returns None when no recognizable timezone is found.
    """
    # Check for uppercase abbreviations (UTC, GMT, PST, …)
    for word in re.findall(r'\b[A-Z]{2,5}\b', task):
        if word in _TZ_ABBREVS:
            return _TZ_ABBREVS[word]

    # Check for an IANA-style literal already in the task (e.g. "America/New_York")
    m = re.search(r'\b[A-Z][a-z]+/[A-Z][a-zA-Z_]+\b', task)
    if m:
        return m.group(0)

    # City/country map — longest match first to prefer "New York City" over "New York"
    task_lc = task.lower()
    for city, tz in sorted(_CITY_TO_TZ.items(), key=lambda x: -len(x[0])):
        if re.search(r'\b' + re.escape(city) + r'\b', task_lc):
            return tz

    return None


# Stop-words stripped from NL tasks before they're passed to registry search.
# Keeping content words (nouns, verbs, place names) while dropping filler gives
# keyword-quality queries to registries that do substring matching.
_SEARCH_STOP_WORDS: frozenset[str] = frozenset({
    "what", "whats", "when", "where", "who", "how", "why",
    "the", "a", "an", "and", "or", "for", "of", "to", "in",
    "is", "it", "me", "my", "i", "do", "does", "did",
    "can", "could", "please", "now", "current", "currently",
    "latest", "today", "tell", "show", "give", "find", "get",
    "make", "want", "need", "help", "some", "any",
})


def _search_query_for(task: str) -> str:
    """Extract registry-friendly keywords from a natural-language task.

    "what time is it in Tokyo" → "time Tokyo"
    "search for latest AI news" → "news"
    "get weather Berlin"        → "weather Berlin"

    Words under 3 chars are always dropped (too generic). If no content words
    remain, fall back to the raw task so search still has something to work with.
    """
    words = [
        w for w in re.split(r'\W+', task)
        if len(w) >= 3 and w.lower() not in _SEARCH_STOP_WORDS
    ]
    return " ".join(words) if words else task


def _infer_args_from_task(tool_schema: dict, task: str) -> dict:
    """When auto() implicit-selects a tool but caller passed no arguments,
    infer the primary required string param from `task`. Returns {} when no
    safe inference is possible — the LLM then retries with explicit args.

    Rules (in order):
    0. Multiple required string params → ambiguous, return {} (can't know
       which ones to fill; e.g. translate(text, target_language)).
    1. Single required param with search-like name (query, q, text, prompt,
       user_question …) → always fill; this IS the payload the tool expects.
    2. Single required param in _STRUCTURED_PARAM_NAMES (timezone, currency,
       lang …) AND the task starts with a NL question word → return {};
       forwarding "what time is it in Tokyo" as a timezone name always fails.
    3. Single required param not covered above → fill it (e.g. bare values,
       QA-style tools with unique param names).
    """
    schema = (tool_schema.get("inputSchema") or {})
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    string_required = [p for p in required if props.get(p, {}).get("type") == "string"]

    # Rule 0a — ambiguous multi-string schema: can't know which to fill
    if len(string_required) > 1:
        return {}

    # Rule 0b — no required string params: check for optional search-like params.
    # Many Smithery servers declare all params as optional (required=[]) but
    # still reject calls without the primary query param. Fill the first
    # SEARCH_PARAM_NAMES match found in the properties.
    if len(string_required) == 0:
        optional_search = [
            p for p in props
            if p in _SEARCH_PARAM_NAMES and props[p].get("type") == "string"
        ]
        if optional_search:
            return {optional_search[0]: task}
        return {}

    pname = string_required[0]

    # Rule 1 — search-like param: always safe to fill
    if pname in _SEARCH_PARAM_NAMES:
        return {pname: task}

    # Rule 2a — path param: only fill if task looks like an actual filesystem path
    if pname in _PATH_PARAM_NAMES:
        stripped = task.strip()
        if stripped.startswith(("/", "~", "./", "../")) or (len(stripped) > 1 and stripped[1] == ":"):
            return {pname: stripped}
        return {}

    # Rule 2b — structured param + NL context phrase: refuse to forward verbatim,
    # but first try to extract the value from the text (timezone, city, etc.)
    first_word = task.split()[0].lower() if task.split() else ""
    if pname in _STRUCTURED_PARAM_NAMES and first_word in _NL_STARTERS:
        if pname in {"timezone", "time_zone", "source_timezone", "target_timezone",
                     "from_timezone", "to_timezone"}:
            tz = _extract_timezone_from_nl(task)
            if tz:
                return {pname: tz}
        return {}

    # Rule 3 — single param, task looks like a direct value
    return {pname: task}


# Canonical example values for structured param names — shown in retry hints
# so the caller sees the expected format at a glance (not just a placeholder).
_PARAM_EXAMPLES: dict[str, str] = {
    "timezone": "America/New_York", "time_zone": "America/New_York",
    "source_timezone": "UTC", "target_timezone": "America/New_York",
    "from_timezone": "UTC", "to_timezone": "America/New_York",
    "language": "en", "lang": "en", "locale": "en-US",
    "source_language": "en", "target_language": "es",
    "currency": "USD", "from_currency": "USD", "to_currency": "EUR",
    "base_currency": "USD", "target_currency": "EUR",
    "symbol": "AAPL", "ticker": "AAPL",
    "city": "London", "country": "US", "region": "Europe",
    "location": "London", "address": "123 Main St",
    "format": "json", "mode": "text", "type": "file", "encoding": "utf-8",
    "path": "/path/to/target", "file": "/path/to/file",
    "directory": "/path/to/dir", "dir": "/path/to/dir",
    "filename": "output.txt", "filepath": "/path/to/file",
    "folder": "/path/to/folder", "url": "https://example.com",
    "uri": "file:///path/to/resource",
}


def _build_inference_hint(
    tool_schema: dict, task: str, server_id: str, tool_name: str
) -> str | None:
    """Return a helpful retry message when _infer_args_from_task returns {}.

    Returns None when the tool has no required string params (empty args may be
    valid, or the server will produce its own informative error). Returns a
    formatted string when at least one required string param exists but couldn't
    be safely inferred from the task.
    """
    schema = tool_schema.get("inputSchema") or {}
    props = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    string_required = [p for p in required if props.get(p, {}).get("type") == "string"]

    if not string_required:
        return None  # no required string params — tool may work without args

    # Build example argument dict using known-good format placeholders
    example_args: dict[str, str] = {}
    param_notes: list[str] = []
    for pname in string_required:
        ex = _PARAM_EXAMPLES.get(pname, f"<{pname}>")
        example_args[pname] = ex
        if pname in _PATH_PARAM_NAMES:
            param_notes.append(f"'{pname}' needs a filesystem path (e.g. \"{ex}\")")
        elif pname in _STRUCTURED_PARAM_NAMES:
            param_notes.append(f"'{pname}' needs a code/identifier (e.g. \"{ex}\")")
        else:
            param_notes.append(f"'{pname}'")

    if len(string_required) > 1:
        reason = f"tool has multiple required params: {', '.join(string_required)}"
    else:
        reason = param_notes[0]

    args_repr = json.dumps(example_args)
    return "\n".join([
        f"auto() couldn't infer args from \"{task}\" — {reason}.",
        "Retry with explicit args:",
        f'  auto("{task}", server_hint="{server_id}", arguments={args_repr})',
    ])


@mcp.tool()
async def setup(name: str) -> str:
    """Setup wizard for a connected server. Call repeatedly until all requirements are met."""
    conn = next((c for c in session["connections"].values() if c.get("name") == name), None)
    if conn is None:
        connected = [c.get("name", "?") for c in session["connections"].values()]
        if connected:
            return f"No connection named '{name}'. Connected: {', '.join(connected)}"
        return f"No connection named '{name}'. Use connect() first."

    install_cmd = conn["command"].split()
    transport = _state.PersistentStdioTransport(install_cmd)
    tools = await transport.list_tools()

    resource_text = await _state._fetch_resource_docs(transport)
    reqs = _state._probe_requirements(tools, resource_text)
    guide = _format_setup_guide(reqs, name, tools=tools)

    lines = [f"Setup: {name}"]

    if reqs["needs_oauth"]:
        lines.append("⚠️  OAuth flow detected — browser authentication may be required.")

    if reqs["schema_creds"]:
        schema_missing = [c for c in reqs["schema_creds"] if c not in reqs["set_env"]]
        if schema_missing:
            lines.append(f"Required credentials (from schema): {', '.join(schema_missing)}")

    if not guide:
        lines.append("✅ All requirements satisfied — ready to call tools.")
        if tools:
            lines.append(f"\nAvailable tools ({len(tools)}): {', '.join(t.get('name', '?') for t in tools)}")
        return "\n".join(lines)

    lines.append(guide)

    if not reqs["resource_scan"]:
        lines.append("\n(No resource docs found — probe based on tool schemas only.)")

    return "\n".join(lines)


@mcp.tool()
async def auth(server_id_or_var: str, value: str = "") -> str:
    """Check or set credentials for a server or environment variable.

    auth("EXA_API_KEY", "sk-...")  → save env var (persists to .env)
    auth("EXA_API_KEY")            → check if set; show how to set if not
    auth("mcp-server-time")        → check server's auth requirements
    auth("my-oauth-server")        → run OAuth browser flow (http transport)
    """
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
        val = os.getenv(name)
        if val:
            preview = val[:4] + "***" + val[-2:] if len(val) > 6 else "***"
            return f"✓ {name} = {preview} (set)\nTo update: auth(\"{name}\", \"new-value\")"
        return f"✗ {name} not set.\nTo set: auth(\"{name}\", \"your-value\")"

    # Server ID → look up in registry
    srv = await _state._registry.get_server(name)
    if srv is None:
        return f"Server '{name}' not found. Try: search(\"{name}\")"

    if srv.transport == "http":
        if not srv.url:
            return "\n".join([
                f"Server '{name}' has no OAuth URL configured.",
                f'Try: search("{name}") to find the right server ID, then:',
                '  auth("<full-server-id>")',
            ])
        from kitsune_mcp import oauth
        base_url = srv.url
        try:
            token = await oauth.ensure_token(base_url)
        except Exception as e:
            return "\n".join([
                f"OAuth failed for '{name}': {e}",
                f'Retry: auth("{name}")',
            ])
        preview = token[:8] + "..." if len(token) > 8 else token
        return "\n".join([
            f"Authenticated '{name}'.",
            f"Token: {preview}",
            f'Next: shapeshift("{name}")',
        ])

    # stdio transport
    resolved, missing = _state._resolve_config(srv.credentials, {})
    if not srv.credentials:
        return f"✓ '{name}' — no auth needed.\nNext: shapeshift(\"{name}\")"
    if missing:
        missing_vars = {_to_env_var(k): v for k, v in missing.items()}
        lines = [f"'{name}' needs credentials:"]
        for ev, desc in missing_vars.items():
            lines.append(f"  ✗ {ev}" + (f" — {desc[:60]}" if desc else ""))
        lines.append("")
        lines.append("Set them:")
        for ev in missing_vars:
            lines.append(f'  auth("{ev}", "your-value")')
        return "\n".join(lines)
    return f"✓ '{name}' — credentials set.\nNext: shapeshift(\"{name}\")"


# Free-tier servers verified to work without any API key. Curated list — these
# are zero-config wins for new users. Updated when new free servers ship.
_FREE_TIER_SERVERS = [
    ("mcp-server-time", "Time queries + timezone conversions (419 timezones)"),
    ("@modelcontextprotocol/server-memory", "Persistent KG memory across calls"),
    ("mcp-server-fetch", "Fetch web pages, get clean markdown"),
    ("@modelcontextprotocol/server-filesystem", "Read/write local files"),
    ("@upstash/context7-mcp", "Up-to-date library docs (no key needed)"),
]


@mcp.tool()
async def onboard() -> str:
    """First-run wizard — show provider auth state + the fastest path to a working tool call.

    Run once at the start of a new session if `kitsune:status` shows you're
    in base form with nothing explored. Returns provider health + a curated
    list of zero-config servers you can shapeshift into immediately.
    """
    import os
    lines = [
        "🦊  Welcome to Kitsune.",
        "",
        "PROVIDERS",
    ]

    # Active providers — check auth state explicitly
    smithery_ok = _smithery_available()
    lines.append(f"  {'✓' if smithery_ok else '🔑'}  Smithery"
                 f"  {'(SMITHERY_API_KEY set — 3000+ verified servers)' if smithery_ok else '(unconfigured — get a key at smithery.ai/account/api-keys to unlock 3000+ servers)'}")
    lines.append("  ✓  Official MCP Registry  (modelcontextprotocol.io — no key needed)")
    lines.append("  ✓  npm + PyPI  (community servers, no key needed)")
    lines.append("  ✓  Glama  (community directory, no key needed)")
    if os.getenv("KITSUNE_TRUST", "").lower() in ("community", "all", "low"):
        lines.append("  ⚠️  KITSUNE_TRUST=community  (community-source confirmation gate is OFF)")
    lines.append("")

    # Recommended starting point — the free tier
    lines.append("FASTEST PATH TO A WORKING TOOL CALL (no API keys required)")
    for sid, desc in _FREE_TIER_SERVERS:
        lines.append(f"  shapeshift(\"{sid}\")")
        lines.append(f"    → {desc}")
    lines.append("")

    # The "3 step" promise
    lines.append("3-STEP CHECK")
    lines.append("  1. shapeshift(\"mcp-server-time\")")
    lines.append("  2. call(\"get_current_time\", arguments={\"timezone\": \"UTC\"})")
    lines.append("  3. shiftback()")
    lines.append("  → If step 2 returns a timestamp, your install works end-to-end.")
    lines.append("")

    # Optional upgrade
    if not smithery_ok:
        lines.append("UPGRADE PATH")
        lines.append("  Get more servers (incl. GitHub, Notion, Linear, Slack, …):")
        lines.append("    1. Sign up at https://smithery.ai/account/api-keys")
        lines.append("    2. key(\"SMITHERY_API_KEY\", \"sm-...\")")
        lines.append("    3. search(\"<what you need>\")")
    else:
        lines.append("All providers active — explore freely with search() / shapeshift().")

    return "\n".join(lines)
