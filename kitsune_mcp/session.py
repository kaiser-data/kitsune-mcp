import contextlib
import json
import os

from kitsune_mcp.paths import kitsune_home

_KITSUNE_HOME = kitsune_home()
SKILLS_PATH = _KITSUNE_HOME / "skills.json"
_STATE_PATH = _KITSUNE_HOME / "state.json"

_session: dict = {
    "explored": {},
    "skills": {},
    "grown": {},
    "shapeshift_tools": [],  # names of dynamically registered proxy tools
    "shapeshift_resources": [],  # normalized URI strings registered via shapeshift()
    "shapeshift_prompts": [],  # prompt names registered via shapeshift()
    "crafted_tools": {},  # name -> {url, method, description, params, headers}
    "current_form": None,  # server_id currently shapeshifted into
    "current_form_pool_key": None,  # exact _process_pool key for shiftback(kill=True)
    "current_form_srv": None,  # ServerInfo of the mounted form; call() reuses it
    "current_form_local_install": None,  # {"cmd": [...], "package": str} when source="local"
    "connections": {},  # persistent connections: {pool_key: {name, command, pid, ...}}
    "stats": {
        "total_calls": 0,
        "tokens_sent": 0,
        "tokens_received": 0,
        "tokens_saved_browse": 0,
        # Sum of schema-token costs for every server mounted this session.
        # Represents "tokens you would now be paying per turn if every server
        # used this session had been installed always-on". Keyed by server_id
        # so re-mounting the same server in the same session doesn't double-count.
        "tokens_avoided_shapeshift": {},
    },
}

session = _session


def _load_skills() -> None:
    """Populate session['skills'] from disk on startup."""
    try:
        with open(SKILLS_PATH) as f:
            data = json.load(f)
        if isinstance(data, dict):
            session["skills"].update(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    _load_state()


def _save_skills() -> None:
    """Persist session['skills'] to disk."""
    try:
        SKILLS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SKILLS_PATH, "w") as f:
            json.dump(session["skills"], f, indent=2)
    except OSError:
        pass
    _save_state()


# Sections of state.json, and the keys this process last saw for each one.
# Two clients (two Kitsune processes) can share one state directory. Each used
# to write its whole in-memory state, so the last writer silently erased what
# the other had added. Saving now merges with the file on disk: keys another
# process added are kept, and only keys *this* process removed are dropped.
_STATE_SECTIONS = ("crafted_tools", "connections", "explored")
_synced_keys: dict[str, set] = {name: set() for name in _STATE_SECTIONS}


def _state_lock_path():
    return _STATE_PATH.with_name(f"{_STATE_PATH.name}.lock")


@contextlib.contextmanager
def _state_file_lock():
    """Exclusive inter-process lock around a state.json read-merge-write."""
    try:
        import fcntl
    except ImportError:  # Windows: no flock; the merge still narrows the window
        yield
        return
    fd = os.open(_state_lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_state_file() -> dict:
    try:
        with open(_STATE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _merge_section(name: str, disk: dict, ours: dict) -> dict:
    """Disk entries, minus keys this process deleted, plus this process's entries."""
    merged = dict(disk) if isinstance(disk, dict) else {}
    for k in _synced_keys[name] - ours.keys():
        merged.pop(k, None)
    merged.update(ours)
    return merged


def _save_state() -> None:
    """Persist crafted_tools, connections metadata, and explored history to disk."""
    tmp = _STATE_PATH.with_name(f"{_STATE_PATH.name}.{os.getpid()}.tmp")
    try:
        _KITSUNE_HOME.mkdir(parents=True, exist_ok=True)
        ours = {
            "crafted_tools": dict(session.get("crafted_tools", {})),
            # Strip runtime fields (pid, started_at) — dead after restart
            "connections": {
                k: {f: v for f, v in conn.items() if f not in ("pid", "started_at")}
                for k, conn in session.get("connections", {}).items()
            },
            "explored": dict(session.get("explored", {})),
        }
        with _state_file_lock():
            disk = _read_state_file()
            state = {name: _merge_section(name, disk.get(name, {}), ours[name]) for name in ours}
            # Cap explored history to 100 entries (keep most recent)
            state["explored"] = dict(list(state["explored"].items())[-100:])
            # Atomic: write a temp file, then rename over the old one. A crash
            # mid-write can no longer leave a truncated state.json (which
            # _load_state would silently treat as empty).
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, _STATE_PATH)
        for name in _STATE_SECTIONS:
            _synced_keys[name] = set(ours[name])
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def _load_state() -> None:
    """Restore crafted_tools, connections, and explored from disk."""
    state = _read_state_file()
    for name in _STATE_SECTIONS:
        section = state.get(name, {})
        if isinstance(section, dict):
            session.setdefault(name, {}).update(section)
        _synced_keys[name] = set(session.get(name, {}))


def _restore_crafted_tools() -> None:
    """Re-register crafted tools after a server restart.

    Called from server.py after all imports so mcp is fully initialized.
    """
    crafted = session.get("crafted_tools", {})
    if not crafted:
        return
    from kitsune_mcp.app import mcp as _mcp
    from kitsune_mcp.tools.shapeshift import _make_endpoint_proxy

    for tool_name, info in crafted.items():
        proxy = _make_endpoint_proxy(
            tool_name,
            info.get("url", ""),
            info.get("method", "POST"),
            dict(info.get("headers") or {}),
            info.get("params", {}),
            description=info.get("description", ""),
        )
        with contextlib.suppress(Exception):
            _mcp.add_tool(proxy)
            # Tracked like a freshly crafted tool, so shiftback() removes it.
            if tool_name not in session["shapeshift_tools"]:
                session["shapeshift_tools"].append(tool_name)


_load_skills()
