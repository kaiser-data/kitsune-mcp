"""Shared state and helpers for kitsune_mcp.tools.* submodules.

Submodules access cross-cutting names (registry singleton, transports, mocked
helpers) via `_state.X` so that test-time `mock.patch("kitsune_mcp.tools._state.X")`
intercepts every call site uniformly. Defining a helper here vs. in a submodule
is a deliberate choice driven by whether tests mock it.
"""

import asyncio
import os
import re
import shutil

from kitsune_mcp.constants import (
    MAX_RESOURCE_DOCS,
    RESOURCE_PRIORITY_KEYWORDS,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_RESOURCE_READ,
    TRUST_LOW,
)
from kitsune_mcp.credentials import (
    _resolve_config,  # noqa: F401  (accessed as _state._resolve_config in shapeshift + tests)
    _smithery_available,  # noqa: F401  (accessed as _state._smithery_available in shapeshift + tests)
    _to_env_var,
)
from kitsune_mcp.pins import (
    reconcile as reconcile_pin,  # noqa: F401  (accessed as _state.reconcile_pin in shapeshift + tests)
)
from kitsune_mcp.probe import (
    _doc_uri_priority,
    _probe_requirements,  # noqa: F401  (accessed as _state._probe_requirements in shapeshift + tests)
)
from kitsune_mcp.registry import (
    NpmRegistry,  # noqa: F401  (accessed as _state.NpmRegistry in discovery.py)
    PyPIRegistry,  # noqa: F401  (accessed as _state.PyPIRegistry in discovery.py)
    SmitheryRegistry,  # noqa: F401  (accessed as _state.SmitheryRegistry in discovery.py)
    _registry,
)
from kitsune_mcp.session import session
from kitsune_mcp.shapeshift import (
    _do_shed,  # noqa: F401  (accessed as _state._do_shed in shapeshift tools + tests)
    _proxy_name_for,  # noqa: F401  (accessed as _state._proxy_name_for, backward compat)
    _register_proxy_prompts,  # noqa: F401  (accessed as _state._register_proxy_prompts)
    _register_proxy_resources,  # noqa: F401  (accessed as _state._register_proxy_resources)
    _register_proxy_tools,  # noqa: F401  (accessed as _state._register_proxy_tools)
)
from kitsune_mcp.transport import (
    BaseTransport,
    DockerTransport,
    HTTPSSETransport,
    PersistentStdioTransport,
    WebSocketTransport,
    sandbox_wrap_cmd,  # noqa: F401  (accessed as _state.sandbox_wrap_cmd in shapeshift + tests)
)

# JSON-schema type → example value, for the `call(...)` hint shown to users.
_EXAMPLE_VALUES = {"string": "hello world", "integer": 1, "number": 1.0, "boolean": True, "array": [], "object": {}}
# JSON-schema type → dummy value, for fabricating args in inspect() full-mode probes.
_DUMMY_VALUES = {"string": "test", "integer": 0, "boolean": False, "number": 0.0}

# Base tool names — used for collision detection in shapeshift()
_BASE_TOOL_NAMES = {
    "auth", "search", "inspect", "call", "run", "fetch",
    "skill", "key", "login", "auto", "status", "shapeshift", "shiftback", "craft",
    "connect", "release", "reload", "test", "bench", "setup", "compare", "onboard", "prewarm",
}

# Default (lean) profile — server.py prunes to this set when KITSUNE_TOOLS is unset.
# The connect/release/reload trio is lean so the MCP REPL (Kitsune's headline
# developer loop) works on a default install without KITSUNE_TOOLS=all.
_LEAN_TOOL_NAMES = {
    "status", "search", "auth", "shapeshift", "call", "auto",
    "connect", "release", "reload",
}


def _active_tool_names() -> set[str]:
    """Resolve the active tool profile from KITSUNE_TOOLS.

    Single source of truth for profile resolution: server.py uses it to prune
    tools at import time, and user-facing messages (e.g. the GATEWAY hint in
    status()) use it to avoid recommending tools outside the active profile.
    """
    env = os.getenv("KITSUNE_TOOLS", "")
    if env.lower() == "all":
        return set(_BASE_TOOL_NAMES)
    if env:
        return {t.strip() for t in env.split(",")} & _BASE_TOOL_NAMES
    return set(_LEAN_TOOL_NAMES)

# Used by compare() to estimate token cost when a probe is gated/failed but
# the registry knows the tool count. Calibrated from measured probes:
# stdio MCP tool descriptions average ~600 tokens each (very rough).
_AVG_TOKENS_PER_TOOL = 600

# Many MCP descriptions literally state their tool count, e.g. "26 tools".
# We parse this as a fallback signal for compare()'s estimate.
_TOOL_COUNT_RE = re.compile(r"\b(\d{1,3})\s+tools?\b", re.IGNORECASE)

_PROBE_CRED_SUFFIXES = ("_TOKEN", "_KEY", "_SECRET", "_API_KEY", "_PAT", "_PASSWORD")


def _track_call(server_id: str, tool_name: str) -> None:
    """Increment call counter for a server and remember the last tool used."""
    prior = session["grown"].get(server_id, {"calls": 0})
    session["grown"][server_id] = {
        "last_tool": tool_name,
        "calls": prior["calls"] + 1,
        "status": "active",
    }


def _get_transport(server_id: str, srv) -> "BaseTransport":
    """Select the right transport for a server_id + optional ServerInfo."""
    if server_id.startswith("docker:"):
        return DockerTransport(server_id[len("docker:"):])
    if server_id.startswith(("ws://", "wss://")):
        return WebSocketTransport(server_id)
    if server_id.startswith(("http://", "https://")):
        # Direct URL escape hatch: treat as a hosted HTTP MCP with OAuth 2.1.
        # The transport probes `.well-known/oauth-authorization-server` at
        # connect time and attaches a Bearer token via kitsune_mcp.oauth.
        return HTTPSSETransport(server_id, deployment_url=server_id, direct=True)
    if srv is not None and getattr(srv, "transport", None) == "websocket":
        return WebSocketTransport(srv.url)
    if srv is not None and getattr(srv, "transport", None) == "stdio":
        cmd = srv.install_cmd or ["npx", "-y", server_id]
        return PersistentStdioTransport(cmd)
    if srv is not None and getattr(srv, "transport", None) == "http":
        # Hosted HTTP MCP from the registry. If the URL isn't Smithery's
        # run.tools domain, assume it's a direct server and use OAuth.
        direct = ".run.tools" not in (srv.url or "")
        return HTTPSSETransport(srv.id, deployment_url=srv.url, direct=direct)
    return HTTPSSETransport(server_id)


def _extract_tool_schema(tool: dict) -> tuple[dict, set]:
    """Return (properties, required_set) from a tool's inputSchema."""
    schema = tool.get("inputSchema") or {}
    return schema.get("properties") or {}, set(schema.get("required") or [])


async def _fetch_resource_docs(transport: "BaseTransport") -> str:
    """Fetch high-priority resource docs from a transport (best-effort)."""
    try:
        resources = await asyncio.wait_for(
            transport.list_resources(), timeout=TIMEOUT_RESOURCE_LIST
        )
        all_uris = [r["uri"] for r in resources]
        doc_uris = sorted(
            (u for u in all_uris if _doc_uri_priority(u) < len(RESOURCE_PRIORITY_KEYWORDS)),
            key=_doc_uri_priority,
        )[:MAX_RESOURCE_DOCS]
        parts = await asyncio.gather(
            *[asyncio.wait_for(transport.read_resource(u), timeout=TIMEOUT_RESOURCE_READ) for u in doc_uris],
            return_exceptions=True,
        )
        return "\n".join(p for p in parts if isinstance(p, str))
    except Exception:
        return ""


def _tool_count_hint(text: str) -> int | None:
    """Pull a plausible tool count out of a server's description."""
    if not text:
        return None
    m = _TOOL_COUNT_RE.search(text)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 200 else None


def _compare_missing_creds(srv) -> list[str]:
    """Strict missing-cred check for compare().

    Unlike _resolve_config (which filters by cred-shaped suffix to avoid
    blocking on optional config knobs), this trusts the registry: if a cred
    is declared, it's required for probe purposes. Returns env-var names
    in declaration order.
    """
    missing = []
    for cred_key in (srv.credentials or {}):
        var = _to_env_var(cred_key)
        if not os.getenv(var):
            missing.append(var)
    return missing


def _humanize_probe_error(err: str) -> str:
    """Map common probe failures to a short, human-readable label."""
    if not err:
        return ""
    if err.startswith("No initialize response"):
        return "init timeout (60s)"
    if err.startswith("Cannot find"):
        return "binary not found"
    if "Path traversal" in err:
        return "rejected: path traversal"
    if "Shell metacharacter" in err:
        return "rejected: shell injection"
    return err[:30]


def _synthetic_http_server(url: str):
    """Build a ServerInfo-shaped object for a bare HTTP MCP URL (OAuth escape hatch)."""
    from urllib.parse import urlparse

    from kitsune_mcp.registry import ServerInfo
    host = urlparse(url).netloc or url
    return ServerInfo(
        id=url,
        name=host,
        description=f"Direct hosted MCP server at {url}",
        source="direct",
        transport="http",
        url=url,
    )


def _probe_trust_ok(srv) -> tuple[bool, str]:
    """Decide whether `inspect()` may auto-probe (i.e. run code from this server).

    Returns (allow, reason). HIGH/MEDIUM-trust registry sources are allowed by
    default. LOW-trust sources, plus anything installed via `npx github:...`
    or `uvx github:...`, require explicit consent (probe=True or KITSUNE_TRUST).
    """
    trust = (os.getenv("KITSUNE_TRUST") or "").lower()
    if trust in ("community", "all", "low"):
        return True, ""
    cmd = srv.install_cmd or []
    pkg = cmd[-1] if cmd else ""
    if pkg.startswith("github:"):
        return False, f"github install via {srv.source}"
    if srv.source in TRUST_LOW:
        return False, f"community source ({srv.source})"
    return True, ""


def _sandbox_active(explicit: bool, source: str) -> bool:
    """Should this mount run inside the Docker sandbox?

    explicit=True (the shapeshift(sandbox=True) flag) always wins. Otherwise
    KITSUNE_SANDBOX sets a session policy: "1"/"true"/"all"/"docker" sandboxes
    every local stdio mount; "community" sandboxes only low-trust sources.
    """
    if explicit:
        return True
    mode = (os.getenv("KITSUNE_SANDBOX") or "").lower()
    if mode == "off":
        return False
    if mode in ("1", "true", "all", "docker"):
        return True
    if mode == "community":
        return source in TRUST_LOW
    return False


def _sandbox_env_names(srv) -> list[str]:
    """Env var NAMES a sandboxed server needs — values are never inlined.

    An unsandboxed stdio subprocess inherits the whole host environment; a
    sandboxed one starts empty, so we forward (by name only, via value-less
    `docker -e KEY`) the vars the server plausibly needs:
      1. Every credential declared in `srv.credentials`.
      2. The same heuristic _probe_env uses — host vars with a cred-shaped
         suffix sharing a name token with the server's id/name (npm/pypi
         listings declare no credentials, so this is the common path).
    Everything else (AWS_*, unrelated API keys) stays on the host.

    srv may be None on ad-hoc paths (run(), unknown-package call()) — no declared
    creds and no identity to match, so nothing is forwarded.
    """
    if srv is None:
        return []
    names = [_to_env_var(c) for c in (srv.credentials or {})]
    haystack = {
        tok for tok in re.findall(r"[a-z0-9]{4,}", (srv.id + " " + srv.name).lower())
    }
    if haystack:
        for var in os.environ:
            if var in names or not var.endswith(_PROBE_CRED_SUFFIXES):
                continue
            var_lower = var.lower()
            if any(tok in var_lower for tok in haystack):
                names.append(var)
    return names


def _sandbox_default_for_exec(explicit: bool, source: str) -> bool:
    """Sandbox policy for the auto()/call()/run() execution paths.

    Broader than shapeshift's `_sandbox_active`: on these "magic" paths the model
    (auto) or an ad-hoc caller (call/run) runs a server nobody explicitly vetted,
    so low-trust community sources AND unknown-source local servers default to the
    Docker cage. Any explicit KITSUNE_SANDBOX policy (all/community/…) still
    applies on top via `_sandbox_active`. Medium/high-trust registry sources are
    vetted enough to skip the default cage.
    """
    if _sandbox_active(explicit, source):
        return True
    # KITSUNE_SANDBOX=off is the session-wide escape hatch — it must also switch
    # off the default cage, not just the explicit all/community policy.
    if (os.getenv("KITSUNE_SANDBOX") or "").lower() == "off":
        return False
    return source in TRUST_LOW or not source


def _sandbox_for_mount(sandbox: bool | None, source: str) -> bool:
    """Tri-state cage policy for the shapeshift()/prewarm() mount paths.

    `sandbox` carries the caller's tri-state request:
      True  → always cage (the caller hard-fails if Docker is missing).
      False → never cage (explicit opt-out — the escape hatch).
      None  → policy default: low-trust / unknown-source servers are caged,
              medium/high-trust registry sources are not. An explicit
              KITSUNE_SANDBOX policy (all/community) layers on top;
              KITSUNE_SANDBOX=off disables the default cage.

    Docker availability is NOT checked here (this is pure policy) — the caller
    decides hard-fail vs best-effort-uncaged when the daemon is missing.
    """
    if sandbox is True:
        return True
    if sandbox is False:
        return False
    return _sandbox_default_for_exec(False, source)


# Nudge appended when a sandbox was wanted but Docker isn't on PATH. The server
# still runs (uncaged) — the exec paths never hard-fail on a missing daemon,
# unlike shapeshift(sandbox=True), which the user asked for explicitly.
_UNCAGED_NOTE = (
    "\n⚠️  Ran uncaged — Docker not found on PATH. "
    "Install Docker to sandbox community/untrusted servers."
)


def sandboxed_stdio_transport(cmd: list[str], srv, explicit: bool = False):
    """Return (transport, note) for an ad-hoc local stdio launch (run()).

    Wraps `cmd` in the hardened Docker profile when policy wants a sandbox AND
    Docker is on PATH AND `cmd` is an npx/uvx launch; otherwise runs it as-is.
    Used by run(), which builds its own argv and has no registry transport.
    """
    source = getattr(srv, "source", "") or ""
    note = ""
    if cmd and cmd[0] in ("npx", "uvx") and _sandbox_default_for_exec(explicit, source):
        if shutil.which("docker"):
            cmd = sandbox_wrap_cmd(cmd, env_names=_sandbox_env_names(srv))
        else:
            note = _UNCAGED_NOTE
    return PersistentStdioTransport(cmd), note


def transport_for_exec(server_id: str, srv, explicit_sandbox: bool = False):
    """Return (transport, note) for auto()/call() — sandbox local stdio per policy.

    HTTP/WS/OAuth and `docker:` servers route through `_get_transport` unchanged
    (nothing runs locally, so there is nothing to cage). For a local stdio server
    the launch is Docker-wrapped only when policy wants a cage AND Docker is on
    PATH AND the launch is npx/uvx; every other case delegates to `_get_transport`
    (uncaged) — with a nudge note when a cage was wanted but Docker was missing.
    """
    if server_id.startswith(("http://", "https://", "ws://", "wss://", "docker:")):
        return _get_transport(server_id, srv), ""
    if srv is not None and getattr(srv, "transport", None) not in (None, "stdio"):
        return _get_transport(server_id, srv), ""
    source = getattr(srv, "source", "") or ""
    cmd = (getattr(srv, "install_cmd", None) or _infer_install_cmd(server_id))
    if cmd and cmd[0] in ("npx", "uvx") and _sandbox_default_for_exec(explicit_sandbox, source):
        if shutil.which("docker"):
            wrapped = sandbox_wrap_cmd(cmd, env_names=_sandbox_env_names(srv))
            return PersistentStdioTransport(wrapped), ""
        return _get_transport(server_id, srv), _UNCAGED_NOTE
    return _get_transport(server_id, srv), ""


def _probe_env(srv) -> dict:
    """Build a sanitized env for inspect probes.

    Passes only PATH, HOME (a tempdir), TMPDIR, and credential-shaped env
    vars relevant to this server. Two passes:
      1. Vars explicitly declared in `srv.credentials`.
      2. Heuristic — vars whose name shares a token with the server's id/name
         (e.g. `NOTION_TOKEN` for `@notionhq/notion-mcp-server`). Helps when
         the registry didn't declare creds but the user has them set.

    Excluded by construction: every other env var (AWS_*, OPENAI_API_KEY, etc.).

    Limitation: does NOT prevent on-disk secret reads (~/.kitsune/oauth,
    ~/.aws). Real isolation is the deferred Docker-sandbox follow-up.
    """
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="kitsune-probe-")
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": tmpdir,
        "TMPDIR": tmpdir,
    }
    for cred_name in srv.credentials or {}:
        var = _to_env_var(cred_name)
        val = os.environ.get(var)
        if val is not None:
            env[var] = val
    # Heuristic passthrough — match host env vars to server identity.
    haystack = {
        tok for tok in re.findall(r"[a-z0-9]{4,}", (srv.id + " " + srv.name).lower())
    }
    if haystack:
        for var, val in os.environ.items():
            if var in env or not var.endswith(_PROBE_CRED_SUFFIXES):
                continue
            var_lower = var.lower()
            if any(tok in var_lower for tok in haystack):
                env[var] = val
    return env


def _probe_label(srv) -> str:
    """Human-readable summary of how a probe was run, for the TOOLS line."""
    if srv.source == "direct" and srv.transport == "http":
        return f"via OAuth {srv.url}"
    if srv.install_cmd:
        return f"via {' '.join(srv.install_cmd)}"
    return "live"


def _infer_install_cmd(server_id: str) -> list[str]:
    """npm-style (@scope/pkg, has /, no dots) → npx -y; Python-style (has dots) → uvx."""
    if server_id.startswith("@") or "/" in server_id or "." not in server_id:
        return ["npx", "-y", server_id]
    return ["uvx", server_id]


def _local_uninstall_cmd(install_cmd: list[str]) -> list[str] | None:
    """uvx pkg → uv tool uninstall pkg. npx → None (cache is ephemeral)."""
    if install_cmd and install_cmd[0] == "uvx" and len(install_cmd) >= 2:
        return ["uv", "tool", "uninstall", install_cmd[-1]]
    return None


# ---------------------------------------------------------------------------
# Fuzzy server-id resolution (auto-recovery for typos / wrong namespaces)
# ---------------------------------------------------------------------------

_RESOLVE_PREFIXES = ("mcp-server-", "server-mcp-", "mcp-", "server-")
_RESOLVE_SUFFIXES = ("-mcp-server", "-mcp")


def _normalize_for_match(s: str) -> str:
    """Strip @org/, leading mcp-server- / server-mcp- / mcp-, trailing -mcp[-server],
    lowercase, then keep alphanumerics only.

    Examples:
      @modelcontextprotocol/server-time → "time"
      mcp-server-time                   → "time"
      @scope/foo-bar-mcp                → "foobar"
    """
    if not s:
        return ""
    s = s.lower()
    if s.startswith("@") and "/" in s:
        s = s.split("/", 1)[1]
    for prefix in _RESOLVE_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    for suffix in _RESOLVE_SUFFIXES:
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return re.sub(r"[^a-z0-9]", "", s)


async def _resolve_server_id(server_id: str) -> tuple[str | None, list[str]]:
    """Try fuzzy resolution of a missing server_id across all registries.

    Returns (resolved_id, candidates):
      - (resolved_id, [resolved_id]) if exactly one high-confidence match
      - (None, [a, b, c])           if multiple plausible matches
      - (None, [])                  if nothing close

    "High confidence" = exact-equal normalized form first; if none, fall back
    to substring overlap. Auto-resolution only fires when there's a single
    match — multiple matches are listed for the caller to disambiguate, never
    silently picked.
    """
    needle = _normalize_for_match(server_id)
    if not needle:
        return None, []
    try:
        candidates = await _registry.search(needle, limit=10)
    except Exception:
        return None, []
    if not candidates:
        return None, []

    # Dedupe candidates by id — defends against any future case where the
    # same canonical entry surfaces from multiple registries. (MultiRegistry
    # already dedupes by name, but this layer should be robust anyway.)
    seen_ids: set[str] = set()
    deduped = []
    for s in candidates:
        if s.id not in seen_ids:
            seen_ids.add(s.id)
            deduped.append(s)

    exact = [s for s in deduped if _normalize_for_match(s.id) == needle]
    if len(exact) == 1:
        return exact[0].id, [exact[0].id]
    if len(exact) > 1:
        return None, [s.id for s in exact[:3]]

    substr = [
        s for s in deduped
        if needle in _normalize_for_match(s.id) or _normalize_for_match(s.id) in needle
    ]
    if len(substr) == 1:
        return substr[0].id, [substr[0].id]
    if len(substr) > 1:
        return None, [s.id for s in substr[:3]]
    return None, []
