import contextlib
import json

from kitsune_mcp.paths import kitsune_home

_KITSUNE_HOME = kitsune_home()
SKILLS_PATH = _KITSUNE_HOME / "skills.json"
_STATE_PATH = _KITSUNE_HOME / "state.json"

_session: dict = {
    "explored": {},
    "skills": {},
    "grown": {},
    "shapeshift_tools": [],      # names of dynamically registered proxy tools
    "shapeshift_resources": [],  # normalized URI strings registered via shapeshift()
    "shapeshift_prompts": [],    # prompt names registered via shapeshift()
    "crafted_tools": {},         # name -> {url, method, description, params, headers}
    "current_form": None,        # server_id currently shapeshifted into
    "current_form_pool_key": None,  # exact _process_pool key for shiftback(kill=True)
    "current_form_local_install": None,  # {"cmd": [...], "package": str} when source="local"
    "connections": {},        # persistent connections: {pool_key: {name, command, pid, ...}}
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


def _save_state() -> None:
    """Persist crafted_tools, connections metadata, and explored history to disk."""
    try:
        _KITSUNE_HOME.mkdir(parents=True, exist_ok=True)
        state = {
            "crafted_tools": session.get("crafted_tools", {}),
            # Strip runtime fields (pid, started_at) — dead after restart
            "connections": {
                k: {f: v for f, v in conn.items() if f not in ("pid", "started_at")}
                for k, conn in session.get("connections", {}).items()
            },
            # Cap explored history to 100 entries (keep most recent)
            "explored": dict(list(session.get("explored", {}).items())[-100:]),
        }
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass


def _load_state() -> None:
    """Restore crafted_tools, connections, and explored from disk."""
    try:
        with open(_STATE_PATH) as f:
            state = json.load(f)
        session.setdefault("crafted_tools", {}).update(state.get("crafted_tools", {}))
        session.setdefault("connections", {}).update(state.get("connections", {}))
        session.setdefault("explored", {}).update(state.get("explored", {}))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


def _restore_crafted_tools() -> None:
    """Re-register crafted tools with FastMCP after a server restart.

    Called from server.py after all imports so mcp is fully initialized.
    """
    crafted = session.get("crafted_tools", {})
    if not crafted:
        return
    import inspect as _inspect

    import httpx as _httpx

    from kitsune_mcp.app import mcp as _mcp
    from kitsune_mcp.shapeshift import _json_type_to_py
    from kitsune_mcp.utils import _ssrf_safe_request

    def _build_proxy(name: str, url: str, method: str, description: str, params: dict):
        py_params = []
        for pname, pschema in params.items():
            json_type = pschema.get("type", "string") if isinstance(pschema, dict) else "string"
            ptype = _json_type_to_py(json_type)
            py_params.append(_inspect.Parameter(
                pname, _inspect.Parameter.KEYWORD_ONLY,
                default=_inspect.Parameter.empty, annotation=ptype,
            ))
        _u, _m = url, method

        async def _endpoint_proxy(**kwargs) -> str:
            try:
                if _m == "GET":
                    r = await _ssrf_safe_request("GET", _u, params=kwargs, timeout=30.0)
                else:
                    r = await _ssrf_safe_request(_m, _u, json_body=kwargs, timeout=30.0)
                r.raise_for_status()
                return r.text
            except _httpx.HTTPStatusError as e:
                return f"HTTP {e.response.status_code} from {_u}: {e.response.text[:200]}"
            except Exception as e:
                return f"Error calling {_u}: {e}"

        _endpoint_proxy.__name__ = name
        _endpoint_proxy.__doc__ = description[:120]
        _endpoint_proxy.__signature__ = _inspect.Signature(py_params, return_annotation=str)
        return _endpoint_proxy

    for tool_name, info in crafted.items():
        proxy = _build_proxy(
            tool_name,
            info.get("url", ""),
            info.get("method", "POST"),
            info.get("description", ""),
            info.get("params", {}),
        )
        with contextlib.suppress(Exception):
            _mcp.add_tool(proxy)


_load_skills()
