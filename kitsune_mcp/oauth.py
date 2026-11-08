"""OAuth 2.1 client for MCP servers (MCP authorization spec).

Discovery follows the server's 401 challenge: `WWW-Authenticate` names the
Protected Resource Metadata (RFC 9728), which names the authorization server,
possibly on another origin; its metadata (RFC 8414 / OpenID Connect discovery)
must state the issuer it was fetched for. Servers from before 2025-06 publish
no resource metadata; then the MCP server's own origin is the authorization
server. Flow: PKCE S256, Dynamic Client Registration (RFC 7591), resource
indicators (RFC 8707), authorization_code + refresh_token grants.

Tokens and client registrations live in `~/.kitsune/oauth/<key>/` with mode
0600, where the key is derived from the exact server URL, so two servers on
one host never share a token. Logins stored by older versions under the bare
hostname are moved over on first use.

Entry points:
- `await stored_token(url)`: a stored token, refreshed if needed, or "" (no
  login: the request goes out anonymously). Never opens a browser.
- `await authenticate(url, challenge)`: after a 401/403; refreshes, or logs in.
- `await ensure_token(url)`: stored token or a fresh login (the `auth` tool).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import ipaddress
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.parse
import weakref
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path

from kitsune_mcp.constants import TIMEOUT_FETCH_URL
from kitsune_mcp.paths import kitsune_home
from kitsune_mcp.utils import _get_http_client, _is_safe_url

_KITSUNE_DIR = kitsune_home() / "oauth"
_CLIENT_NAME = "Kitsune MCP"
_OAUTH_LISTENER_TIMEOUT = 300.0  # 5 minutes
_REFRESH_LEAD_SECONDS = 60
_WELL_KNOWN_PATH = "/.well-known/oauth-authorization-server"
_OIDC_PATH = "/.well-known/openid-configuration"
_PRM_PATH = "/.well-known/oauth-protected-resource"


class NoAuthMetadata(RuntimeError):
    """The server wants authorization but publishes no OAuth metadata."""


@dataclass
class AuthMeta:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    code_challenge_methods_supported: list[str]
    grant_types_supported: list[str]
    token_endpoint_auth_methods_supported: list[str]
    revocation_endpoint: str | None = None


@dataclass
class ClientInfo:
    client_id: str
    redirect_uri: str
    client_secret: str | None = None
    issuer: str | None = None  # authorization server it was registered with


@dataclass
class AuthTarget:
    """Where and how to log in for one MCP server."""

    server_url: str
    resource: str  # RFC 8707 resource indicator: the server's canonical URI
    meta: AuthMeta
    scope: str | None = None


@dataclass
class TokenBundle:
    access_token: str
    expires_at: float
    token_type: str = "Bearer"
    refresh_token: str | None = None
    scope: str | None = None


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def _origin(base_url: str) -> str:
    """Return a filesystem-safe origin identifier for `base_url`."""
    parsed = urllib.parse.urlparse(base_url)
    netloc = parsed.netloc or parsed.path
    return netloc.replace(":", "_")


def _canonical(url: str) -> str:
    """scheme://host[:port]/path, lowercased host, no query, fragment or trailing slash."""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}"


def _store_key(server_url: str) -> str:
    """Storage key for one server URL: readable host plus a hash of the full URL."""
    digest = hashlib.sha256(_canonical(server_url).encode()).hexdigest()[:12]
    return f"{_origin(server_url).lower()}-{digest}"


def _paths(origin: str) -> tuple[Path, Path, Path]:
    base = _KITSUNE_DIR / origin
    return base, base / "client.json", base / "tokens.json"


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# PKCE + state
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _make_state() -> str:
    return secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _meta_from(m: dict) -> AuthMeta | None:
    try:
        return AuthMeta(
            issuer=m["issuer"],
            authorization_endpoint=m["authorization_endpoint"],
            token_endpoint=m["token_endpoint"],
            registration_endpoint=m.get("registration_endpoint"),
            code_challenge_methods_supported=m.get("code_challenge_methods_supported", []),
            grant_types_supported=m.get("grant_types_supported", []),
            token_endpoint_auth_methods_supported=m.get(
                "token_endpoint_auth_methods_supported", []
            ),
            revocation_endpoint=m.get("revocation_endpoint"),
        )
    except (KeyError, TypeError):
        return None


async def _get_json(url: str) -> dict | None:
    """GET a metadata document; None unless it is a 200 with a JSON object."""
    try:
        r = await _get_http_client().get(
            url, headers={"Accept": "application/json"}, timeout=TIMEOUT_FETCH_URL
        )
        if r.status_code != 200:
            return None
        doc = r.json()
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


async def discover(base_url: str) -> AuthMeta | None:
    """Authorization server metadata at the server's own origin (pre-2025-06 servers)."""
    parsed = urllib.parse.urlparse(base_url)
    doc = await _get_json(f"{parsed.scheme}://{parsed.netloc}{_WELL_KNOWN_PATH}")
    return _meta_from(doc) if doc is not None else None


_CHALLENGE_PARAM_RE = re.compile(
    r'([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,]+))'
)


def parse_challenge(header: str | None) -> dict[str, str]:
    """Parameters of the Bearer challenge in a WWW-Authenticate header.

    `Bearer realm="OAuth", resource_metadata="https://…", scope="a b"` →
    {"realm": "OAuth", "resource_metadata": "https://…", "scope": "a b"}.
    Stops at the next challenge scheme if the header carries several.
    """
    if not header:
        return {}
    m = re.search(r"(?i)\bbearer\b", header)
    if not m:
        return {}
    rest = header[m.end() :]
    params: dict[str, str] = {}
    pos = 0
    for pm in _CHALLENGE_PARAM_RE.finditer(rest):
        if rest[pos : pm.start()].strip(" ,\t"):
            break  # a bare token between parameters starts another scheme
        quoted, bare = pm.group(2), pm.group(3)
        value = re.sub(r"\\(.)", r"\1", quoted) if quoted is not None else bare
        params[pm.group(1).lower()] = value
        pos = pm.end()
    return params


def _is_loopback(url: str) -> bool:
    host = urllib.parse.urlsplit(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urllib.parse.urlsplit(a), urllib.parse.urlsplit(b)
    return (pa.scheme.lower(), pa.netloc.lower()) == (pb.scheme.lower(), pb.netloc.lower())


def _may_fetch(url: str, server_url: str) -> bool:
    """Metadata URLs we follow: public HTTPS, the server's own origin, or loopback for a loopback server."""
    if _is_safe_url(url) or _same_origin(url, server_url):
        return True
    return _is_loopback(server_url) and _is_loopback(url)


def _secure_endpoint(url: str) -> bool:
    """OAuth 2.1: endpoints use TLS, except on the loopback interface."""
    scheme = urllib.parse.urlsplit(url).scheme.lower()
    return scheme == "https" or (scheme == "http" and _is_loopback(url))


def _resource_covers(resource: str, server_url: str) -> bool:
    """True if `resource` is the server's URL or a parent path on the same origin."""
    if not _same_origin(resource, server_url):
        return False
    res_path = urllib.parse.urlsplit(resource).path.rstrip("/")
    srv_path = urllib.parse.urlsplit(server_url).path.rstrip("/")
    return srv_path == res_path or srv_path.startswith(res_path + "/")


async def _protected_resource_metadata(server_url: str, challenge: dict[str, str]) -> dict | None:
    """RFC 9728 metadata: the challenge's URL first, then the well-known locations."""
    candidates: list[str] = []
    hinted = challenge.get("resource_metadata")
    if hinted and _may_fetch(hinted, server_url):
        candidates.append(hinted)
    p = urllib.parse.urlsplit(server_url)
    origin = f"{p.scheme}://{p.netloc}"
    path = p.path.rstrip("/")
    if path:
        candidates.append(f"{origin}{_PRM_PATH}{path}")
    candidates.append(f"{origin}{_PRM_PATH}")
    for url in dict.fromkeys(candidates):
        doc = await _get_json(url)
        if doc is not None and isinstance(doc.get("authorization_servers"), list):
            return doc
    return None


def _as_metadata_urls(issuer: str) -> list[str]:
    """Where an issuer's metadata may live (RFC 8414 §3.1, OpenID Connect Discovery)."""
    p = urllib.parse.urlsplit(issuer)
    origin = f"{p.scheme}://{p.netloc}"
    path = p.path.rstrip("/")
    if path:
        return [
            f"{origin}{_WELL_KNOWN_PATH}{path}",
            f"{origin}{_OIDC_PATH}{path}",
            f"{origin}{path}{_OIDC_PATH}",
        ]
    return [f"{origin}{_WELL_KNOWN_PATH}", f"{origin}{_OIDC_PATH}"]


async def _authorization_server(issuer: str, server_url: str) -> AuthMeta | None:
    """Metadata for `issuer`, accepted only if it names that same issuer (mix-up defence)."""
    if not _may_fetch(issuer, server_url) or not _secure_endpoint(issuer):
        return None
    for url in _as_metadata_urls(issuer):
        doc = await _get_json(url)
        if doc is None or str(doc.get("issuer", "")).rstrip("/") != issuer.rstrip("/"):
            continue
        meta = _meta_from(doc)
        if (
            meta
            and _secure_endpoint(meta.authorization_endpoint)
            and _secure_endpoint(meta.token_endpoint)
        ):
            return meta
    return None


async def discover_target(server_url: str, challenge: str | None = None) -> AuthTarget:
    """Work out where to log in for server_url, starting from its 401 challenge."""
    params = parse_challenge(challenge)
    prm = await _protected_resource_metadata(server_url, params)
    if prm is not None:
        resource = prm.get("resource") or _canonical(server_url)
        if not isinstance(resource, str) or not _resource_covers(resource, server_url):
            raise RuntimeError(
                f"The OAuth metadata for {server_url} is for another resource "
                f"({resource!r}); refusing to log in with it."
            )
        scope = params.get("scope") or " ".join(prm.get("scopes_supported") or []) or None
        for issuer in prm["authorization_servers"]:
            if isinstance(issuer, str) and (
                meta := await _authorization_server(issuer, server_url)
            ):
                return AuthTarget(server_url, resource, meta, scope)
        raise RuntimeError(
            f"{server_url} names authorization servers {prm['authorization_servers']}, "
            "but none publishes metadata for its own issuer over a secure connection."
        )
    # Before 2025-06 the MCP server's origin was the authorization server.
    meta = await _get_meta(server_url)
    if meta is None:
        raise NoAuthMetadata(
            f"{server_url} asks for authorization but publishes no OAuth metadata "
            f"({_PRM_PATH} or {_WELL_KNOWN_PATH}). If it expects an API key "
            "header instead, Kitsune cannot send one yet."
        )
    return AuthTarget(server_url, _canonical(server_url), meta, params.get("scope"))


# ---------------------------------------------------------------------------
# Client registration (RFC 7591)
# ---------------------------------------------------------------------------


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _load_client(origin: str) -> ClientInfo | None:
    _, client_path, _ = _paths(origin)
    if not client_path.exists():
        return None
    try:
        data = json.loads(client_path.read_text())
        return ClientInfo(**data)
    except Exception:
        return None


def _save_client(origin: str, client: ClientInfo) -> None:
    _, client_path, _ = _paths(origin)
    _atomic_write_json(client_path, asdict(client))


async def register_client(meta: AuthMeta, origin: str, redirect_uri: str) -> ClientInfo:
    """POST to the registration endpoint (RFC 7591). Falls back to manual if unsupported."""
    if not meta.registration_endpoint:
        raise RuntimeError(
            f"Server {origin} does not support Dynamic Client Registration. "
            "Manual registration is not supported in this version."
        )

    # Prefer token_endpoint_auth_method=none (public client) when supported.
    auth_methods = meta.token_endpoint_auth_methods_supported or ["none"]
    auth_method = "none" if "none" in auth_methods else auth_methods[0]

    body = {
        "client_name": _CLIENT_NAME,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": auth_method,
    }
    r = await _get_http_client().post(
        meta.registration_endpoint,
        json=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=TIMEOUT_FETCH_URL,
    )
    r.raise_for_status()
    data = r.json()
    client = ClientInfo(
        client_id=data["client_id"],
        redirect_uri=redirect_uri,
        client_secret=data.get("client_secret"),
        issuer=meta.issuer,
    )
    _save_client(origin, client)
    return client


# ---------------------------------------------------------------------------
# Loopback callback listener
# ---------------------------------------------------------------------------


class _CallbackState:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None


def _make_handler(state: _CallbackState):
    class _Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_a, **_kw):  # noqa: D401
            pass

        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = dict(urllib.parse.parse_qsl(parsed.query))
            if "error" in params:
                state.error = params.get("error_description") or params["error"]
            else:
                state.code = params.get("code")
                state.state = params.get("state")
            body = (
                b"<html><body style='font-family:sans-serif;text-align:center;"
                b"padding:40px'><h2>You can close this window.</h2>"
                b"<p>Kitsune MCP received the OAuth callback.</p></body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            state.event.set()

    return _Handler


# ---------------------------------------------------------------------------
# Authorization code flow with PKCE
# ---------------------------------------------------------------------------


def _auth_url(
    meta: AuthMeta,
    client: ClientInfo,
    challenge: str,
    state: str,
    *,
    force_login: bool = False,
    resource: str | None = None,
    scope: str | None = None,
) -> str:
    params = {
        "response_type": "code",
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    if resource:
        params["resource"] = resource
    if scope:
        params["scope"] = scope
    if force_login:
        params["prompt"] = "login"
    sep = "&" if "?" in meta.authorization_endpoint else "?"
    return f"{meta.authorization_endpoint}{sep}{urllib.parse.urlencode(params)}"


async def authorize(
    meta: AuthMeta,
    client: ClientInfo,
    force_login: bool = False,
    *,
    resource: str | None = None,
    scope: str | None = None,
) -> TokenBundle:
    """Run the PKCE authorization code flow via loopback. Returns a TokenBundle.

    force_login=True adds `prompt=login` to the auth URL — required after logout
    so the IdP's existing session cookie cannot silently re-issue a code without
    user interaction (OpenID Connect Core 1.0 §3.1.2.1).
    """
    methods = meta.code_challenge_methods_supported or ["S256"]
    if "S256" not in methods:
        raise RuntimeError(f"Server at {meta.issuer} does not advertise PKCE S256 (got {methods})")

    verifier, challenge = _pkce_pair()
    state_value = _make_state()

    # Parse the redirect URI port (client was registered with a specific port).
    port = urllib.parse.urlparse(client.redirect_uri).port
    if port is None:
        raise RuntimeError(f"Cannot parse port from redirect_uri={client.redirect_uri}")

    cb_state = _CallbackState()
    server = http.server.HTTPServer(("127.0.0.1", port), _make_handler(cb_state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        auth_url = _auth_url(
            meta,
            client,
            challenge,
            state_value,
            force_login=force_login,
            resource=resource,
            scope=scope,
        )

        headless = os.environ.get("KITSUNE_NO_BROWSER") == "1"
        opened = False
        if not headless:
            try:
                opened = webbrowser.open(auth_url)
            except Exception:
                opened = False
        if headless or not opened:
            print(
                "🔐 OAuth required. Open this URL in a browser:\n"
                f"   {auth_url}\n"
                f"Kitsune will capture the callback on {client.redirect_uri}\n"
                f"(timeout: {int(_OAUTH_LISTENER_TIMEOUT)}s)",
                file=sys.stderr,  # stdout is the MCP JSON-RPC channel
                flush=True,
            )
        else:
            print(
                f"🔐 Opening browser for OAuth to {urllib.parse.urlparse(meta.issuer).netloc}...",
                file=sys.stderr,  # stdout is the MCP JSON-RPC channel
                flush=True,
            )

        got_callback = await asyncio.to_thread(cb_state.event.wait, _OAUTH_LISTENER_TIMEOUT)
        if not got_callback:
            raise TimeoutError("OAuth callback not received within 5 minutes")
        if cb_state.error:
            raise RuntimeError(f"OAuth error: {cb_state.error}")
        if cb_state.state != state_value:
            raise RuntimeError("OAuth state mismatch (possible CSRF)")
        if not cb_state.code:
            raise RuntimeError("OAuth callback missing authorization code")

        return await _exchange_code(meta, client, cb_state.code, verifier, resource=resource)
    finally:
        server.shutdown()
        server.server_close()


async def _exchange_code(
    meta: AuthMeta,
    client: ClientInfo,
    code: str,
    verifier: str,
    *,
    resource: str | None = None,
) -> TokenBundle:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": client.redirect_uri,
        "client_id": client.client_id,
        "code_verifier": verifier,
    }
    if resource:
        data["resource"] = resource
    if client.client_secret:
        data["client_secret"] = client.client_secret
    r = await _get_http_client().post(
        meta.token_endpoint,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=TIMEOUT_FETCH_URL,
    )
    r.raise_for_status()
    return _bundle_from_response(r.json())


def _bundle_from_response(payload: dict) -> TokenBundle:
    expires_in = int(payload.get("expires_in", 3600))
    return TokenBundle(
        access_token=payload["access_token"],
        expires_at=time.time() + expires_in,
        token_type=payload.get("token_type", "Bearer"),
        refresh_token=payload.get("refresh_token"),
        scope=payload.get("scope"),
    )


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


async def refresh(
    meta: AuthMeta,
    client: ClientInfo,
    bundle: TokenBundle,
    *,
    resource: str | None = None,
) -> TokenBundle:
    if not bundle.refresh_token:
        raise RuntimeError("No refresh_token available")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": bundle.refresh_token,
        "client_id": client.client_id,
    }
    if resource:
        data["resource"] = resource
    if client.client_secret:
        data["client_secret"] = client.client_secret
    r = await _get_http_client().post(
        meta.token_endpoint,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        timeout=TIMEOUT_FETCH_URL,
    )
    if r.status_code == 400:
        try:
            err = r.json().get("error")
        except Exception:
            err = None
        if err in ("invalid_grant", "invalid_token"):
            raise PermissionError("refresh token invalid")
    r.raise_for_status()
    payload = r.json()
    # Some servers don't rotate refresh tokens — preserve the old one.
    if "refresh_token" not in payload and bundle.refresh_token:
        payload["refresh_token"] = bundle.refresh_token
    return _bundle_from_response(payload)


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


def load_tokens(origin: str) -> TokenBundle | None:
    _, _, tok_path = _paths(origin)
    if not tok_path.exists():
        return None
    try:
        return TokenBundle(**json.loads(tok_path.read_text()))
    except Exception:
        return None


def save_tokens(origin: str, bundle: TokenBundle) -> None:
    _, _, tok_path = _paths(origin)
    _atomic_write_json(tok_path, asdict(bundle))


def delete_tokens(origin: str) -> None:
    _, _, tok_path = _paths(origin)
    tok_path.unlink(missing_ok=True)


def _save_target(key: str, target: AuthTarget) -> None:
    base, _, _ = _paths(key)
    _atomic_write_json(
        base / "target.json",
        {
            "server_url": target.server_url,
            "resource": target.resource,
            "scope": target.scope,
            "meta": asdict(target.meta),
        },
    )


def _load_target(key: str) -> AuthTarget | None:
    base, _, _ = _paths(key)
    try:
        data = json.loads((base / "target.json").read_text())
        return AuthTarget(
            server_url=data["server_url"],
            resource=data["resource"],
            meta=AuthMeta(**data["meta"]),
            scope=data.get("scope"),
        )
    except Exception:
        return None


def _migrate_legacy(server_url: str, key: str) -> None:
    """Move a login stored by older versions (keyed by bare hostname) to this URL's key.

    Moved, not copied: a later logout must not bring the old tokens back.
    """
    legacy = _origin(server_url)
    if not legacy or legacy == key:
        return
    _, old_client, old_tokens = _paths(legacy)
    new_base, new_client, new_tokens = _paths(key)
    for old, new in ((old_tokens, new_tokens), (old_client, new_client)):
        if old.exists() and not new.exists():
            new_base.mkdir(parents=True, exist_ok=True)
            os.replace(old, new)


# One lock per stored login, so concurrent calls never refresh (or open a
# browser) twice: a rotated refresh token would invalidate the other caller's.
_token_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]] = (
    weakref.WeakKeyDictionary()
)


def _token_lock(key: str) -> asyncio.Lock:
    per_loop = _token_locks.setdefault(asyncio.get_running_loop(), {})
    return per_loop.setdefault(key, asyncio.Lock())


def _fresh(bundle: TokenBundle) -> bool:
    return bundle.expires_at - time.time() > _REFRESH_LEAD_SECONDS


# Origins whose next ensure_token() must use prompt=login. Set by logout(),
# consumed (and cleared) by the next ensure_token() call. Survives only within
# the process — that's fine because logout + immediate re-auth is the only
# path that exercises it, and re-auth always happens in the same process.
_force_login_origins: set[str] = set()


async def revoke(meta: AuthMeta, client: ClientInfo, bundle: TokenBundle) -> bool:
    """Best-effort RFC 7009 revocation. Returns True if the IdP confirmed revocation.

    Tries the refresh_token first (kills the long-lived credential) then the
    access_token. Failures are swallowed — local deletion is the real source of
    truth; revocation is belt-and-braces for server-side state.
    """
    if not meta.revocation_endpoint:
        return False
    tokens_to_try = [
        ("refresh_token", bundle.refresh_token),
        ("access_token", bundle.access_token),
    ]
    ok = False
    for hint, tok in tokens_to_try:
        if not tok:
            continue
        try:
            r = await _get_http_client().post(
                meta.revocation_endpoint,
                data={
                    "token": tok,
                    "token_type_hint": hint,
                    "client_id": client.client_id,
                },
                timeout=TIMEOUT_FETCH_URL,
            )
            if r.status_code in (200, 204):
                ok = True
        except Exception:
            pass
    return ok


async def logout(base_url: str) -> tuple[bool, bool]:
    """Revoke + delete tokens, and make the next login use prompt=login.

    Returns (revoked_at_idp, deleted_locally). Local deletion is always
    attempted; revocation depends on the IdP advertising a revocation_endpoint.
    """
    key = _store_key(base_url)
    _migrate_legacy(base_url, key)
    revoked = False
    bundle = load_tokens(key)
    if bundle:
        target = _load_target(key)
        meta = target.meta if target else await _get_meta(base_url)
        client = _load_client(key)
        if meta and client:
            revoked = await revoke(meta, client, bundle)
    delete_tokens(key)
    _force_login_origins.add(key)
    return revoked, True


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


# In-memory cache of AuthMeta per base_url to avoid repeated discovery.
_meta_cache: dict[str, AuthMeta] = {}


async def _get_meta(base_url: str) -> AuthMeta | None:
    if base_url in _meta_cache:
        return _meta_cache[base_url]
    meta = await discover(base_url)
    if meta:
        _meta_cache[base_url] = meta
    return meta


async def _refreshed(server_url: str, key: str, bundle: TokenBundle) -> str:
    """Refresh a stored login; "" if that is not possible. Caller holds the lock."""
    client = _load_client(key)
    if not (bundle.refresh_token and client):
        return ""
    target = _load_target(key)
    # Logins moved over from older versions have no target; they came from
    # the server's own origin, so that is where they are refreshed.
    meta = target.meta if target else await _get_meta(server_url)
    if meta is None:
        return ""
    try:
        new_bundle = await refresh(
            meta, client, bundle, resource=target.resource if target else None
        )
    except PermissionError:
        delete_tokens(key)  # refresh token revoked or expired: a new login is needed
        return ""
    except Exception:
        return ""  # transient: keep the tokens and let the caller decide
    save_tokens(key, new_bundle)
    return new_bundle.access_token


async def stored_token(server_url: str) -> str:
    """A stored access token for server_url, refreshed if needed, or "".

    Never opens a browser: "" means the request goes out without credentials,
    and a 401 from the server leads to authenticate().
    """
    key = _store_key(server_url)
    async with _token_lock(key):
        _migrate_legacy(server_url, key)
        bundle = load_tokens(key)
        if bundle is None:
            return ""
        if _fresh(bundle):
            return bundle.access_token
        return await _refreshed(server_url, key, bundle)


async def authenticate(
    server_url: str, challenge: str | None = None, rejected: str | None = None
) -> str:
    """Return a new token after the server refused one (401/403).

    `challenge` is the response's WWW-Authenticate header; `rejected` the token
    that was refused ("" or None when the request was anonymous). Another
    caller's fresh login is reused, then a refresh is tried, then the browser
    login runs. An `insufficient_scope` challenge skips the refresh: only a new
    login can grant more scope.
    """
    key = _store_key(server_url)
    params = parse_challenge(challenge)
    async with _token_lock(key):
        _migrate_legacy(server_url, key)
        bundle = load_tokens(key)
        if bundle and bundle.access_token != rejected and _fresh(bundle):
            return bundle.access_token
        step_up = params.get("error") == "insufficient_scope"
        if bundle and not step_up and key not in _force_login_origins:
            token = await _refreshed(server_url, key, bundle)
            if token and token != rejected:
                return token
        delete_tokens(key)

        target = await discover_target(server_url, challenge)
        _save_target(key, target)
        client = _load_client(key)
        legacy_client = client is not None and client.issuer is None
        if client is None or (
            client.issuer != target.meta.issuer
            and not (legacy_client and _same_origin(target.meta.issuer, server_url))
        ):
            port = _pick_free_port()
            client = await register_client(target.meta, key, f"http://127.0.0.1:{port}/callback")

        force_login = key in _force_login_origins
        _force_login_origins.discard(key)
        new_bundle = await authorize(
            target.meta,
            client,
            force_login=force_login,
            resource=target.resource,
            scope=target.scope,
        )
        save_tokens(key, new_bundle)
        return new_bundle.access_token


async def ensure_token(base_url: str) -> str:
    """A token for base_url: the stored one (refreshed if needed) or a fresh login."""
    return await stored_token(base_url) or await authenticate(base_url)
