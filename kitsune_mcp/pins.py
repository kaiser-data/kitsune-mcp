"""Trust-on-first-use (TOFU) version pinning for local npm/PyPI servers.

The registry pins each server to the version it reports *at resolution time*
(`npx -y pkg@1.2.3` / `uvx pkg==1.2.3`). That makes a single session
reproducible, but "latest" still drifts across sessions — so the same
`shapeshift("server-x")` can silently execute a *newer* (possibly hijacked)
release next week. Version pinning at resolution alone can't catch that: it
pins whatever the registry reports each time.

TOFU closes the gap. The FIRST time a server is mounted, its exact resolved
version is recorded in `~/.kitsune/pins.json`. Later mounts reuse the recorded
version and warn when the registry has moved on — turning a silent post-install
package hijack into a visible "this moved since you trusted it" prompt. Adopt
the newer version (and overwrite the pin) with `KITSUNE_REPIN=1`.

Only concrete `npx`/`uvx` specs carry a version, so only they are pinnable;
`github:` targets, bare-name local installs, and hand-written `connect()`
commands pass through untouched (documented limit — no version to record).
"""
import json
import os
from pathlib import Path

from kitsune_mcp.paths import kitsune_home

PINS_VERSION = 1


def _pins_path() -> Path:
    """Location of the TOFU pin store. Computed lazily so KITSUNE_HOME set at
    runtime (tests, benchmarks, multi-tenant) is always honored."""
    return kitsune_home() / "pins.json"


def _load() -> dict:
    """Return {server_id: {source, version, spec}} — {} on missing/corrupt file."""
    path = _pins_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    pins = data.get("pins")
    return pins if isinstance(pins, dict) else {}


def _save(pins: dict) -> None:
    """Atomically persist the pin store (0600, like other ~/.kitsune state)."""
    path = _pins_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"version": PINS_VERSION, "pins": pins}, indent=2, sort_keys=True))
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def get_pin(server_id: str) -> dict | None:
    """Return the recorded pin for a server, or None if never pinned."""
    return _load().get(server_id)


def record_pin(server_id: str, source: str, name: str, version: str) -> None:
    """Record (or overwrite) the pinned version for a server."""
    pins = _load()
    pins[server_id] = {"source": source, "name": name, "version": version}
    _save(pins)


def _parse_spec(install_cmd: list[str]) -> tuple[int, str, str, str] | None:
    """Locate the versioned package spec in an npx/uvx install command.

    Returns (index, name, version, sep) where install_cmd[index] is the spec
    token, or None when the command carries no pinnable version:
      ["npx", "-y", "pkg@1.2.3"]          -> (2, "pkg", "1.2.3", "@")
      ["npx", "-y", "@scope/pkg@1.2.3"]   -> (2, "@scope/pkg", "1.2.3", "@")
      ["uvx", "pkg==1.2.3"]               -> (1, "pkg", "1.2.3", "==")
      ["npx", "-y", "github:owner/repo"]  -> None  (no version)
      ["uvx", "bare-name"]                -> None  (no version)
    """
    if not install_cmd:
        return None
    launcher = install_cmd[0]
    # The spec is the first non-flag argument after the launcher.
    spec_index = next(
        (i for i in range(1, len(install_cmd)) if not install_cmd[i].startswith("-")),
        None,
    )
    if spec_index is None:
        return None
    spec = install_cmd[spec_index]
    if launcher == "uvx":
        if "==" not in spec:
            return None
        name, version = spec.split("==", 1)
        return (spec_index, name, version, "==") if name and version else None
    if launcher == "npx":
        # Version separator is the LAST '@' that isn't the scoped-package prefix.
        at = spec.rfind("@")
        if at <= 0:  # -1 (no @) or 0 (leading @scope with no version)
            return None
        name, version = spec[:at], spec[at + 1:]
        return (spec_index, name, version, "@") if name and version else None
    return None


def reconcile(server_id: str, install_cmd: list[str], source: str,
              repin: bool | None = None) -> tuple[list[str], str]:
    """Apply TOFU pinning to a resolved install command.

    Returns (install_cmd, note): the command to actually launch (rewritten to
    the pinned version on drift) and a human-readable note for the mount output
    (empty when there is nothing to say).

    repin=None reads the KITSUNE_REPIN env policy; pass True/False to force it.
    """
    parsed = _parse_spec(install_cmd)
    if parsed is None:
        return install_cmd, ""  # nothing pinnable — pass through untouched
    index, name, resolved, sep = parsed

    if repin is None:
        repin = (os.getenv("KITSUNE_REPIN") or "").lower() in ("1", "true", "yes", "all")

    existing = get_pin(server_id)

    if repin:
        record_pin(server_id, source, name, resolved)
        if existing and existing.get("version") != resolved:
            return install_cmd, f"🔒 Repinned {name} {existing.get('version')} → {resolved} (KITSUNE_REPIN)."
        return install_cmd, f"🔒 Pinned {name} to {resolved} (KITSUNE_REPIN)."

    if existing is None:
        record_pin(server_id, source, name, resolved)
        return install_cmd, (
            f"🔒 Pinned {name} to {resolved} on first use — future mounts reuse "
            f"this exact version. (KITSUNE_REPIN=1 to adopt newer releases.)"
        )

    pinned_version = existing.get("version", "")
    if pinned_version == resolved:
        return install_cmd, ""  # unchanged since first use — nothing to report

    # Drift: the registry now offers a different version than the one trusted on
    # first use. Launch the PINNED version and make the divergence visible.
    rewritten = list(install_cmd)
    rewritten[index] = f"{name}{sep}{pinned_version}"
    return rewritten, (
        f"⚠️  {name} is pinned to {pinned_version}, but the registry now offers "
        f"{resolved}. Running the pinned version. Set KITSUNE_REPIN=1 to adopt "
        f"{resolved} and update the pin."
    )
