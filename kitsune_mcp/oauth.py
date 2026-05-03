"""OAuth 2.1 client for MCP servers advertising `.well-known/oauth-authorization-server`.

Implements the subset of OAuth 2.1 required by the MCP spec: PKCE S256,
Dynamic Client Registration (RFC 7591), authorization_code + refresh_token grants.

Tokens and client registrations are persisted to `~/.kitsune/oauth/<origin>/`
with mode 0600, keyed by the OAuth server's origin (netloc of the issuer URL).

Public entry point: `await ensure_token(base_url)` → access_token string.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path

from kitsune_mcp.constants import TIMEOUT_FETCH_URL
from kitsune_mcp.utils import _get_http_client

_KITSUNE_DIR = Path.home() / ".kitsune" / "oauth"
_CLIENT_NAME = "Kitsune MCP"
_OAUTH_LISTENER_TIMEOUT = 300.0  # 5 minutes
_REFRESH_LEAD_SECONDS = 60
_WELL_KNOWN_PATH = "/.well-known/oauth-authorization-server"


@dataclass
class AuthMeta:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None
    code_challenge_methods_supported: list[str]
    grant_types_supported: list[str]
    token_endpoint_auth_methods_supported: list[str]


@dataclass
class ClientInfo:
    client_id: str
    redirect_uri: str
    client_secret: str | None = None


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


async def discover(base_url: str) -> AuthMeta | None:
    """Fetch and parse the OAuth authorization server metadata. Returns None if absent."""
    parsed = urllib.parse.urlparse(base_url)
    well_known = f"{parsed.scheme}://{parsed.netloc}{_WELL_KNOWN_PATH}"
    try:
        r = await _get_http_client().get(well_known, timeout=TIMEOUT_FETCH_URL)
        if r.status_code != 200:
            return None
        m = r.json()
    except Exception:
        return None
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
        )
    except KeyError:
        return None


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


async def authorize(meta: AuthMeta, client: ClientInfo) -> TokenBundle:
    """Run the PKCE authorization code flow via loopback. Returns a TokenBundle."""
    methods = meta.code_challenge_methods_supported or ["S256"]
    if "S256" not in methods:
        raise RuntimeError(
            f"Server at {meta.issuer} does not advertise PKCE S256 "
            f"(got {methods})"
        )

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
        auth_params = {
            "response_type": "code",
            "client_id": client.client_id,
            "redirect_uri": client.redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state_value,
        }
        auth_url = f"{meta.authorization_endpoint}?{urllib.parse.urlencode(auth_params)}"

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
                flush=True,
            )
        else:
            print(
                f"🔐 Opening browser for OAuth to {urllib.parse.urlparse(meta.issuer).netloc}...",
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

        return await _exchange_code(meta, client, cb_state.code, verifier)
    finally:
        server.shutdown()
        server.server_close()


async def _exchange_code(
    meta: AuthMeta, client: ClientInfo, code: str, verifier: str
) -> TokenBundle:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": client.redirect_uri,
        "client_id": client.client_id,
        "code_verifier": verifier,
    }
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


async def refresh(meta: AuthMeta, client: ClientInfo, bundle: TokenBundle) -> TokenBundle:
    if not bundle.refresh_token:
        raise RuntimeError("No refresh_token available")
    data = {
        "grant_type": "refresh_token",
        "refresh_token": bundle.refresh_token,
        "client_id": client.client_id,
    }
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


# ---------------------------------------------------------------------------
# Public entry point
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


async def ensure_token(base_url: str) -> str:
    """Return a valid access token for `base_url`, running the full flow as needed.

    Order of operations:
    1. Discover `.well-known` metadata (raises if absent).
    2. Load cached token; return if still valid.
    3. If expired and refresh_token exists, refresh; on invalid_grant fall through.
    4. Load or register a client via DCR.
    5. Run the authorization code + PKCE flow.
    """
    meta = await _get_meta(base_url)
    if meta is None:
        raise RuntimeError(
            f"No OAuth metadata at {base_url}{_WELL_KNOWN_PATH} — "
            "server does not advertise OAuth 2.1 support."
        )
    origin = _origin(base_url)

    bundle = load_tokens(origin)
    if bundle and bundle.expires_at - time.time() > _REFRESH_LEAD_SECONDS:
        return bundle.access_token

    client = _load_client(origin)

    if bundle and bundle.refresh_token and client:
        try:
            new_bundle = await refresh(meta, client, bundle)
            save_tokens(origin, new_bundle)
            return new_bundle.access_token
        except PermissionError:
            delete_tokens(origin)
            # Fall through to re-auth.
        except Exception:
            # Network error or malformed response — try full re-auth.
            delete_tokens(origin)

    if client is None:
        port = _pick_free_port()
        redirect_uri = f"http://127.0.0.1:{port}/callback"
        client = await register_client(meta, origin, redirect_uri)

    new_bundle = await authorize(meta, client)
    save_tokens(origin, new_bundle)
    return new_bundle.access_token
