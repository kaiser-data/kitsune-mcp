import asyncio
import ipaddress
import json
import logging
import os

# Suppress httpx/httpcore per-request INFO lines that flood the console during
# registry work. Set KITSUNE_DEBUG_HTTP=1 to re-enable them for debugging.
import os as _os
import re
import shutil
import socket
import subprocess
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpcore
import httpx

from kitsune_mcp.constants import MAX_RESPONSE_TOKENS

_http_log_level = logging.DEBUG if _os.getenv("KITSUNE_DEBUG_HTTP") else logging.WARNING
logging.getLogger("httpx").setLevel(_http_log_level)
logging.getLogger("httpcore").setLevel(_http_log_level)

# ---------------------------------------------------------------------------
# Shared HTTP client — reused across registry lookups, URL fetch
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return the process-wide shared AsyncClient, creating it on first call."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(follow_redirects=True)
    return _http_client


class _PublicOnlyBackend(httpcore.AsyncNetworkBackend):
    """httpcore network backend that connects only to public addresses it checked itself.

    The SSRF pre-check resolves a hostname, and the connection used to resolve
    it again: a rebinding resolver could answer public the first time and
    private the second. Here the connect-time lookup *is* the check: every
    address must be public, and the socket goes to one of those addresses.
    TLS still verifies the hostname, because httpcore passes the request's
    host as the SNI/verification name separately from the connect address.

    Not pinned: KITSUNE_ALLOW_LOCAL_FETCH=1 (local targets allowed on purpose)
    and the configured proxy host (the proxy resolves the target, so the
    pre-check is all that applies there).
    """

    def __init__(self, inner: httpcore.AsyncNetworkBackend) -> None:
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ) -> httpcore.AsyncNetworkStream:
        if not os.getenv("KITSUNE_ALLOW_LOCAL_FETCH") and host.lower() not in _proxy_hosts():
            host = await _checked_public_address(host)
        return await self._inner.connect_tcp(
            host, port, timeout=timeout, local_address=local_address, socket_options=socket_options
        )

    async def connect_unix_socket(self, path: str, timeout=None, socket_options=None):
        raise httpcore.ConnectError("unix sockets are not reachable through guarded requests")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _proxy_hosts() -> set[str]:
    hosts = set()
    for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
        value = os.environ.get(var)
        if value:
            host = urlparse(value if "://" in value else f"http://{value}").hostname
            if host:
                hosts.add(host.lower())
    return hosts


async def _checked_public_address(host: str) -> str:
    """One public address for host (resolving it once), or httpcore.ConnectError."""
    bare = host.strip("[]").rstrip(".")
    literal = _literal_ip(bare)
    if literal is not None:
        if _is_public_ip(literal):
            return str(literal)
        raise httpcore.ConnectError(f"{host} is not a public address")
    ips = await _resolve_host(bare)
    if not ips:
        raise httpcore.ConnectError(f"{host} does not resolve (not a public address)")
    for ip in ips:
        try:
            addr = ipaddress.ip_address(ip.split("%", 1)[0])
        except ValueError:
            raise httpcore.ConnectError(
                f"{host} resolved to {ip!r}: not a public address"
            ) from None
        if not _is_public_ip(addr):
            raise httpcore.ConnectError(f"{host} resolved to {ip}: not a public address")
    return ips[0]


_guarded_client: httpx.AsyncClient | None = None


def _get_guarded_client() -> httpx.AsyncClient:
    """Shared client for SSRF-guarded requests: connections pinned to checked addresses.

    Redirects are off; callers walk them hop by hop (_ssrf_safe_request, OAuth
    metadata). Everything else (registries, MCP servers, which may be local on
    purpose) keeps using _get_http_client().
    """
    global _guarded_client
    if _guarded_client is None or _guarded_client.is_closed:
        transport = httpx.AsyncHTTPTransport()
        pool = transport._pool
        pool._network_backend = _PublicOnlyBackend(pool._network_backend)
        _guarded_client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    return _guarded_client


def _literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a host string denotes on its own, without DNS.

    Besides dotted quads this catches the legacy IPv4 spellings that resolvers
    still accept: 127.1, 2130706433, 0x7f.0.0.1 all mean 127.0.0.1.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except (OSError, ValueError):
        return None


def _is_public_ip(addr) -> bool:
    """Globally routable unicast. `is_global` alone admits multicast (224.0.0.0/4)."""
    return addr.is_global and not addr.is_multicast


def _is_safe_url(url: str) -> bool:
    """Return True only for public HTTPS URLs — blocks SSRF to private/loopback addresses.

    Static check only; hostnames are resolved per request in _ssrf_safe_request.
    """
    try:
        p = urlparse(url)
        if p.scheme != "https":
            return False
        host = (p.hostname or "").rstrip(".").lower()
        if not host or host == "localhost" or host.endswith(".localhost"):
            return False
        addr = _literal_ip(host)
        if addr is not None:
            return _is_public_ip(addr)
        return True
    except Exception:
        return False


async def _resolve_host(host: str) -> list[str]:
    """IP addresses a hostname resolves to ([] if it does not resolve)."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        return []
    return [str(info[4][0]) for info in infos]


async def _resolves_private(url: str) -> bool:
    """True if the URL's hostname resolves to any non-public address, or to none.

    Closes the gap where internal DNS names pass _is_safe_url. A name that does
    not resolve now counts as unsafe too: the connection would resolve it
    again, and a rebinding resolver can fail the check's lookup and answer the
    connection's with a private address. (A resolver can still answer the two
    lookups differently; binding the connection to the checked addresses would
    close that, and is not done here.)
    """
    host = (urlparse(url).hostname or "").rstrip(".")
    if not host or _literal_ip(host) is not None:
        return False  # literal IPs are fully judged by _is_safe_url
    ips = await _resolve_host(host)
    if not ips:
        return True
    for ip in ips:
        try:
            if not _is_public_ip(ipaddress.ip_address(ip.split("%", 1)[0])):
                return True
        except ValueError:
            return True
    return False


# Sent only to the origin they were meant for; dropped when a redirect leaves it.
_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
# The only headers that may follow a redirect to another origin. Any other
# header may carry a secret (X-API-Key, Api-Token, vendor-specific names), and
# there is no way to tell, so it stays with the origin it was meant for.
_CROSS_ORIGIN_SAFE_HEADERS = frozenset(
    {"accept", "accept-language", "content-type", "user-agent", "cache-control"}
)


def _origin(url: str) -> tuple[str, str, int | None]:
    p = urlparse(url)
    return (p.scheme.lower(), (p.hostname or "").lower(), p.port)


async def _ssrf_safe_request(
    method: str,
    url: str,
    *,
    params=None,
    json_body=None,
    headers: dict | None = None,
    timeout: float = 30.0,
    before_redirect: Callable[[str], Awaitable[str | None]] | None = None,
) -> httpx.Response:
    """HTTP request that validates every redirect hop against _is_safe_url.

    *before_redirect* (optional) is awaited with each redirect target before it
    is requested; a returned string refuses the hop with that message (the
    guard's network policy uses it). `params` go to the first URL only: a
    redirect target carries its own query.

    Raises ValueError if any redirect target is a private/loopback address,
    unless KITSUNE_ALLOW_LOCAL_FETCH=1 is set. Handles POST→GET method
    downgrade on 301/302/303 per RFC 9110.
    """
    client = _get_guarded_client()
    kw: dict = {"headers": headers or {}, "timeout": timeout}
    if params is not None:
        kw["params"] = params
    if json_body is not None:
        kw["content"] = json.dumps(json_body).encode()
        kw["headers"] = {**kw["headers"], "Content-Type": "application/json"}

    allow_local = bool(os.getenv("KITSUNE_ALLOW_LOCAL_FETCH"))
    for _ in range(10):
        if not allow_local and (not _is_safe_url(url) or await _resolves_private(url)):
            raise ValueError(
                f"Blocked: '{url}' resolves to a private address, or does not resolve. "
                "Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow."
            )
        r = await client.request(method, url, follow_redirects=False, **kw)
        kw.pop("params", None)
        if not r.is_redirect:
            return r
        next_req = r.next_request
        if next_req is None:
            return r
        next_url = str(next_req.url)
        if not _is_safe_url(next_url) and not allow_local:
            raise ValueError(
                f"Blocked: redirect to '{next_url}' is a private/loopback address. "
                "Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow."
            )
        if before_redirect is not None:
            refusal = await before_redirect(next_url)
            if refusal:
                raise ValueError(refusal)
        downgrade = r.status_code in (301, 302, 303) and method.upper() in ("POST", "PUT", "PATCH")
        if _origin(next_url) != _origin(url) and "content" in kw and not downgrade:
            # 307/308 keep the method and body: the body was meant for this
            # origin only (tool arguments, secrets), so it is never replayed.
            raise ValueError(
                f"Blocked: {r.status_code} redirect would resend the request body to "
                f"another origin ({_origin(next_url)[1]})."
            )
        if _origin(next_url) != _origin(url):
            # Never hand a token, session cookie or API-key header to a
            # different origin.
            kw["headers"] = {
                k: v for k, v in kw["headers"].items() if k.lower() in _CROSS_ORIGIN_SAFE_HEADERS
            }
        url = next_url
        # RFC 9110: 301/302/303 downgrades non-GET to GET
        if r.status_code in (301, 302, 303) and method.upper() in ("POST", "PUT", "PATCH"):
            method = "GET"
            kw.pop("content", None)
            kw["headers"] = {k: v for k, v in kw["headers"].items() if k != "Content-Type"}

    raise ValueError("SSRF guard: exceeded 10 redirects")


def _estimate_tokens(text) -> int:
    if isinstance(text, list):
        return sum(len(json.dumps(t)) for t in text) // 4
    return len(str(text)) // 4


def _truncate(text: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n[...truncated at ~{max_tokens} tokens]"


def _clean_response(text: str) -> str:
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # strip markdown links, keep label
    text = re.sub(r"!\[[^\]]*\]", "", text)  # strip images
    text = re.sub(r"\n{3,}", "\n\n", text)  # collapse blank lines
    text = re.sub(r"[ \t]{2,}", " ", text)  # collapse spaces
    return text.strip()


def _clean_truncate(text: str, max_tokens: int = MAX_RESPONSE_TOKENS) -> str:
    """_truncate(_clean_response(text)) without regex passes over megabytes we drop anyway."""
    max_chars = max_tokens * 4
    cap = max_chars * 8  # headroom for what cleaning collapses
    if len(text) <= cap:
        return _truncate(_clean_response(text), max_tokens)
    cleaned = _clean_response(text[:cap])
    return cleaned[:max_chars] + f"\n[...truncated at ~{max_tokens} tokens]"


class _TextExtractor(HTMLParser):
    """Visible text of an HTML document: script and style contents dropped, entities decoded.

    html.parser follows the HTML rules for where a script ends (`</script >`,
    `</SCRIPT foo>`…), which a regex does not (CodeQL py/bad-tag-filter).
    """

    _SKIP = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        else:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skipping = max(0, self._skipping - 1)
        else:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def _strip_html(text: str) -> str:
    parser = _TextExtractor()
    parser.feed(text)
    parser.close()
    return _clean_response("".join(parser.parts).replace("\xa0", " "))


def _extract_content(result: dict) -> str:
    content = result.get("content", [])
    if content:
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(text_parts) if text_parts else json.dumps(content, indent=2)
    return json.dumps(result, indent=2)


def _rss_mb(pid: int | None) -> str:
    """Return resident memory of a process as a human-readable string, or '' on failure."""
    if pid is None:
        return ""
    try:
        # Linux: read /proc/<pid>/status
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    kb = int(line.split()[1])
                    return f"{kb // 1024}MB"
    except OSError:
        pass
    try:
        # macOS / BSD: use ps (no shell — pid passed as argv)
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
        if out:
            return f"{int(out) // 1024}MB"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return ""


async def _try_axonmcp(url: str, intent: str) -> str | None:
    axon = shutil.which("axon-mcp")
    if not axon:
        return None
    try:
        cmd = [axon, "browse", url]
        if intent:
            cmd += ["--intent", intent]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=20.0)
        result = stdout.decode().strip()
        return result if result else None
    except Exception:
        return None
