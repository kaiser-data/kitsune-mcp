"""Action guard — a policy check in front of every downstream tool call.

Trust tiers, the Docker cage and TOFU pins defend against bad *servers*. The
guard defends against bad *calls* to good servers: a prompt-injected agent
asking the official GitHub or filesystem server to push or read something it
shouldn't. It is off unless ~/.kitsune/policy.json exists.

Stage 1 (this module) decides everything code can decide: tool allow/ask/deny
rules, path roots, a host allowlist and opaque encoded payloads. What it can't
decide (free-text commands, tools no rule covers) comes out as "classify";
until a classifier backend lands, that is handled like "ask". "ask" goes to the
human through MCP elicitation, never through an argument the agent could set.

`mode: "monitor"` (the default) evaluates and logs every call but never blocks.

Design and evidence: docs/superpowers/specs/2026-09-26-action-guard-design.md
"""

from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import json
import math
import os
import re
import time
from collections import Counter
from dataclasses import dataclass

from kitsune_mcp.paths import kitsune_home

POLICY_VERSION = 1
MODES = ("monitor", "enforce")
DEFAULTS = ("allow", "classify", "ask", "deny")
_TOP_KEYS = {"version", "mode", "task", "default", "network", "paths", "servers"}
_LATER_KEYS = {"backend", "bands", "on_backend_error"}  # classifier stage, not read yet
_SERVER_KEYS = {"allow", "ask", "deny", "free_text_args"}
DEFAULT_FREE_TEXT_ARGS = ("command", "cmd", "script", "code", "query", "sql")

# Always denied, whatever the policy says (credential stores + Kitsune's own
# state, so a filesystem server can't rewrite the policy, pins or tokens).
BUILTIN_DENY_PATHS = (
    "~/.ssh",
    "~/.aws",
    "~/.config/gcloud",
    "~/.kube",
    "~/.docker/config.json",
    "~/.netrc",
    "/var/run/secrets",
    "/run/secrets",
)

_READ_VERBS = {"read", "get", "list", "search", "find", "view", "show", "describe", "stat", "cat"}
_WRITE_VERBS = {
    "write",
    "create",
    "edit",
    "update",
    "delete",
    "remove",
    "move",
    "rename",
    "put",
    "post",
    "push",
    "set",
    "apply",
    "exec",
    "execute",
    "run",
    "upload",
    "append",
    "patch",
    "insert",
    "drop",
}
_PATH_KEY_HINTS = ("path", "file", "dir", "folder", "cwd", "dest", "root")
_FILE_EXTS = {
    "txt", "json", "py", "js", "ts", "md", "yaml", "yml", "toml", "csv", "log", "sh", "html",
    "xml", "lock", "cfg", "ini", "conf", "tar", "gz", "tgz", "zip", "whl", "pem", "key", "out",
}  # fmt: skip

_URL_HOST = re.compile(r"\b(?:https?|wss?|ftp)://(?:[^@/\s]+@)?([^/:\s\"'<>?#]+)", re.I)
_SSH_HOST = re.compile(r"\b[\w.-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,}|\d{1,3}(?:\.\d{1,3}){3}):")
_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")
_NET_CMD_HOST = re.compile(
    r"\b(?:curl|wget|ssh|scp|nc|ncat|telnet|nmap|nikto|dirb|gobuster|ffuf|wpscan|sqlmap|hydra|ping)\b"
    r"[^\n|;&]*?\s(?:[\w.-]+@)?([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})(?=[\s/:]|$)"
)
_FREE_TEXT_PATH = re.compile(r"(?:^|[\s'\"=(<>])((?:~/|/)[^\s'\"<>|;&)]*)")
_B64_RUN = re.compile(r"[A-Za-z0-9+/_-]{120,}={0,2}")
_HEX_RUN = re.compile(r"\b[0-9a-fA-F]{120,}\b")
_OPAQUE_MAGIC = (
    b"\x1f\x8b",
    b"\x78\x01",
    b"\x78\x5e",
    b"\x78\x9c",
    b"\x78\xda",
    b"BZh",
    b"\xfd7zXZ",
)


class PolicyError(ValueError):
    """policy.json is present but unusable — the guard then fails closed."""


@dataclass(frozen=True)
class Policy:
    mode: str
    default: str
    task: str
    network_allow: tuple[str, ...] | None
    read_roots: tuple[str, ...] | None
    write_roots: tuple[str, ...] | None
    deny_paths: tuple[str, ...]
    servers: dict
    digest: str


@dataclass(frozen=True)
class Verdict:
    action: str  # "allow" | "block" | "ask" | "classify"
    stage: str  # "rule" | "path" | "host" | "blob" | "default" | "policy"
    reason: str


# ─── policy file ──────────────────────────────────────────────────────────────


def policy_path():
    return kitsune_home() / "policy.json"


def _str_list(value, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise PolicyError(f"{where} must be a list of strings")
    return tuple(value)


def _roots(paths: dict, key: str) -> tuple[str, ...] | None:
    if key not in paths:
        return None
    return tuple(_norm(p) for p in _str_list(paths[key], f"paths.{key}"))


def parse_policy(data) -> Policy:
    if not isinstance(data, dict):
        raise PolicyError("policy must be a JSON object")
    if data.get("version") != POLICY_VERSION:
        raise PolicyError(f"version must be {POLICY_VERSION}")
    unknown = set(data) - _TOP_KEYS - _LATER_KEYS
    if unknown:
        raise PolicyError(f"unknown keys: {', '.join(sorted(unknown))}")
    mode = data.get("mode", "monitor")
    if mode not in MODES:
        raise PolicyError(f"mode must be one of {MODES}")
    default = data.get("default", "classify")
    if default not in DEFAULTS:
        raise PolicyError(f"default must be one of {DEFAULTS}")

    network = data.get("network", {})
    if not isinstance(network, dict) or set(network) - {"allow"}:
        raise PolicyError('network must be {"allow": [...]}')
    network_allow = _str_list(network["allow"], "network.allow") if "allow" in network else None

    paths = data.get("paths", {})
    if not isinstance(paths, dict) or set(paths) - {"read", "write", "deny"}:
        raise PolicyError('paths takes only "read", "write" and "deny"')
    deny = _str_list(paths.get("deny", []), "paths.deny")

    servers = data.get("servers", {})
    if not isinstance(servers, dict):
        raise PolicyError("servers must be an object")
    for name, rules in servers.items():
        if not isinstance(rules, dict) or set(rules) - _SERVER_KEYS:
            raise PolicyError(f"servers.{name} takes only {sorted(_SERVER_KEYS)}")
        for key, value in rules.items():
            _str_list(value, f"servers.{name}.{key}")

    return Policy(
        mode=mode,
        default=default,
        task=str(data.get("task", "")),
        network_allow=network_allow,
        read_roots=_roots(paths, "read"),
        write_roots=_roots(paths, "write"),
        deny_paths=deny,
        servers=servers,
        digest=hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12],
    )


_policy_cache: dict = {}


def load_policy() -> Policy | PolicyError | None:
    """None when no policy file exists (guard off). Re-read when the file changes."""
    path = policy_path()
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    except OSError as e:
        return PolicyError(str(e))
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _policy_cache:
        try:
            result: Policy | PolicyError = parse_policy(json.loads(path.read_text()))
        except PolicyError as e:
            result = e
        except (OSError, ValueError) as e:
            result = PolicyError(f"unreadable policy file: {e}")
        _policy_cache.clear()
        _policy_cache[key] = result
    return _policy_cache[key]


# ─── stage 1: resolution ──────────────────────────────────────────────────────


def _norm(path: str) -> str:
    return os.path.realpath(os.path.expanduser(path))


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _strings(obj, key: str = ""):
    """Yield (key, string) for every string in a nested argument structure."""
    if isinstance(obj, str):
        yield key, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, str(k))
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _strings(v, key)


def _tool_rule(policy: Policy, server_id: str, tool: str) -> str | None:
    for scope in (server_id, "*"):
        rules = policy.servers.get(scope)
        if not rules:
            continue
        for action in ("deny", "ask", "allow"):
            if any(fnmatch.fnmatchcase(tool, pat) for pat in rules.get(action, ())):
                return action
    return None


def _free_text_keys(policy: Policy, server_id: str) -> set[str]:
    keys: set[str] = set()
    for scope in (server_id, "*"):
        keys.update((policy.servers.get(scope) or {}).get("free_text_args", ()))
    return keys or set(DEFAULT_FREE_TEXT_ARGS)


def _access(tool: str) -> str:
    """'read' only when the tool name has a read verb and no write verb."""
    words = set(re.split(r"[_\-.\s]+|(?<=[a-z])(?=[A-Z])", tool.lower()))
    return "read" if words & _READ_VERBS and not words & _WRITE_VERBS else "write"


def _paths(args: dict, free_keys: set[str]) -> list[str]:
    found = []
    for key, value in _strings(args):
        lower = key.lower()
        if lower in free_keys:
            text = _URL_HOST.sub(" ", value)
            found += [m.group(1) for m in _FREE_TEXT_PATH.finditer(text)]
        elif any(h in lower for h in _PATH_KEY_HINTS) and value and "://" not in value:
            found.append(value)
    return [_norm(p) for p in found if p.strip()]


def _path_denied(path: str, policy: Policy) -> bool:
    name = os.path.basename(path)
    if name == ".env" or name.startswith(".env."):
        return True
    if _under(path, _norm(str(kitsune_home()))):
        return True
    for entry in (*BUILTIN_DENY_PATHS, *policy.deny_paths):
        if any(c in entry for c in "*?["):
            if fnmatch.fnmatch(path, os.path.expanduser(entry)):
                return True
        elif _under(path, _norm(entry)):
            return True
    return False


def _hosts(args: dict, free_keys: set[str]) -> set[str]:
    hosts: set[str] = set()
    for key, value in _strings(args):
        hosts.update(m.lower() for m in _URL_HOST.findall(value))
        if key.lower() in free_keys:
            hosts.update(m.lower() for m in _SSH_HOST.findall(value))
            hosts.update(_IP.findall(value))
            hosts.update(m.lower() for m in _NET_CMD_HOST.findall(value))
    return {h.rstrip(".") for h in hosts if h.rsplit(".", 1)[-1].lower() not in _FILE_EXTS}


def _host_allowed(host: str, allow: tuple[str, ...]) -> bool:
    for pat in allow:
        pat = pat.lower()
        if host == pat or fnmatch.fnmatchcase(host, pat):
            return True
        if pat.startswith("*.") and host == pat[2:]:
            return True
    return False


def _entropy(s: str) -> float:
    counts = Counter(s)
    return -sum(c / len(s) * math.log2(c / len(s)) for c in counts.values())


def _is_opaque(raw: bytes) -> bool:
    if raw.startswith(_OPAQUE_MAGIC):
        return True
    printable = sum(32 <= b < 127 or b in (9, 10, 13) for b in raw)
    return printable / max(1, len(raw)) < 0.9


def _opaque_blob(args: dict) -> bool:
    """Encoded payloads a classifier can't read (compressed, then base64/hex)
    go to the human instead."""
    for _, value in _strings(args):
        for m in _HEX_RUN.finditer(value):
            if len(m.group()) % 2 == 0 and _is_opaque(bytes.fromhex(m.group())):
                return True
        for m in _B64_RUN.finditer(value):
            token = m.group()
            if _entropy(token) < 4.8:  # paths and identifiers, not encoded data
                continue
            for decode in (base64.b64decode, base64.urlsafe_b64decode):
                try:
                    raw = decode(token + "=" * (-len(token) % 4))
                except (binascii.Error, ValueError):
                    continue
                if _is_opaque(raw):
                    return True
                break
    return False


def evaluate(policy: Policy, server_id: str, tool: str, args: dict) -> Verdict:
    """Stage 1: every decision the policy settles without a classifier."""
    rule = _tool_rule(policy, server_id, tool)
    if rule == "deny":
        return Verdict("block", "rule", f"tool {tool!r} is denied by policy")

    free_keys = {k.lower() for k in _free_text_keys(policy, server_id)}
    access = _access(tool)
    for path in _paths(args, free_keys):
        if _path_denied(path, policy):
            return Verdict("block", "path", f"{path} is a protected path")
        writable = policy.write_roots is None or any(_under(path, r) for r in policy.write_roots)
        if access == "write" and not writable:
            return Verdict("block", "path", f"{path} is outside the write roots")
        if access == "read" and (policy.read_roots is not None or policy.write_roots is not None):
            roots = (*(policy.read_roots or ()), *(policy.write_roots or ()))
            if not any(_under(path, r) for r in roots):
                return Verdict("block", "path", f"{path} is outside the read roots")

    if policy.network_allow is not None:
        for host in sorted(_hosts(args, free_keys)):
            if not _host_allowed(host, policy.network_allow):
                return Verdict("block", "host", f"host {host} is not in network.allow")

    if _opaque_blob(args):
        return Verdict("ask", "blob", "arguments contain an opaque encoded payload")
    if rule == "ask":
        return Verdict("ask", "rule", f"policy asks before {tool!r}")

    has_free_text = any(k.lower() in free_keys and v.strip() for k, v in _strings(args))
    if rule == "allow":
        if has_free_text:
            return Verdict("classify", "rule", "allowed tool with free-text arguments")
        return Verdict("allow", "rule", f"tool {tool!r} is allowed by policy")

    action = {"deny": "block"}.get(policy.default, policy.default)
    return Verdict(action, "default", f"no rule covers {tool!r} (default: {policy.default})")


# ─── enforcement ──────────────────────────────────────────────────────────────

counts: Counter = Counter()


def _log(server_id: str, tool: str, args: dict, verdict: Verdict, mode: str, outcome: str):
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": mode,
        "server": server_id,
        "tool": tool,
        "stage": verdict.stage,
        "verdict": verdict.action,
        "reason": verdict.reason,
        "args_sha256": hashlib.sha256(
            json.dumps(args, sort_keys=True, default=str).encode()
        ).hexdigest(),
        "outcome": outcome,
    }
    counts[outcome] += 1
    path = kitsune_home() / "guard.log.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass


async def _ask_human(server_id: str, tool: str, args: dict, verdict: Verdict) -> bool:
    """Out-of-band approval via MCP elicitation. Anything but an explicit yes is a no,
    including clients that don't support elicitation."""
    from pydantic import BaseModel, Field

    from kitsune_mcp.app import mcp

    class Approve(BaseModel):
        approve: bool = Field(description="Run this tool call?")

    preview = json.dumps(args, default=str)
    if len(preview) > 500:
        preview = preview[:500] + "…"
    message = (
        f"Kitsune guard: run {tool} on {server_id}?\n"
        f"Reason for asking: {verdict.reason}\n"
        f"Arguments: {preview}"
    )
    try:
        result = await mcp.get_context().elicit(message=message, schema=Approve)
    except Exception:
        return False
    return result.action == "accept" and bool(getattr(result.data, "approve", False))


async def guard_call(server_id: str, tool: str, args: dict) -> str | None:
    """Check one downstream call. Returns None to proceed, or a message to return
    to the agent instead of executing."""
    policy = load_policy()
    if policy is None:
        return None
    if isinstance(policy, PolicyError):
        mode, verdict = "enforce", Verdict("ask", "policy", f"policy file is invalid ({policy})")
    else:
        mode, verdict = policy.mode, evaluate(policy, server_id, tool, args or {})
        if verdict.action == "classify":
            verdict = Verdict("ask", verdict.stage, verdict.reason + "; no classifier configured")

    if mode == "monitor":
        _log(server_id, tool, args, verdict, mode, "executed (monitor)")
        return None
    if verdict.action == "allow":
        _log(server_id, tool, args, verdict, mode, "executed")
        return None
    if verdict.action == "ask":
        if await _ask_human(server_id, tool, args, verdict):
            _log(server_id, tool, args, verdict, mode, "approved")
            return None
        _log(server_id, tool, args, verdict, mode, "not approved")
        return (
            f"⛔ Not run: {tool} on {server_id} needs the user's approval "
            f"({verdict.reason}), and it was not given.\n"
            f"This can't be changed from a tool call; the user can edit {policy_path()}."
        )
    _log(server_id, tool, args, verdict, mode, "blocked")
    return (
        f"⛔ Blocked by Kitsune guard: {tool} on {server_id} — {verdict.reason}.\n"
        f"This can't be changed from a tool call; the user can edit {policy_path()}."
    )


def status_line() -> str | None:
    """One line for status(), or None when the guard is off."""
    policy = load_policy()
    if policy is None:
        return None
    if isinstance(policy, PolicyError):
        return f"  ⛔ Guard: policy file invalid — every call needs approval ({policy})"
    tally = ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "no calls yet"
    return f"  🛡  Guard: {policy.mode} (policy {policy.digest}) — {tally}"
