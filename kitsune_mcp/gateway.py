"""Kitsune Gateway Mode — client config discovery, credential harvest, server absorption."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from kitsune_mcp.constants import CRED_SUFFIXES
from kitsune_mcp.paths import kitsune_home

_KITSUNE_HOME = kitsune_home()
_ABSORBED_PATH = _KITSUNE_HOME / "absorbed_servers.json"
_BACKUP_DIR = _KITSUNE_HOME / "backup"


# ─── Client config paths ──────────────────────────────────────────────────────

def _client_config_paths() -> dict[str, Path]:
    """Return paths to existing MCP client config files on this machine."""
    plat = sys.platform
    home = Path.home()
    raw: dict[str, dict[str, Path]] = {
        "claude-desktop": {
            "darwin": home / "Library/Application Support/Claude/claude_desktop_config.json",
            "win32":  Path(os.environ.get("APPDATA", "")) / "Claude/claude_desktop_config.json",
            "linux":  home / ".config/Claude/claude_desktop_config.json",
        },
        "claude-code": {"all": home / ".claude/mcp.json"},
        "claude-code-user": {"all": home / ".claude.json"},
        "cursor":      {"all": home / ".cursor/mcp.json"},
        "windsurf":    {"all": home / ".codeium/windsurf/mcp_config.json"},
    }
    result: dict[str, Path] = {}
    for client, plat_map in raw.items():
        path = plat_map.get(plat) or plat_map.get("all")
        if path and path.exists():
            result[client] = path
    return result


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class AbsorbedServer:
    id: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict = field(default_factory=dict)
    client: str = ""
    absorbed_at: str = ""
    estimated_tools: int = 8
    url: str = ""              # remote servers ({"url": ...} config entries)
    transport: str = "stdio"   # "stdio" | "http" | "websocket"


@dataclass
class ClientConfig:
    client: str
    path: Path
    servers: list[AbsorbedServer]


# ─── Config discovery (Phase 1 — read-only) ───────────────────────────────────

def _parse_mcp_servers(config: dict, client: str) -> list[AbsorbedServer]:
    """Extract server stubs from an MCP client config dict.

    Handles both launch styles: local ({"command": ..., "args": [...]}) and
    remote ({"url": ..., "type": "http"|"sse"}). Entries with neither are
    skipped — absorbing an unlaunchable stub would make shapeshift fall back
    to `npx -y <id>`, executing an arbitrary same-named npm package.
    """
    servers: list[AbsorbedServer] = []
    for name, cfg in (config.get("mcpServers") or {}).items():
        if not isinstance(cfg, dict):
            continue
        command = cfg.get("command", "")
        url = cfg.get("url") or ""
        if command:
            transport = "stdio"
        elif url:
            transport = "websocket" if url.startswith(("ws://", "wss://")) else "http"
        else:
            continue
        servers.append(AbsorbedServer(
            id=name,
            command=command,
            args=cfg.get("args") or [],
            env=cfg.get("env") or {},
            client=client,
            url=url,
            transport=transport,
        ))
    return servers


def _claude_code_user_servers(data: dict) -> dict:
    """Merge mcpServers from ~/.claude.json: top-level + current project (project wins)."""
    servers = dict(data.get("mcpServers") or {})
    projects = data.get("projects")
    if isinstance(projects, dict):
        project = projects.get(str(Path.cwd()))
        if isinstance(project, dict):
            servers.update(project.get("mcpServers") or {})
    return servers


def _find_mcp_configs() -> list[ClientConfig]:
    """Discover MCP client configs present on this machine. Read-only.

    Precedence: ~/.claude.json (claude-code-user, the modern Claude Code
    location) wins over the legacy ~/.claude/mcp.json (claude-code) when
    both define the same server id.
    """
    result: list[ClientConfig] = []
    for client, path in _client_config_paths().items():
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        if client == "claude-code-user":
            data = {"mcpServers": _claude_code_user_servers(data)}
        servers = _parse_mcp_servers(data, client)
        if servers:
            result.append(ClientConfig(client=client, path=path, servers=servers))

    modern = next((c for c in result if c.client == "claude-code-user"), None)
    legacy = next((c for c in result if c.client == "claude-code"), None)
    if modern and legacy:
        modern_ids = {s.id for s in modern.servers}
        remaining = [s for s in legacy.servers if s.id not in modern_ids]
        if remaining:
            result = [
                ClientConfig(client=c.client, path=c.path, servers=remaining)
                if c is legacy else c
                for c in result
            ]
        else:
            result = [c for c in result if c is not legacy]
    return result


# ─── Credential harvest (Phase 2) ─────────────────────────────────────────────

def _is_credential_key(key: str) -> bool:
    env_name = key.upper().replace("-", "_")
    return any(env_name.endswith(sfx) for sfx in CRED_SUFFIXES)


def _harvest_credentials(servers: list[AbsorbedServer]) -> dict[str, str]:
    """Extract credential env vars from server env blocks. Returns {ENV_VAR: value}."""
    from kitsune_mcp.credentials import _to_env_var
    harvested: dict[str, str] = {}
    for srv in servers:
        for key, val in (srv.env or {}).items():
            if isinstance(val, str) and val and _is_credential_key(key):
                harvested[_to_env_var(key)] = val
    return harvested


# ─── Absorbed server persistence (Phase 3) ────────────────────────────────────

def _load_absorbed_servers() -> list[AbsorbedServer]:
    """Load absorbed server definitions from ~/.kitsune/absorbed_servers.json."""
    if not _ABSORBED_PATH.exists():
        return []
    try:
        data = json.loads(_ABSORBED_PATH.read_text())
        return [AbsorbedServer(**s) for s in data]
    except Exception:
        return []


def _save_absorbed_servers(servers: list[AbsorbedServer]) -> None:
    """Atomically write absorbed servers to ~/.kitsune/absorbed_servers.json."""
    _KITSUNE_HOME.mkdir(parents=True, exist_ok=True)
    payload = [s.__dict__.copy() for s in servers]
    fd, tmp = tempfile.mkstemp(dir=_KITSUNE_HOME, suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, _ABSORBED_PATH)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _to_server_info(a: AbsorbedServer):
    """Convert an AbsorbedServer to a ServerInfo for the registry."""
    from kitsune_mcp.registry import ServerInfo
    creds = {
        k: "" for k in (a.env or {})
        if _is_credential_key(k)
    }
    install_cmd = [a.command, *a.args] if a.command else []
    return ServerInfo(
        id=a.id,
        name=a.id,
        description=f"Absorbed from {a.client}",
        source="absorbed",
        transport=a.transport or "stdio",
        url=a.url,
        install_cmd=install_cmd,
        credentials=creds,
    )


# ─── Config management (Phase 4) ──────────────────────────────────────────────

def _write_project_config() -> Path:
    """Write .claude/mcp.json with only Kitsune for the current project."""
    cwd = Path.cwd()
    claude_dir = cwd / ".claude"
    claude_dir.mkdir(exist_ok=True)
    mcp_path = claude_dir / "mcp.json"
    config = {"mcpServers": {"kitsune": {"command": "npx", "args": ["-y", "kitsune-mcp"]}}}
    fd, tmp = tempfile.mkstemp(dir=claude_dir, suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(tmp, mcp_path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return mcp_path


def _write_exclusive_config(client: str, keep: list[str]) -> Path:
    """Backup existing config and rewrite keeping only Kitsune + listed server IDs."""
    paths = _client_config_paths()
    if client not in paths:
        raise FileNotFoundError(f"No config found for client: {client}")
    path = paths[client]
    original_text = path.read_text()
    data = json.loads(original_text)

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = _BACKUP_DIR / f"{client}.json"
    backup_path.write_text(original_text)

    mcp_servers = data.get("mcpServers") or {}
    data["mcpServers"] = {
        k: v for k, v in mcp_servers.items()
        if k in keep or "kitsune" in k.lower()
    }

    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return backup_path


def _restore_config(client: str) -> bool:
    """Restore backed-up config for the given client. Returns True if successful."""
    backup_path = _BACKUP_DIR / f"{client}.json"
    if not backup_path.exists():
        return False
    paths = _client_config_paths()
    target = paths.get(client)
    if target is None:
        # Config was removed; reconstruct path from backup location name
        return False
    target.write_text(backup_path.read_text())
    return True
