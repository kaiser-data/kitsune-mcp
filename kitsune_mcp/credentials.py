import os
import re
from pathlib import Path

from dotenv import load_dotenv

from kitsune_mcp.constants import CRED_SUFFIXES, TRUST_LOW, TRUST_MEDIUM

# Read at import time (load_dotenv() must be called by entry point first)
SMITHERY_API_KEY = os.getenv("SMITHERY_API_KEY", "")
# Write .env to the user's working directory (same location load_dotenv() reads from).
ENV_PATH = os.path.join(os.getcwd(), ".env")

# .env search order — CWD wins (loaded last with override=True)
_DOTENV_PATHS = [
    Path.home() / ".kitsune" / ".env",
    Path.home() / ".env",
    Path(ENV_PATH),
]

# Revision counter — increments whenever any .env file changes on disk.
# Pool entries store their revision at spawn time; stale entries are evicted
# and respawned so they pick up new credentials automatically.
#
# INVARIANT: _dotenv_revision is monotonically non-decreasing for the lifetime
# of the process, including in tests. The pool eviction logic in
# transport._get_or_start compares `entry.dotenv_revision != _dotenv_revision`
# to decide whether a pool process predates a .env change. If this counter is
# ever reset (e.g. `_dotenv_revision = 0` in a test fixture) while pool entries
# exist, those entries become indistinguishable from freshly-spawned ones and
# stale env values stick. Tests that need to simulate a .env change MUST
# increment the counter, never reset it.
_dotenv_revision: int = 0
_last_dotenv_mtimes: tuple = ()


def _dotenv_mtimes() -> tuple:
    """Return mtime tuple for all .env paths (None if absent)."""
    result = []
    for p in _DOTENV_PATHS:
        try:
            result.append(p.stat().st_mtime)
        except OSError:
            result.append(None)
    return tuple(result)


def _reload_dotenv() -> None:
    """Re-read all .env locations. CWD wins. Increments _dotenv_revision when files change."""
    global _dotenv_revision, _last_dotenv_mtimes
    current_mtimes = _dotenv_mtimes()
    for p in _DOTENV_PATHS[:-1]:
        if p.exists():
            load_dotenv(p, override=False)
    load_dotenv(_DOTENV_PATHS[-1], override=True)  # CWD .env wins
    if current_mtimes != _last_dotenv_mtimes:
        _dotenv_revision += 1
        _last_dotenv_mtimes = current_mtimes


def _registry_headers():
    api_key = os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _smithery_available() -> bool:
    return bool(os.getenv("SMITHERY_API_KEY") or SMITHERY_API_KEY)


def _to_env_var(k: str) -> str:
    s = re.sub(r'([a-z])([A-Z])', r'\1_\2', k)
    s = re.sub(r'([A-Z]+)([A-Z][a-z])', r'\1_\2', s)
    return s.upper()


def _save_to_env(env_var: str, value: str) -> None:
    try:
        try:
            with open(ENV_PATH) as f:
                lines = f.readlines()
        except FileNotFoundError:
            lines = []
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{env_var}="):
                lines[i] = f"{env_var}={value}\n"
                found = True
                break
        if not found:
            if lines and not lines[-1].endswith('\n'):
                lines.append('\n')
            lines.append(f"{env_var}={value}\n")
        with open(ENV_PATH, 'w') as f:
            f.writelines(lines)
    except OSError:
        pass
    os.environ[env_var] = value


def _resolve_config(credentials: dict, user_config: dict) -> tuple:
    _reload_dotenv()  # re-read .env on every check — picks up mid-session edits
    resolved = dict(user_config)
    for cred_key in credentials:
        if not resolved.get(cred_key):
            val = os.getenv(_to_env_var(cred_key)) or None
            resolved[cred_key] = val  # None → JSON null, satisfies Smithery config schema
    # Only block on real secrets — env vars ending in a credential suffix.
    # Optional config knobs (ENABLED_TOOLS, LOGGING_LEVEL, etc.) are not blockers.
    missing = {
        k: v for k, v in credentials.items()
        if not resolved.get(k) and any(_to_env_var(k).endswith(sfx) for sfx in CRED_SUFFIXES)
    }
    return resolved, missing


def _credentials_guide(server_id: str, credentials: dict, resolved: dict) -> str:
    """Credential status with actionable .env lines for missing ones."""
    missing = {k: v for k, v in credentials.items() if not resolved.get(k)}
    if not missing:
        return ""
    envs = {k: _to_env_var(k) for k in credentials}
    lines = [f"Server '{server_id}' needs credentials:"]
    for cred_key, desc in credentials.items():
        status = "✓" if resolved.get(cred_key) else "✗"
        desc_str = f" — {desc[:60]}" if desc else ""
        lines.append(f"  {status} {envs[cred_key]}{desc_str}")
    missing_envs = [envs[k] for k in missing]
    lines += [
        "",
        "Add to .env:",
        *[f"  {e}=your-value" for e in missing_envs],
        f"Or: key('{missing_envs[0]}', 'your-value')",
    ]
    return "\n".join(lines)


def _credentials_ready(credentials: dict, source: str = "") -> str:
    """One-line credential status. Describes what we verified.

    Three tiers, all explicit (never just "no creds declared"):
      ✅ free – no key       — official/npm/pypi sources without declared creds
      🔑 key required        — Smithery-hosted servers (always need SMITHERY_API_KEY)
                               or any server with declared creds
      ⚠️  key unknown         — community sources (glama/github) without declared creds —
                               undeclared ≠ free; runtime auth may still fail
    """
    # Smithery-hosted servers always require SMITHERY_API_KEY regardless of
    # whether the registry entry declares per-server creds. This is the most
    # common first-run failure source — "no creds declared" misled users.
    if source == "smithery":
        return "✓ env set" if _smithery_available() else "🔑 needs SMITHERY_API_KEY"

    if not credentials:
        if source in TRUST_LOW:
            return "⚠️  community — may need creds"
        if source in TRUST_MEDIUM:
            return "🔑 may need OAuth or registry key"
        # TRUST_HIGH (official) without declared creds: most likely truly free
        return "✅ free – no key"

    _reload_dotenv()
    missing = [
        env for k in credentials
        for env in [_to_env_var(k)]
        if not os.getenv(env) and any(env.endswith(sfx) for sfx in CRED_SUFFIXES)
    ]
    return "✓ env set" if not missing else f"🔑 needs {', '.join(missing)}"


def _credentials_inspect_block(credentials: dict, resolved: dict, source: str = "") -> list[str]:
    """CREDENTIALS section lines for inspect() — shows ✓/✗ per key with .env hints."""
    if not credentials:
        lines = ["CREDENTIALS: none declared in registry"]
        if source in TRUST_MEDIUM | TRUST_LOW:
            lines += [
                "  Note: declared ≠ actual. Servers may still require browser OAuth",
                "  on first call, out-of-band setup (e.g., sharing Notion pages,",
                "  granting scopes), or a valid unexpired token. Check the README.",
            ]
        lines.append("")
        return lines
    envs = {k: _to_env_var(k) for k in credentials}
    lines = ["CREDENTIALS"]
    for cred_key, desc in credentials.items():
        status = "✓ env set" if resolved.get(cred_key) else "✗ missing"
        desc_str = f" — {desc[:60]}" if desc else ""
        lines.append(f"  {status}  {envs[cred_key]}{desc_str}")
    missing_envs = [envs[k] for k in credentials if not resolved.get(k)]
    if missing_envs:
        lines += ["", "  Add to .env:"] + [f"    {e}=your-value" for e in missing_envs]
    lines.append("")
    return lines
