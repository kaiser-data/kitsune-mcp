import asyncio
import atexit
import contextlib
import datetime
import hashlib
import itertools
import json
import os
import re
import signal
import sys
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

import kitsune_mcp.credentials as _creds
from kitsune_mcp import oauth
from kitsune_mcp.constants import (
    DOCKER_DEFAULT_MEMORY,
    DOCKER_DEFAULT_PIDS,
    MCP_CLIENT_INFO,
    MCP_PROTOCOL_VERSION,
    POOL_MAX_IDLE_SECONDS,
    POOL_MAX_PROCESSES,
    SANDBOX_NPM_IMAGE,
    SANDBOX_PYPI_IMAGE,
    STDIO_BUFFER_LIMIT,
    TIMEOUT_HTTP_TOOL,
    TIMEOUT_PROMPT_LIST,
    TIMEOUT_RESOURCE_LIST,
    TIMEOUT_STDIO_INIT,
    TIMEOUT_STDIO_TOOL,
)
from kitsune_mcp.credentials import SMITHERY_API_KEY, _credentials_guide, _resolve_config
from kitsune_mcp.registry import SmitheryRegistry
from kitsune_mcp.session import _save_state, session
from kitsune_mcp.utils import (
    _clean_truncate,
    _estimate_tokens,
    _extract_content,
    _get_http_client,
)

# ---------------------------------------------------------------------------
# Install command validation
# ---------------------------------------------------------------------------

_SHELL_METACHAR_RE = re.compile(r"[&;|$`\n]")
_PATH_TRAVERSAL_RE = re.compile(r"\.\.[/\\]")


def _initialize_request(request_id: int = 1) -> dict:
    """Canonical MCP `initialize` JSON-RPC request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "initialize",
        "params": {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": MCP_CLIENT_INFO,
        },
    }


def _initialized_notification() -> dict:
    """Canonical MCP `notifications/initialized` message (sent after initialize succeeds)."""
    return {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}


def _negotiated_version(init_msg: dict | None) -> str:
    """Protocol version the server settled on in its initialize response.

    Streamable HTTP (spec 2025-03-26+) requires the client to echo this back
    in an MCP-Protocol-Version header on every subsequent request. Falls back
    to our requested version when the server omits it (pre-2025 servers).
    """
    result = (init_msg or {}).get("result") or {}
    return result.get("protocolVersion") or MCP_PROTOCOL_VERSION


def _validate_install_cmd(cmd: list[str]) -> None:
    """Validate argv[0] of an install command for shell injection and path traversal.

    Only checks the executable name (argv[0]) — arguments are passed directly to
    create_subprocess_exec and are not subject to shell interpretation.

    Raises ValueError if the command looks dangerous.
    """
    if not cmd:
        raise ValueError("Empty install command")
    argv0 = cmd[0]
    if _SHELL_METACHAR_RE.search(argv0):
        raise ValueError(f"Shell metacharacter in command: {argv0!r}")
    if _PATH_TRAVERSAL_RE.search(argv0):
        raise ValueError(f"Path traversal in command: {argv0!r}")


def _stdin(proc: asyncio.subprocess.Process) -> asyncio.StreamWriter:
    """proc.stdin, typed. Every child here is spawned with stdin=PIPE, so None is a bug."""
    if proc.stdin is None:
        raise RuntimeError("subprocess was started without a stdin pipe")
    return proc.stdin


class BaseTransport(ABC):
    @abstractmethod
    async def execute(self, tool: str, args: dict, config: dict) -> str: ...


# ---------------------------------------------------------------------------
# Persistent Process Pool
# ---------------------------------------------------------------------------

# Spawn each child in a fresh process group so we can signal the whole tree on
# shutdown. uvx/npx fork a real server as a child — killing only the wrapper
# orphans the child and leaks one zombie per shapeshift cycle (#kill-tree).
_SUBPROC_SPAWN_KWARGS: dict[str, Any]
if sys.platform == "win32":
    _SUBPROC_SPAWN_KWARGS = {
        "creationflags": getattr(__import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0),
    }
else:
    _SUBPROC_SPAWN_KWARGS = {"start_new_session": True}


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """SIGKILL the process and any children it spawned in its session group.

    POSIX: send SIGKILL to the negated PGID so wrappers (uvx, npx, sh -c …) and
    their children all die at once. Windows: send CTRL_BREAK_EVENT to the
    process group, then fall back to proc.kill().

    All errors are suppressed — by the time we kill, the proc may already be
    reaped (returncode set) or its pgid lookup may fail (Linux race after fork).
    Always safe to call; never raises.
    """
    if proc.returncode is not None:
        return
    pid = proc.pid
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        with contextlib.suppress(Exception):
            proc.kill()
        return
    # SAFETY: only SIGKILL a *process group we own*. We spawn every child with
    # start_new_session=True, so a real child is its own session/group leader
    # (pgid == pid). Requiring that before killpg() prevents two ways this used
    # to nuke the wrong group — and, on CI, the whole runner VM:
    #   1. a leaked/mocked pool entry whose pid is a MagicMock or a stale/fake
    #      integer (tests hardcode pid=99999); os.getpgid() on a live-by-chance
    #      pid would return a *foreign* group and killpg() would SIGKILL it.
    #   2. pid reuse racing a just-reaped child.
    # A bare int that doesn't lead its own group is never something we started.
    if isinstance(pid, int) and pid > 1:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
    # Belt-and-braces: also kill the asyncio handle so its transport tears down
    # cleanly even if killpg already reaped the leader. proc.kill() targets only
    # this one pid (never a group), so it is safe on both real and mock procs.
    with contextlib.suppress(ProcessLookupError, Exception):
        proc.kill()


async def _reap(proc: asyncio.subprocess.Process, timeout: float) -> None:
    """Kill a child and reap it without ever deadlocking on a full pipe.

    A child that has flooded its stdout/stderr PIPE blocks in write(); the
    kernel then keeps the pipe's write end open until the buffered bytes are
    drained. Calling proc.wait() while those pipes stay full can hang forever
    (reproduced on Linux CI: an unread-PIPE child + SIGKILL + wait wedges the
    whole runner). So we drain stdout/stderr to EOF *concurrently* with wait(),
    all under a hard timeout. Safe on mocked procs (guards on a real Process).
    """
    _kill_process_tree(proc)
    if not isinstance(proc, asyncio.subprocess.Process):
        return

    async def _drain(stream) -> None:
        if stream is None:
            return
        with contextlib.suppress(Exception):
            while await stream.read(65536):
                pass

    with contextlib.suppress(asyncio.TimeoutError, Exception):
        await asyncio.wait_for(
            asyncio.gather(
                proc.wait(),
                _drain(proc.stdout),
                _drain(proc.stderr),
                return_exceptions=True,
            ),
            timeout=timeout,
        )


@dataclass
class _PoolEntry:
    proc: asyncio.subprocess.Process
    install_cmd: list
    started_at: float  # time.monotonic()
    next_id: int = 3  # 1=init, 2=initialized notify
    call_count: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    name: str = ""
    last_used_at: float = field(default_factory=time.monotonic)
    dotenv_revision: int = 0  # _creds._dotenv_revision at spawn time

    def pid(self) -> int | None:
        return self.proc.pid

    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def is_alive(self) -> bool:
        return self.proc.returncode is None


_process_pool: dict[str, _PoolEntry] = {}  # keyed by json(install_cmd, sort_keys=True)


def _kill_all_pool_processes() -> None:
    """Kill every pooled subprocess synchronously.

    Registered as an atexit handler so:
    - Orphaned stdio servers are cleaned up when the MCP server exits (#11)
    - BaseSubprocessTransport.__del__ never fires after the event loop is gone,
      eliminating "RuntimeError: Event loop is closed" teardown noise (#23)
    """
    _save_state()
    for entry in list(_process_pool.values()):
        _kill_process_tree(entry.proc)
    _process_pool.clear()


atexit.register(_kill_all_pool_processes)

# Debounce: skip the O(N) pool sweep if it ran in the last EVICT_DEBOUNCE_SECONDS.
# A hot pool serving 1 call/sec was sweeping every entry on every call; the
# eviction criteria (idle > POOL_MAX_IDLE_SECONDS, typically minutes) are not
# tight enough to need sub-second precision. Forced sweeps still happen via
# `force=True` after process death is observed in the call path.
EVICT_DEBOUNCE_SECONDS = 30.0
_last_evict_at: float = 0.0


def _evict_stale_pool_entries(force: bool = False) -> list[str]:
    """Remove dead or long-idle processes from the pool. Returns evicted keys.

    Debounced: a no-op if the last sweep was within EVICT_DEBOUNCE_SECONDS
    unless force=True.
    """
    global _last_evict_at
    now = time.monotonic()
    if not force and (now - _last_evict_at) < EVICT_DEBOUNCE_SECONDS:
        return []
    _last_evict_at = now
    to_remove = [
        k
        for k, e in _process_pool.items()
        if not e.is_alive() or (now - e.last_used_at) > POOL_MAX_IDLE_SECONDS
    ]
    for k in to_remove:
        entry = _process_pool.get(k)
        if entry is not None:
            _kill_process_tree(entry.proc)
        _process_pool.pop(k, None)
    # Hard cap: if still over limit, evict oldest by last_used_at
    if len(_process_pool) > POOL_MAX_PROCESSES:
        oldest = sorted(_process_pool.items(), key=lambda kv: kv[1].last_used_at)
        for k, e in oldest[: len(_process_pool) - POOL_MAX_PROCESSES]:
            _kill_process_tree(e.proc)
            _process_pool.pop(k, None)
    return to_remove


async def _ping(entry: "_PoolEntry", timeout: float = 2.0) -> bool:
    """Send tools/list to a live pool entry and confirm it responds. Non-blocking."""
    if not entry.is_alive():
        return False
    try:
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            _stdin(entry.proc).write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": msg_id, "method": "tools/list", "params": {}}
                ).encode()
                + b"\n"
            )
            await _stdin(entry.proc).drain()
            resp = await asyncio.wait_for(
                _read_stdio_response(entry.proc.stdout, msg_id),
                timeout=timeout,
            )
            return resp is not None and "error" not in resp
    except Exception:
        return False


async def _read_stdio_response(reader, expected_id: int, timeout: float = 30.0) -> dict | None:
    """Standalone version of StdioTransport._read_response for use before class definition."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=remaining)
        except TimeoutError:
            return None
        if not line:
            return None
        try:
            msg = json.loads(line.decode().strip())
            if msg.get("id") == expected_id:
                return msg
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass


# ---------------------------------------------------------------------------
# Smithery Connect helpers (new API — api.smithery.ai/connect)
# ---------------------------------------------------------------------------

_SMITHERY_API_BASE = "https://api.smithery.ai"


@dataclass
class _SmitheryAuth:
    """Single owner of Smithery namespace + service-token state.

    Async-safe: concurrent callers past the cache miss serialize on the lock,
    so only one HTTP refresh happens per expiry window (no thundering herd).
    """

    namespace: str | None = None
    service_token: str = ""
    token_expires: float = 0.0
    namespace_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    token_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    connections: dict[str, str] = field(default_factory=dict)  # conn_id → mcpUrl

    def reset(self) -> None:
        """Clear all cached state (for tests or explicit re-auth)."""
        self.namespace = None
        self.service_token = ""
        self.token_expires = 0.0
        self.connections.clear()

    async def get_namespace(self) -> str | None:
        if self.namespace:
            return self.namespace
        api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
        if not api_key:
            return None
        async with self.namespace_lock:
            if self.namespace:  # double-check after lock
                return self.namespace
            try:
                r = await _get_http_client().get(
                    f"{_SMITHERY_API_BASE}/namespaces",
                    headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                    timeout=10,
                )
                r.raise_for_status()
                namespaces = r.json().get("namespaces", [])
                if namespaces:
                    self.namespace = namespaces[0]["name"]
            except Exception:
                pass
        return self.namespace

    async def get_token(self) -> str:
        now = time.monotonic()
        if self.service_token and now < self.token_expires:
            return self.service_token
        api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
        if not api_key:
            return ""
        async with self.token_lock:
            now = time.monotonic()
            if self.service_token and now < self.token_expires:
                return self.service_token
            try:
                r = await _get_http_client().post(
                    f"{_SMITHERY_API_BASE}/tokens",
                    json={"name": "kitsune-mcp", "scopes": ["mcp"]},
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    timeout=10,
                )
                r.raise_for_status()
                data = r.json()
                self.service_token = data["token"]
                expires_at = datetime.datetime.fromisoformat(
                    data["expiresAt"].replace("Z", "+00:00")
                )
                ttl = (expires_at - datetime.datetime.now(datetime.UTC)).total_seconds()
                self.token_expires = now + max(ttl - 300, 60)  # refresh 5 min early
            except Exception:
                self.service_token = ""
        return self.service_token


_smithery_auth = _SmitheryAuth()


# Backwards-compatible thin wrappers — keep call sites and tests stable.
async def _smithery_namespace() -> str | None:
    """Return the user's first Smithery namespace (cached for the session)."""
    return await _smithery_auth.get_namespace()


async def _smithery_service_token() -> str:
    """Return a valid service token with mcp scope (cached, auto-refreshed)."""
    return await _smithery_auth.get_token()


def _smithery_conn_id(qualified_name: str) -> str:
    """Stable, URL-safe connection ID derived from a qualified server name."""
    sanitized = re.sub(r"[^a-z0-9-]", "-", qualified_name.lower()).strip("-")
    return f"kitsune-{sanitized}"[:64]


def _build_mcp_url(deployment_url: str, config: dict) -> str:
    """Append non-null config values as query parameters to the deployment URL."""
    clean = {k: v for k, v in config.items() if v is not None}
    if not clean:
        return deployment_url
    qs = urllib.parse.urlencode(clean)
    sep = "&" if "?" in deployment_url else "?"
    return f"{deployment_url}{sep}{qs}"


async def _ensure_smithery_connection(namespace: str, conn_id: str, mcp_url: str) -> bool:
    """Create or update a Smithery Connect connection. Returns True on success."""
    # Skip if we already set up this conn_id with the same URL this session
    if _smithery_auth.connections.get(conn_id) == mcp_url:
        return True
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    client = _get_http_client()
    url = f"{_SMITHERY_API_BASE}/connect/{namespace}/{conn_id}"
    try:
        r = await client.put(url, json={"mcpUrl": mcp_url}, headers=headers, timeout=15)
        if r.status_code == 409:
            # URL mismatch — delete existing and recreate
            await client.delete(url, headers=headers, timeout=10)
            r = await client.put(url, json={"mcpUrl": mcp_url}, headers=headers, timeout=15)
        r.raise_for_status()
        _smithery_auth.connections[conn_id] = mcp_url
        return True
    except Exception:
        return False


class _SSEParser:
    """Incremental text/event-stream parser (WHATWG rules).

    Feed it one line at a time (without the line terminator); it returns an
    event's data when a blank line ends that event. Multiple `data:` lines in
    one event are joined with newlines; only one space after the colon is
    stripped; comment lines (starting with `:`) are ignored.
    """

    def __init__(self) -> None:
        self._data: list[str] = []
        self._event = ""
        self.last_event = "message"  # name of the event flush() returned last

    def feed_line(self, line: str) -> str | None:
        if line == "":
            return self.flush()
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data.append(value)
        elif name == "event":
            self._event = value
        return None

    def flush(self) -> str | None:
        event, self._event = self._event, ""
        if not self._data:
            return None
        data = "\n".join(self._data)
        self._data = []
        self.last_event = event or "message"
        return data


def _json_messages(data: str) -> list[dict]:
    """JSON-RPC messages in one payload: a single object or a batch array."""
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [m for m in parsed if isinstance(m, dict)]
    return []


def _is_response(msg: dict, request_id: int | None) -> bool:
    """True for a JSON-RPC response (not a request or notification) to request_id.

    request_id=None accepts a response to any request.
    """
    if "method" in msg or ("result" not in msg and "error" not in msg):
        return False
    return request_id is None or msg.get("id") == request_id


def _sse_messages(text: str) -> list[dict]:
    parser = _SSEParser()
    out: list[dict] = []
    for line in [*text.splitlines(), ""]:
        data = parser.feed_line(line)
        if data is not None:
            out.extend(_json_messages(data))
    return out


def _parse_sse(text: str) -> dict | None:
    """First JSON object carried by a buffered SSE body, or None."""
    messages = _sse_messages(text)
    return messages[0] if messages else None


def _parse_rpc_body(text: str, request_id: int | None = None) -> dict | None:
    """The response to request_id in a buffered Streamable HTTP body: SSE or plain JSON.

    Notifications and server-to-client requests on the same stream are skipped.
    """
    messages = _sse_messages(text) or _json_messages(text)
    return next((m for m in messages if _is_response(m, request_id)), None)


class AuthRequired(PermissionError):
    """The server answered 401/403. `challenge` is its WWW-Authenticate header, if any."""

    def __init__(self, status: int, challenge: str | None = None) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status
        self.challenge = challenge


def _auth_error(r: "_HTTPReply") -> AuthRequired:
    return AuthRequired(r.status, r.headers.get("www-authenticate"))


class CallOutcomeUnknown(RuntimeError):
    """A tools/call reached the server but no result came back; it may have run."""


def _outcome_unknown_message(tool: str, server: str, reason: str) -> str:
    return (
        f"⚠️  '{tool}' on {server}: outcome unknown, {reason}.\n"
        f"  The call may have run. Check its effect before calling it again."
    )


# MCP sessions from HTTP initialize, reused across calls so each tool call
# skips the handshake (#66). The key hashes the bearer token and config, so a
# new token or changed credentials start a new session. Records are immutable
# and stay in the cache while requests use them, so concurrent callers share
# one session; a per-key lock makes sure only one of them runs the handshake.
HTTP_SESSION_MAX_AGE = 30 * 60.0  # seconds; older sessions are closed and re-made
HTTP_SESSION_MAX_COUNT = 64  # oldest session is closed beyond this


@dataclass(frozen=True)
class _HTTPSession:
    endpoint: str
    bearer: str
    session_id: str | None  # None: the server is stateless and issued no id
    proto: str
    legacy: "_LegacySSEStream | None" = None  # set for 2024-11-05 HTTP+SSE servers
    created_at: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return time.monotonic() - self.created_at > HTTP_SESSION_MAX_AGE


@dataclass
class _HTTPReply:
    status: int
    headers: httpx.Headers
    message: dict | None  # the JSON-RPC response to our request, if one arrived

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


_http_sessions: dict[tuple[str, str], _HTTPSession] = {}
_http_session_locks: dict[tuple[str, str], asyncio.Lock] = {}
_http_request_ids = itertools.count(2)


def _http_session_key(endpoint: str, bearer: str, config: dict) -> tuple[str, str]:
    blob = f"{bearer}\0{json.dumps(config, sort_keys=True, default=str)}"
    return endpoint, hashlib.sha256(blob.encode()).hexdigest()


def _http_headers(bearer: str, sess: _HTTPSession | None) -> dict[str, str]:
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if bearer:  # no token yet: the request goes out anonymously
        hdrs["Authorization"] = f"Bearer {bearer}"
    if sess is not None:
        if sess.session_id:
            hdrs["mcp-session-id"] = sess.session_id
        hdrs["MCP-Protocol-Version"] = sess.proto
    return hdrs


def _server_request_reply(msg: dict) -> dict[str, Any]:
    """Our answer to a server-to-client request: ping succeeds, the rest are unsupported.

    Kitsune offers no client capabilities (sampling, roots, elicitation).
    """
    if msg.get("method") == "ping":
        return {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
    return {
        "jsonrpc": "2.0",
        "id": msg["id"],
        "error": {"code": -32601, "message": f"Method not supported: {msg.get('method')}"},
    }


async def _answer_server_request(
    endpoint: str, bearer: str, sess: _HTTPSession | None, msg: dict
) -> None:
    """Reply to a server-to-client request seen on a response stream.

    Kitsune offers no client capabilities (sampling, roots, elicitation), so
    anything but ping gets "method not found"; leaving it unanswered could make
    the server wait forever before it sends our result.
    """
    reply = _server_request_reply(msg)
    with contextlib.suppress(httpx.HTTPError):
        await _get_http_client().post(
            endpoint,
            content=json.dumps(reply),
            headers=_http_headers(bearer, sess),
            timeout=TIMEOUT_HTTP_TOOL,
        )


async def _http_post(
    endpoint: str, bearer: str, sess: _HTTPSession | None, payload: dict
) -> _HTTPReply:
    """POST one JSON-RPC message and read the reply as the spec allows.

    The server may answer with application/json or with an SSE stream. A
    stream is read incrementally and closed as soon as the response matching
    our request id arrives; notifications on it are skipped and server-to-client
    requests are answered. Notifications (no id) only need the status code.
    """
    request_id = payload.get("id") if "method" in payload else None
    client = _get_http_client()
    async with client.stream(
        "POST",
        endpoint,
        content=json.dumps(payload),
        headers=_http_headers(bearer, sess),
        timeout=TIMEOUT_HTTP_TOOL,
    ) as r:
        if request_id is None or not r.is_success:
            await r.aread()
            return _HTTPReply(r.status_code, r.headers, None)

        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "text/event-stream":
            parser = _SSEParser()
            async for line in r.aiter_lines():
                data = parser.feed_line(line)
                for msg in _json_messages(data) if data is not None else []:
                    if _is_response(msg, request_id):
                        return _HTTPReply(r.status_code, r.headers, msg)
                    if "method" in msg and "id" in msg:
                        await _answer_server_request(endpoint, bearer, sess, msg)
            tail = parser.flush()
            for msg in _json_messages(tail) if tail is not None else []:
                if _is_response(msg, request_id):
                    return _HTTPReply(r.status_code, r.headers, msg)
            return _HTTPReply(r.status_code, r.headers, None)

        # application/json, or a body with a missing or wrong content type.
        body = (await r.aread()).decode("utf-8", errors="replace")
        return _HTTPReply(r.status_code, r.headers, _parse_rpc_body(body, request_id))


class _LegacySSEStream:
    """Client side of the deprecated 2024-11-05 HTTP+SSE transport.

    The client opens one long-lived GET stream. Its first event, `endpoint`,
    names the URL to POST messages to; responses then arrive on the GET
    stream, matched to their request by id. Kept for servers that predate
    Streamable HTTP (spec: "Backwards compatibility").
    """

    def __init__(self, url: str, bearer: str) -> None:
        self.url = url
        self.bearer = bearer
        self.post_url: str | None = None
        self.closed = False
        self._pending: dict[Any, asyncio.Future[dict]] = {}
        self._ready: asyncio.Future[str] | None = None
        self._task: asyncio.Task[None] | None = None

    def _headers(self) -> dict[str, str]:
        hdrs = {"Content-Type": "application/json"}
        if self.bearer:
            hdrs["Authorization"] = f"Bearer {self.bearer}"
        return hdrs

    async def open(self, timeout: float) -> None:
        self._ready = asyncio.get_running_loop().create_future()
        self._task = asyncio.create_task(self._read(self._ready))
        try:
            self.post_url = await asyncio.wait_for(asyncio.shield(self._ready), timeout)
        except BaseException:
            await self.close()
            raise

    def _endpoint_url(self, data: str) -> str:
        """Resolve the endpoint event; it must stay on the server's origin.

        The bearer token goes with every POST, so a stream that names another
        host must not be able to redirect it there.
        """
        url = urllib.parse.urljoin(self.url, data.strip())
        a, b = urllib.parse.urlsplit(self.url), urllib.parse.urlsplit(url)
        if (a.scheme, a.netloc) != (b.scheme, b.netloc):
            raise RuntimeError(f"legacy SSE endpoint {url!r} is on another origin")
        return url

    async def _read(self, ready: "asyncio.Future[str]") -> None:
        error: BaseException = httpx.RemoteProtocolError("legacy SSE stream ended")
        try:
            async with _get_http_client().stream(
                "GET",
                self.url,
                headers={**self._headers(), "Accept": "text/event-stream"},
                timeout=httpx.Timeout(TIMEOUT_HTTP_TOOL, read=None),
            ) as r:
                if r.status_code in (401, 403):
                    raise AuthRequired(r.status_code, r.headers.get("www-authenticate"))
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if not r.is_success or ctype != "text/event-stream":
                    raise RuntimeError(f"legacy SSE stream: HTTP {r.status_code} ({ctype})")
                parser = _SSEParser()
                async for line in r.aiter_lines():
                    data = parser.feed_line(line)
                    if data is None:
                        continue
                    if parser.last_event == "endpoint":
                        if not ready.done():
                            ready.set_result(self._endpoint_url(data))
                        continue
                    for msg in _json_messages(data):
                        await self._dispatch(msg)
        except asyncio.CancelledError:
            error = httpx.RemoteProtocolError("legacy SSE stream closed")
            raise
        except Exception as e:
            error = e
        finally:
            self.closed = True
            if not ready.done():
                ready.set_exception(error)
            lost = httpx.RemoteProtocolError(f"legacy SSE stream lost: {error}")
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(lost)

    async def _dispatch(self, msg: dict) -> None:
        if "method" in msg:
            if "id" in msg and self.post_url:
                await _answer_server_request(self.post_url, self.bearer, None, msg)
            return
        fut = self._pending.get(msg.get("id"))
        if fut is not None and not fut.done():
            fut.set_result(msg)

    async def request(self, payload: dict) -> _HTTPReply:
        """POST one message; for a request, wait for its response on the stream."""
        if self.closed or not self.post_url:
            # Nothing was sent, so the caller may safely start a new session.
            raise httpx.ConnectError("legacy SSE stream is closed")
        request_id = payload.get("id") if "method" in payload else None
        fut: asyncio.Future[dict] | None = None
        if request_id is not None:
            fut = asyncio.get_running_loop().create_future()
            self._pending[request_id] = fut
        try:
            r = await _get_http_client().post(
                self.post_url,
                content=json.dumps(payload),
                headers=self._headers(),
                timeout=TIMEOUT_HTTP_TOOL,
            )
            if fut is None or not r.is_success:
                return _HTTPReply(r.status_code, r.headers, None)
            try:
                msg = await asyncio.wait_for(fut, TIMEOUT_HTTP_TOOL)
            except TimeoutError as e:
                raise httpx.ReadTimeout("no response on the legacy SSE stream") from e
            return _HTTPReply(r.status_code, r.headers, msg)
        finally:
            if request_id is not None:
                self._pending.pop(request_id, None)

    def close_nowait(self) -> None:
        self.closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def close(self) -> None:
        self.close_nowait()
        if self._task is not None:
            with contextlib.suppress(BaseException):
                await self._task


async def _close_http_session(sess: _HTTPSession) -> None:
    """Tell the server a session is no longer needed (spec: DELETE; 405 is allowed)."""
    if sess.legacy is not None:
        await sess.legacy.close()
        return
    if not sess.session_id:
        return
    with contextlib.suppress(httpx.HTTPError):
        await _get_http_client().delete(
            sess.endpoint, headers=_http_headers(sess.bearer, sess), timeout=5.0
        )


async def close_http_sessions() -> None:
    """Close every cached HTTP MCP session (for shutdown and tests)."""
    sessions = list(_http_sessions.values())
    _http_sessions.clear()
    await asyncio.gather(*(_close_http_session(s) for s in sessions))


def _drop_http_session(key: tuple[str, str], sess: _HTTPSession) -> None:
    """Remove sess from the cache unless another caller already replaced it."""
    if _http_sessions.get(key) is sess:
        del _http_sessions[key]
    if sess.legacy is not None:
        sess.legacy.close_nowait()


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


class HTTPSSETransport(BaseTransport):
    """Execute tool calls against an HTTP MCP server.

    Two modes:
    - Smithery-mediated (default): uses api.smithery.ai/connect with per-user
      namespaced connections and a service token.
    - Direct OAuth (`direct=True`): hits the server URL directly and attaches
      no token at first; a 401/403 runs OAuth 2.1 discovery and login
      (`kitsune_mcp.oauth.authenticate`), and later calls send the token.
    """

    def __init__(
        self,
        qualified_name: str,
        deployment_url: str = "",
        direct: bool = False,
    ):
        self.qualified_name = qualified_name
        self.direct = direct
        if direct:
            # qualified_name IS the URL in direct mode; deployment_url is the
            # same URL so downstream code (list_tools, execute) stays uniform.
            self.deployment_url = deployment_url or qualified_name
        else:
            # deployment_url comes from the registry's deploymentUrl field,
            # e.g. "https://brave.run.tools"
            self.deployment_url = deployment_url or f"https://{qualified_name}.run.tools"

    async def _connect_endpoint(self, config: dict) -> tuple[str, str] | None:
        """Return (endpoint_url, bearer_token) or None on failure."""
        if self.direct:
            # A stored login if there is one, else no token: public servers need
            # none, and one that does answers 401, which starts the login.
            try:
                token = await oauth.stored_token(self.deployment_url)
            except Exception:
                token = ""
            return self.deployment_url, token

        namespace = await _smithery_namespace()
        if not namespace:
            return None
        token = await _smithery_service_token()
        if not token:
            return None
        mcp_url = _build_mcp_url(self.deployment_url, config)
        conn_id = _smithery_conn_id(self.qualified_name)
        ok = await _ensure_smithery_connection(namespace, conn_id, mcp_url)
        if not ok:
            return None
        endpoint = f"{_SMITHERY_API_BASE}/connect/{namespace}/{conn_id}/mcp"
        return endpoint, token

    async def _session(
        self, key: tuple[str, str], endpoint: str, bearer: str, stale: _HTTPSession | None
    ) -> tuple[_HTTPSession, bool]:
        """Return (session, fresh): the cached session for key, or a new one.

        Initialization runs under a per-key lock, so concurrent callers make
        one handshake and then share its session. `stale` is a session the
        caller just saw rejected; it is never handed back.
        """
        lock = _http_session_locks.setdefault(key, asyncio.Lock())
        async with lock:
            cur = _http_sessions.get(key)
            if cur is not None and cur is not stale:
                if not cur.expired():
                    return cur, False
                _drop_http_session(key, cur)
                await _close_http_session(cur)

            r = await _http_post(endpoint, bearer, None, _initialize_request())
            if r.status in (400, 404, 405):
                # Spec backwards compatibility: an old HTTP+SSE server rejects
                # the POST; try its GET stream before giving up.
                sess = await self._legacy_session(endpoint, bearer, r.status)
            else:
                sess = await self._streamable_session(endpoint, bearer, r)

            _http_sessions[key] = sess
            while len(_http_sessions) > HTTP_SESSION_MAX_COUNT:
                oldest_key = min(_http_sessions, key=lambda k: _http_sessions[k].created_at)
                await _close_http_session(_http_sessions.pop(oldest_key))
            return sess, True

    @staticmethod
    def _check_init(r: _HTTPReply) -> dict | None:
        if r.status in (401, 403):
            raise _auth_error(r)
        if not r.ok:
            raise RuntimeError(f"Initialize failed: HTTP {r.status}")
        if r.message and "error" in r.message:
            raise RuntimeError(f"Initialize failed: {r.message['error']}")
        return r.message

    async def _streamable_session(self, endpoint: str, bearer: str, r: _HTTPReply) -> _HTTPSession:
        init_msg = self._check_init(r)
        sess = _HTTPSession(
            endpoint=endpoint,
            bearer=bearer,
            session_id=r.headers.get("mcp-session-id"),
            proto=_negotiated_version(init_msg),
        )
        note = await _http_post(endpoint, bearer, sess, _initialized_notification())
        if note.status in (401, 403):
            raise _auth_error(note)
        return sess

    async def _legacy_session(self, endpoint: str, bearer: str, post_status: int) -> _HTTPSession:
        stream = _LegacySSEStream(endpoint, bearer)
        try:
            await stream.open(TIMEOUT_HTTP_TOOL)
        except PermissionError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Initialize failed: HTTP {post_status}, and no legacy SSE stream ({e})"
            ) from e
        try:
            init_msg = self._check_init(await stream.request(_initialize_request()))
            sess = _HTTPSession(
                endpoint=endpoint,
                bearer=bearer,
                session_id=None,
                proto=_negotiated_version(init_msg),
                legacy=stream,
            )
            await stream.request(_initialized_notification())
        except BaseException:
            await stream.close()
            raise

        return sess

    async def _rpc(
        self, endpoint: str, bearer: str, config: dict, method: str, params: dict
    ) -> dict | None:
        """Send one JSON-RPC request over this endpoint's (shared) MCP session.

        Raises PermissionError on 401/403. A rejected session (the spec answers
        404, some servers 400) gets one fresh handshake and one more try, but
        only a request the server provably did not run is sent again: a
        tools/call whose response was lost could repeat a mutation, so it
        raises CallOutcomeUnknown instead.
        """
        key = _http_session_key(endpoint, bearer, config)
        request = {
            "jsonrpc": "2.0",
            "id": next(_http_request_ids),
            "method": method,
            "params": params,
        }
        replay_safe = method != "tools/call"
        stale: _HTTPSession | None = None

        for attempt in range(2):
            sess, fresh = await self._session(key, endpoint, bearer, stale)
            can_retry = attempt == 0 and not fresh
            try:
                if sess.legacy is not None:
                    r = await sess.legacy.request(request)
                else:
                    r = await _http_post(endpoint, bearer, sess, request)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                if not can_retry:
                    raise
                stale = sess  # never reached the server: safe to send again
                _drop_http_session(key, sess)
                continue
            except httpx.HTTPError as e:
                if not replay_safe:
                    raise CallOutcomeUnknown(
                        f"connection lost after sending ({type(e).__name__})"
                    ) from e
                if not can_retry:
                    raise
                stale = sess
                _drop_http_session(key, sess)
                continue

            if r.status in (401, 403):
                _drop_http_session(key, sess)
                raise _auth_error(r)
            if r.ok:
                if r.message is not None or replay_safe:
                    return r.message
                raise CallOutcomeUnknown(
                    "the server accepted the call but sent no readable response"
                )
            if r.status in (400, 404):
                # The session was rejected before the call ran.
                _drop_http_session(key, sess)
                if can_retry:
                    stale = sess
                    continue
                raise RuntimeError(f"HTTP {r.status} from the server")
            if not replay_safe:
                raise CallOutcomeUnknown(f"HTTP {r.status} from the server")
            if not can_retry:
                raise RuntimeError(f"HTTP {r.status} from the server")
            stale = sess
            _drop_http_session(key, sess)
        return None

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        result = await self._connect_endpoint(config)
        if result is None:
            return self._connect_failure_message()
        endpoint, token = result

        async def _run(bearer: str):
            msg = await self._rpc(
                endpoint, bearer, config, "tools/call", {"name": tool, "arguments": args}
            )
            if msg is None:
                raise RuntimeError("Empty response")
            return msg

        try:
            response = await asyncio.wait_for(_run(token), timeout=TIMEOUT_HTTP_TOOL)
        except CallOutcomeUnknown as e:
            return _outcome_unknown_message(tool, self.qualified_name, str(e))
        except TimeoutError:
            return (
                f"Timeout connecting to {self.qualified_name}. Server may be sleeping — try again."
            )
        except PermissionError as e:
            # Direct: the server refused the request before running it, so it is
            # safe to log in (or refresh) and send it once more.
            if self.direct:
                try:
                    new_token = await self._reauthenticate(e, token)
                    response = await asyncio.wait_for(_run(new_token), timeout=TIMEOUT_HTTP_TOOL)
                except CallOutcomeUnknown as e2:
                    return _outcome_unknown_message(tool, self.qualified_name, str(e2))
                except oauth.NoAuthMetadata as e2:
                    return f"{self.qualified_name} needs authorization: {e2}"
                except Exception as e2:
                    return f"OAuth failed for {self.qualified_name}: {e2}"
            else:
                srv = await SmitheryRegistry().get_server(self.qualified_name)
                if srv and srv.credentials:
                    resolved, missing = _resolve_config(srv.credentials, config)
                    if missing:
                        return _credentials_guide(self.qualified_name, srv.credentials, resolved)
                return (
                    f"Auth failed for {self.qualified_name}. "
                    "Check SMITHERY_API_KEY at smithery.ai/account/api-keys"
                )
        except Exception as e:
            return f"Failed to connect to {self.qualified_name}: {e}"

        if "error" in response:
            err_obj = response["error"]
            return f"Error from {self.qualified_name}/{tool}: {err_obj.get('message', json.dumps(err_obj))}"

        result_data = response.get("result", {})
        raw = _extract_content(result_data)

        tokens_out = _estimate_tokens({"tool": tool, "args": args})
        tokens_in = _estimate_tokens(raw)
        session["stats"]["total_calls"] += 1
        session["stats"]["tokens_sent"] += tokens_out
        session["stats"]["tokens_received"] += tokens_in

        return _clean_truncate(raw)

    async def _reauthenticate(self, err: PermissionError, rejected: str) -> str:
        """New token after a 401/403, using the server's challenge for discovery."""
        challenge = err.challenge if isinstance(err, AuthRequired) else None
        return await oauth.authenticate(self.deployment_url, challenge, rejected=rejected or None)

    def _connect_failure_message(self) -> str:
        if self.direct:
            return f"Cannot reach {self.qualified_name}."
        return (
            f"Cannot reach {self.qualified_name} via Smithery Connect. "
            "Check SMITHERY_API_KEY at smithery.ai/account/api-keys"
        )

    async def list_tools(self, config: dict | None = None) -> list[dict]:
        """Fetch tools/list from the configured endpoint."""
        if config is None:
            config = {}
        result = await self._connect_endpoint(config)
        if result is None:
            return []
        endpoint, token = result

        async def _run(bearer: str) -> list[dict]:
            msg = await self._rpc(endpoint, bearer, config, "tools/list", {})
            if msg and "result" in msg:
                return msg["result"].get("tools", [])
            return []

        try:
            return await asyncio.wait_for(_run(token), timeout=TIMEOUT_HTTP_TOOL)
        except PermissionError as e:
            if not self.direct:
                return []
            try:
                new_token = await self._reauthenticate(e, token)
                return await asyncio.wait_for(_run(new_token), timeout=TIMEOUT_HTTP_TOOL)
            except Exception:
                return []
        except Exception:
            return []


class StdioTransport(BaseTransport):
    """Execute tool calls on local MCP servers via stdio subprocess + JSON-RPC."""

    def __init__(self, install_cmd: list):
        self.install_cmd = install_cmd

    @staticmethod
    def _frame(msg: dict) -> bytes:
        return json.dumps(msg).encode() + b"\n"

    @staticmethod
    async def _read_response(reader, expected_id: int, timeout: float = 30.0) -> dict | None:
        """Read lines from stdout, skipping notifications, until we find expected_id."""
        return await _read_stdio_response(reader, expected_id, timeout)

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            _validate_install_cmd(self.install_cmd)
        except ValueError as e:
            return str(e)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.install_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STDIO_BUFFER_LIMIT,
                **_SUBPROC_SPAWN_KWARGS,
            )
        except FileNotFoundError:
            return f"Cannot find '{self.install_cmd[0]}'. Is node/npx installed?"
        except Exception as e:
            return f"Failed to start {self.install_cmd[0]}: {e}"

        try:
            # 1. Initialize (allow extra time for first-run package download)
            _stdin(proc).write(self._frame(_initialize_request()))
            await _stdin(proc).drain()

            init_resp = await self._read_response(
                proc.stdout, expected_id=1, timeout=TIMEOUT_STDIO_INIT
            )
            if init_resp is None:
                return f"No initialize response from {self.install_cmd[0]}"
            if "error" in init_resp:
                return f"Initialize error from {self.install_cmd[0]}: {init_resp['error']}"

            # 2. Notify initialized + 3. Call tool — batched into one flush
            _stdin(proc).write(self._frame(_initialized_notification()))
            _stdin(proc).write(
                self._frame(
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": tool, "arguments": args},
                    }
                )
            )
            await _stdin(proc).drain()

            tool_resp = await self._read_response(
                proc.stdout, expected_id=2, timeout=TIMEOUT_STDIO_TOOL
            )
            if tool_resp is None:
                return f"No response from {self.install_cmd[0]} for tool '{tool}'"
            if "error" in tool_resp:
                err = tool_resp["error"]
                return f"Tool error: {err.get('message', json.dumps(err))}"

            result = tool_resp.get("result", {})
            raw = _extract_content(result)

            tokens_out = _estimate_tokens({"tool": tool, "args": args})
            tokens_in = _estimate_tokens(raw)
            session["stats"]["total_calls"] += 1
            session["stats"]["tokens_sent"] += tokens_out
            session["stats"]["tokens_received"] += tokens_in

            return _clean_truncate(raw)

        except Exception as e:
            return f"Stdio transport error: {e}"
        finally:
            with contextlib.suppress(Exception):
                _stdin(proc).close()
            # Drain stdout/stderr while reaping — a child that flooded its PIPE
            # would otherwise deadlock proc.wait(). See _reap().
            await _reap(proc, timeout=TIMEOUT_RESOURCE_LIST)


# ---------------------------------------------------------------------------
# Persistent Stdio Transport
# ---------------------------------------------------------------------------


class PersistentStdioTransport(BaseTransport):
    """Execute tool calls on a long-lived stdio subprocess.

    The process is shared across calls via _process_pool, keyed by install_cmd.
    stderr is inherited from parent by default.
    Each pool entry has an asyncio.Lock to serialize concurrent calls.
    """

    def __init__(
        self,
        install_cmd: list,
        inherit_stderr: bool = True,
        probe_env: dict | None = None,
    ):
        self.install_cmd = install_cmd
        self.inherit_stderr = inherit_stderr
        # When probe_env is set, the subprocess starts with that env instead
        # of inheriting the host's. Pool key is suffixed so probe processes
        # never satisfy production tool calls (which expect full host env).
        self.probe_env = probe_env
        suffix = "#probe" if probe_env is not None else ""
        self._pool_key = json.dumps(install_cmd, sort_keys=True) + suffix

    @staticmethod
    def _frame(msg: dict) -> bytes:
        return json.dumps(msg).encode() + b"\n"

    async def _start_process(self) -> _PoolEntry:
        """Spawn subprocess, run MCP handshake, store in pool. Returns entry."""
        try:
            _validate_install_cmd(self.install_cmd)
        except ValueError as e:
            raise RuntimeError(str(e)) from e
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.install_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=None if self.inherit_stderr else asyncio.subprocess.PIPE,
                limit=STDIO_BUFFER_LIMIT,
                env=self.probe_env,  # None = inherit host env (default)
                **_SUBPROC_SPAWN_KWARGS,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Cannot find '{self.install_cmd[0]}'. Is it installed?") from None
        except Exception as e:
            raise RuntimeError(f"Failed to start {self.install_cmd[0]}: {e}") from e

        entry = _PoolEntry(
            proc=proc,
            install_cmd=self.install_cmd,
            started_at=time.monotonic(),
            # Every respawn (.env change, mid-call death) keeps the connect()
            # name, so reload()/release() still find the process by it.
            name=session["connections"].get(self._pool_key, {}).get("name", ""),
        )

        # MCP initialize handshake
        _stdin(proc).write(self._frame(_initialize_request()))
        await _stdin(proc).drain()

        init_resp = await StdioTransport._read_response(
            proc.stdout, expected_id=1, timeout=TIMEOUT_STDIO_INIT
        )
        if init_resp is None:
            _kill_process_tree(proc)
            raise RuntimeError(f"No initialize response from {self.install_cmd[0]}")
        if "error" in init_resp:
            _kill_process_tree(proc)
            raise RuntimeError(f"Initialize error: {init_resp['error']}")

        _stdin(proc).write(self._frame(_initialized_notification()))
        await _stdin(proc).drain()

        entry.dotenv_revision = _creds._dotenv_revision
        _process_pool[self._pool_key] = entry
        return entry

    async def _get_or_start(self) -> _PoolEntry:
        """Return existing live pool entry or start a new one.

        Evicts entries that are dead, idle too long, or spawned before a .env
        change — so new credentials are always picked up on the next call.
        """
        _evict_stale_pool_entries()
        entry = _process_pool.get(self._pool_key)
        if entry is not None and entry.is_alive():
            if entry.dotenv_revision != _creds._dotenv_revision:
                # .env changed since this process was spawned — kill and respawn
                _kill_process_tree(entry.proc)
                _process_pool.pop(self._pool_key, None)
            else:
                return entry
        return await self._start_process()

    async def _send_request(self, method: str, params: dict, timeout: float) -> dict:
        """Send a JSON-RPC request on the persistent process and return the result dict ({} on error)."""
        entry = await self._get_or_start()
        async with entry.lock:
            msg_id = entry.next_id
            entry.next_id += 1
            _stdin(entry.proc).write(
                self._frame({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
            )
            await _stdin(entry.proc).drain()
            resp = await _read_stdio_response(
                entry.proc.stdout, expected_id=msg_id, timeout=timeout
            )
            if not resp or "error" in resp:
                return {}
            return resp.get("result") or {}

    async def list_tools(self) -> list[dict]:
        """Ask live process for its tool list via tools/list."""
        result = await self._send_request("tools/list", {}, TIMEOUT_STDIO_TOOL)
        return result.get("tools", [])

    async def list_resources(self) -> list[dict]:
        """Ask live process for its resource list via resources/list."""
        result = await self._send_request("resources/list", {}, 10.0)
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> str:
        """Read a single resource by URI via resources/read."""
        result = await self._send_request("resources/read", {"uri": uri}, 10.0)
        # Resource content items use mimeType, not type — extract any text field present
        return "\n".join(c["text"] for c in result.get("contents", []) if "text" in c)

    async def list_prompts(self) -> list[dict]:
        """Ask live process for its prompt list via prompts/list."""
        result = await self._send_request("prompts/list", {}, TIMEOUT_PROMPT_LIST)
        return result.get("prompts", [])

    async def get_prompt(self, name: str, arguments: dict) -> list[dict]:
        """Fetch a rendered prompt by name via prompts/get."""
        result = await self._send_request(
            "prompts/get", {"name": name, "arguments": arguments}, TIMEOUT_PROMPT_LIST
        )
        return result.get("messages", [])

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            entry = await self._get_or_start()
        except RuntimeError as e:
            return str(e)

        for attempt in range(2):  # one retry on mid-call process death
            async with entry.lock:
                if not entry.is_alive():
                    try:
                        entry = await self._start_process()
                    except RuntimeError as e:
                        return f"Reconnect failed: {e}"

                msg_id = entry.next_id
                entry.next_id += 1

                try:
                    _stdin(entry.proc).write(
                        self._frame(
                            {
                                "jsonrpc": "2.0",
                                "id": msg_id,
                                "method": "tools/call",
                                "params": {"name": tool, "arguments": args},
                            }
                        )
                    )
                    await _stdin(entry.proc).drain()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    if attempt == 0:
                        # Process died mid-write — evict and retry
                        _kill_process_tree(entry.proc)
                        _process_pool.pop(self._pool_key, None)
                        try:
                            entry = await self._start_process()
                        except RuntimeError as e:
                            return f"Reconnect failed: {e}"
                        continue
                    return f"Failed to send to {self.install_cmd[0]} after reconnect"
                except Exception as e:
                    return f"Failed to send to {self.install_cmd[0]}: {e}"

                tool_resp = await StdioTransport._read_response(
                    entry.proc.stdout, expected_id=msg_id, timeout=TIMEOUT_STDIO_TOOL
                )
                if tool_resp is None:
                    if not entry.is_alive():
                        # Died after the request landed: the tool may have run,
                        # so don't send it again. The next call starts fresh.
                        _process_pool.pop(self._pool_key, None)
                        return _outcome_unknown_message(
                            tool, self.install_cmd[0], "the server process exited before replying"
                        )
                    return f"No response from {self.install_cmd[0]} for tool '{tool}'"
                if "error" in tool_resp:
                    err = tool_resp["error"]
                    return f"Tool error: {err.get('message', json.dumps(err))}"

                entry.call_count += 1
                entry.last_used_at = time.monotonic()
                result = tool_resp.get("result", {})
                raw = _extract_content(result)

                tokens_out = _estimate_tokens({"tool": tool, "args": args})
                tokens_in = _estimate_tokens(raw)
                session["stats"]["total_calls"] += 1
                session["stats"]["tokens_sent"] += tokens_out
                session["stats"]["tokens_received"] += tokens_in
                return _clean_truncate(raw)

        return f"Failed to call '{tool}' after reconnect"  # unreachable but satisfies type checker


async def _ws_exchange(ws: Any, payload: dict, timeout: float) -> dict:
    """Send one JSON-RPC request over a WebSocket and return the response to it.

    Frames are read until the one whose id matches arrives. Notifications and
    responses to other ids are skipped; server-to-client requests are answered
    so the server never waits on us.
    """
    await ws.send(json.dumps(payload))
    request_id = payload["id"]

    async def _wait() -> dict:
        while True:
            raw = await ws.recv()
            text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
            for msg in _json_messages(text):
                if _is_response(msg, request_id):
                    return msg
                if "method" in msg and "id" in msg:
                    await ws.send(json.dumps(_server_request_reply(msg)))

    return await asyncio.wait_for(_wait(), timeout)


class _WSInitError(RuntimeError):
    """The server rejected or garbled initialize; nothing else was sent."""


class WebSocketTransport(BaseTransport):
    """MCP over WebSocket (ws:// or wss://), one connection per operation.

    WebSocket is not one of the MCP specification's standard transports; it is
    a custom transport that some servers offer. Each message is one JSON-RPC
    object per text frame. Requires the 'websockets' package (`kitsune-mcp[ws]`).
    """

    def __init__(self, url: str):
        self.url = url

    @contextlib.asynccontextmanager
    async def _connect(self):
        """Open a connection and run the initialize handshake; yield a request function."""
        import websockets

        async with websockets.connect(self.url, open_timeout=TIMEOUT_STDIO_INIT) as ws:
            ids = itertools.count(1)
            init = await _ws_exchange(ws, _initialize_request(next(ids)), TIMEOUT_STDIO_INIT)
            if "error" in init:
                err = init["error"]
                raise _WSInitError(f"initialize failed: {err.get('message', err)}")
            if "protocolVersion" not in (init.get("result") or {}):
                raise _WSInitError("initialize reply has no protocolVersion")
            await ws.send(json.dumps(_initialized_notification()))

            async def request(method: str, params: dict, timeout: float) -> dict:
                payload = {"jsonrpc": "2.0", "id": next(ids), "method": method, "params": params}
                return await _ws_exchange(ws, payload, timeout)

            yield request

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        try:
            import websockets  # noqa: F401
        except ImportError:
            return "WebSocket transport requires 'websockets': pip install 'kitsune-mcp[ws]'"

        sent = False
        try:
            async with self._connect() as request:
                sent = True
                msg = await request(
                    "tools/call", {"name": tool, "arguments": args}, TIMEOUT_HTTP_TOOL
                )
        except Exception as e:
            if sent:
                # The call went out; its effect is unknown, so don't suggest a blind retry.
                reason = "no reply in time" if isinstance(e, TimeoutError) else f"{e}"
                return _outcome_unknown_message(tool, self.url, reason)
            return f"WebSocket error ({self.url}): {e}"

        if "error" in msg:
            err = msg["error"]
            return f"Error {err.get('code', '')}: {err.get('message', str(err))}"

        result = msg.get("result", {})
        raw_text = _extract_content(result)

        tokens_out = _estimate_tokens({"tool": tool, "args": args})
        tokens_in = _estimate_tokens(raw_text)
        session["stats"]["total_calls"] += 1
        session["stats"]["tokens_sent"] += tokens_out
        session["stats"]["tokens_received"] += tokens_in
        return _clean_truncate(raw_text)

    async def list_tools(self, config: dict | None = None) -> list[dict]:
        """tools/list over WebSocket, following pagination cursors. [] on any failure."""
        try:
            async with self._connect() as request:
                tools: list[dict] = []
                params: dict = {}
                for _ in range(50):  # bound a server that never stops paginating
                    msg = await request("tools/list", params, TIMEOUT_HTTP_TOOL)
                    result = msg.get("result") or {}
                    tools.extend(result.get("tools", []))
                    cursor = result.get("nextCursor")
                    if not cursor:
                        break
                    params = {"cursor": cursor}
                return tools
        except Exception:
            return []


def _hardened_docker_flags(config: dict, tmpfs_exec: bool = False) -> list[str]:
    """Locked-down `docker run` flags shared by DockerTransport and sandbox_wrap_cmd().

    See DockerTransport's docstring for the profile rationale and the meaning
    of each config override (memory, pids_limit, writable, network, cap_add).

    tmpfs_exec: Docker's default --tmpfs options include noexec — right for
    DockerTransport's scratch space (the server ships in the image), fatal for
    the sandbox wrap, where npx/uvx must EXECUTE the package they download
    into /tmp (HOME and the package caches point there).
    """
    memory = str(config.get("memory") or DOCKER_DEFAULT_MEMORY)
    pids_limit = str(config.get("pids_limit") or DOCKER_DEFAULT_PIDS)
    flags = [
        "--label",
        "kitsune-mcp=1",
        "--memory",
        memory,
        "--pids-limit",
        pids_limit,
        "--security-opt",
        "no-new-privileges",
        "--cap-drop",
        "ALL",
    ]
    for cap in config.get("cap_add") or []:
        flags += ["--cap-add", str(cap)]
    # Read-only root filesystem unless the server explicitly needs to write.
    # Always give it a small writable tmpfs so well-behaved servers can scratch.
    # (tmpfs pages count against --memory, so the exec variant's size stays
    # within the default cap.)
    if not config.get("writable"):
        tmpfs = "/tmp:rw,exec,nosuid,size=512m" if tmpfs_exec else "/tmp"
        flags += ["--read-only", "--tmpfs", tmpfs]
    network = config.get("network")
    if network:
        flags += ["--network", str(network)]
    return flags


# launcher → (base image, cache env forced onto the tmpfs so the read-only
# rootfs doesn't break package download on first run)
_SANDBOX_LAUNCHERS = {
    "npx": (SANDBOX_NPM_IMAGE, {"HOME": "/tmp", "npm_config_cache": "/tmp/.npm"}),
    "uvx": (SANDBOX_PYPI_IMAGE, {"HOME": "/tmp", "UV_CACHE_DIR": "/tmp/.uv-cache"}),
}


def sandbox_wrap_cmd(
    cmd: list[str], env_names: list[str] | None = None, config: dict | None = None
) -> list[str]:
    """Wrap a local `npx`/`uvx` launch in the hardened `docker run` profile.

    The container gets no host filesystem, no capabilities, a read-only rootfs,
    and RAM/PID caps — the same profile DockerTransport applies to `docker:`
    images. Credential env vars are forwarded by NAME only (`-e KEY`): docker
    copies each value from its own (inherited) environment, so secrets never
    appear in the argv, `ps` output, or the process-pool key.

    Raises ValueError for launchers other than npx/uvx — arbitrary local
    commands have no known base image to run in.
    """
    if not cmd:
        raise ValueError("sandbox: empty command")
    launcher = cmd[0]
    if launcher not in _SANDBOX_LAUNCHERS:
        raise ValueError(
            f"sandbox supports npx/uvx commands only, got {launcher!r} — "
            f"run it unsandboxed or provide a docker: image instead"
        )
    image, cache_env = _SANDBOX_LAUNCHERS[launcher]
    config = config or {}
    wrapped = ["docker", "run", "--rm", "-i", *_hardened_docker_flags(config, tmpfs_exec=True)]
    for k, v in cache_env.items():
        wrapped += ["-e", f"{k}={v}"]
    for name in env_names or []:
        wrapped += ["-e", name]
    wrapped.append(str(config.get("image") or image))
    wrapped += cmd
    return wrapped


class DockerTransport(BaseTransport):
    """Run an MCP server inside a Docker container via stdio, hardened by default.

    Every container runs with a locked-down profile so an untrusted image is
    contained even if it turns hostile:
    - ephemeral        (--rm auto-removes it on exit)
    - RAM-capped       (--memory, default 512m)
    - PID-capped       (--pids-limit, default 512 — blunts fork bombs)
    - no privilege esc (--security-opt no-new-privileges)
    - no capabilities  (--cap-drop ALL)
    - read-only rootfs (--read-only + --tmpfs /tmp for scratch space)
    - pooled through PersistentStdioTransport — shares the 10-process hard cap

    Networking stays on by default (most MCP servers need egress); pass
    config["network"]="none" to cut it. This is stronger than a bare `docker
    run`, but Docker is not a security boundary against a kernel exploit —
    treat it as defence-in-depth, not a guarantee.

    Config overrides (all optional):
        memory:     RAM limit                (default "512m")
        pids_limit: max processes            (default 512)
        writable:   True → drop --read-only  (for servers that write to disk)
        network:    docker --network value   (e.g. "none")
        cap_add:    list of caps to re-add   (for servers that truly need one)
        env:        {name: value} passed as -e

    Usage:
        call("docker:mcp/my-image:latest", "tool_name", {...})
        call("docker:my-image", "tool_name", {...}, config={"network": "none"})
    """

    def __init__(self, image: str):
        self.image = image

    def _build_cmd(self, config: dict) -> list[str]:
        cmd = ["docker", "run", "--rm", "-i", *_hardened_docker_flags(config)]
        for k, v in (config.get("env") or {}).items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append(self.image)
        return cmd

    async def execute(self, tool: str, args: dict, config: dict) -> str:
        cmd = self._build_cmd(config)
        return await PersistentStdioTransport(cmd).execute(tool, args, config)
