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
from html.parser import HTMLParser
from urllib.parse import urlparse

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
            return addr.is_global
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
    """True if the URL's hostname resolves to any non-public address.

    Closes the gap where internal DNS names pass _is_safe_url. A rebinding
    resolver can still answer differently at connect time; this check makes
    the common case (an internal name) fail closed.
    """
    host = (urlparse(url).hostname or "").rstrip(".")
    if not host or _literal_ip(host) is not None:
        return False  # literal IPs are fully judged by _is_safe_url
    for ip in await _resolve_host(host):
        try:
            if not ipaddress.ip_address(ip.split("%", 1)[0]).is_global:
                return True
        except ValueError:
            return True
    return False


# Sent only to the origin they were meant for; dropped when a redirect leaves it.
_CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


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
) -> httpx.Response:
    """HTTP request that validates every redirect hop against _is_safe_url.

    Raises ValueError if any redirect target is a private/loopback address,
    unless KITSUNE_ALLOW_LOCAL_FETCH=1 is set. Handles POST→GET method
    downgrade on 301/302/303 per RFC 9110.
    """
    client = _get_http_client()
    kw: dict = {"headers": headers or {}, "timeout": timeout}
    if params is not None:
        kw["params"] = params
    if json_body is not None:
        kw["content"] = json.dumps(json_body).encode()
        kw["headers"] = {**kw["headers"], "Content-Type": "application/json"}

    allow_local = bool(os.getenv("KITSUNE_ALLOW_LOCAL_FETCH"))
    for _ in range(10):
        if not allow_local and await _resolves_private(url):
            raise ValueError(
                f"Blocked: '{url}' resolves to a private/loopback address. "
                "Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow."
            )
        r = await client.request(method, url, follow_redirects=False, **kw)
        if not r.is_redirect:
            return r
        next_req = r.next_request
        if next_req is None:
            return r
        next_url = str(next_req.url)
        if not _is_safe_url(next_url) and not allow_local:
            raise ValueError(
                f"Blocked: redirect to '{next_url}' resolves to a private/loopback address. "
                "Set KITSUNE_ALLOW_LOCAL_FETCH=1 to allow."
            )
        if _origin(next_url) != _origin(url):
            # Never hand a token or session cookie to a different origin.
            kw["headers"] = {
                k: v for k, v in kw["headers"].items() if k.lower() not in _CREDENTIAL_HEADERS
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
