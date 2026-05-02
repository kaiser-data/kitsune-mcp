"""Public surface for kitsune_mcp.tools.

Implementation is split into themed submodules:
    discovery   — search, inspect, compare, status
    exec        — call, run, fetch, test, bench
    morph       — shapeshift, shiftback, craft, connect, release
    onboarding  — skill, key, auto, setup
    _state      — shared helpers and mock-patchable cross-cutting state

For mock.patch in tests, prefer `kitsune_mcp.tools._state.X` so the patch
catches every call site uniformly.
"""

# Submodule imports trigger @mcp.tool() registration on the shared FastMCP instance.
from kitsune_mcp.tools import _state  # noqa: F401  (re-exported)
from kitsune_mcp.tools.discovery import compare, inspect, search, status  # noqa: F401
from kitsune_mcp.tools.exec import bench, call, fetch, run, test  # noqa: F401
from kitsune_mcp.tools.morph import connect, craft, release, shapeshift, shiftback  # noqa: F401
from kitsune_mcp.tools.onboarding import auto, key, setup, skill  # noqa: F401

# Backward-compat re-exports of names that tests / server.py imported from
# the old monolithic kitsune_mcp/tools.py module.
from kitsune_mcp.tools._state import (  # noqa: F401
    _AVG_TOKENS_PER_TOOL,
    _BASE_TOOL_NAMES,
    _DUMMY_VALUES,
    _EXAMPLE_VALUES,
    _PROBE_CRED_SUFFIXES,
    _TOOL_COUNT_RE,
    BaseTransport,
    DockerTransport,
    HTTPSSETransport,
    NpmRegistry,
    PersistentStdioTransport,
    PyPIRegistry,
    SmitheryRegistry,
    WebSocketTransport,
    _compare_missing_creds,
    _do_shed,
    _extract_tool_schema,
    _fetch_resource_docs,
    _get_transport,
    _humanize_probe_error,
    _infer_install_cmd,
    _local_uninstall_cmd,
    _probe_env,
    _probe_label,
    _probe_requirements,
    _probe_trust_ok,
    _proxy_name_for,
    _register_proxy_prompts,
    _register_proxy_resources,
    _register_proxy_tools,
    _registry,
    _resolve_config,
    _smithery_available,
    _synthetic_http_server,
    _to_env_var,
    _tool_count_hint,
    _track_call,
    session,
)
