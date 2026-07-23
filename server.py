"""Kitsune MCP — entry point and re-export facade.

All logic lives in the kitsune_mcp package. This file:
  1. Loads .env before any kitsune_mcp imports read os.getenv() at module level.
  2. Imports all modules so their @mcp.tool() decorators register with the shared mcp instance.
  3. Prunes tools based on KITSUNE_TOOLS env var (default: lean profile).
  4. Re-exports public names so existing tests (from server import ...) continue to work.

KITSUNE_TOOLS env var controls which tools are registered:
  (not set)  — lean profile: status, search, auth, shapeshift, call, auto,
               connect, release, reload  (9 tools, ~1,685 tokens overhead)
  KITSUNE_TOOLS=all           — all tools (forge / evaluator mode, ~3,396 tokens)
  KITSUNE_TOOLS=shapeshift,call — exactly those tools
"""

import contextlib

from dotenv import load_dotenv

# Must run before kitsune_mcp.credentials reads SMITHERY_API_KEY at module level.
# Load order: project-local .env first (lower priority), then $KITSUNE_HOME/.env
# (higher priority — wins regardless of CWD so daemon launches work correctly).
from kitsune_mcp.paths import kitsune_home  # noqa: E402

load_dotenv()                                           # CWD .env (project-local)
load_dotenv(kitsune_home() / ".env", override=True)     # canonical store wins

from kitsune_mcp.app import mcp  # noqa: E402, F401
from kitsune_mcp.constants import *  # noqa: E402, F401, F403
from kitsune_mcp.credentials import (  # noqa: E402, F401
    ENV_PATH,
    SMITHERY_API_KEY,
    _credentials_guide,
    _credentials_inspect_block,
    _dotenv_revision,
    _registry_headers,
    _reload_dotenv,
    _resolve_config,
    _save_to_env,
    _smithery_available,
    _to_env_var,
)
from kitsune_mcp.gateway import (  # noqa: E402, F401
    AbsorbedServer,
    ClientConfig,
    _find_mcp_configs,
    _harvest_credentials,
    _load_absorbed_servers,
    _parse_mcp_servers,
    _restore_config,
    _save_absorbed_servers,
    _to_server_info,
    _write_exclusive_config,
    _write_project_config,
)
from kitsune_mcp.official_registry import OfficialMCPRegistry  # noqa: E402, F401
from kitsune_mcp.probe import (  # noqa: E402, F401
    _ENV_VAR_RE,
    _LOCAL_URL_RE,
    _classify_provider,
    _doc_uri_priority,
    _format_setup_guide,
    _probe_requirements,
)
from kitsune_mcp.registry import (  # noqa: E402, F401
    _CACHE_TTL_SEARCH,
    _CACHE_TTL_SERVER,
    REGISTRY_BASE,
    AbsorbedRegistry,
    BaseRegistry,
    GitHubRegistry,
    GlamaRegistry,
    McpRegistryIO,
    MultiRegistry,
    NpmRegistry,
    PyPIRegistry,
    ServerInfo,
    SmitheryRegistry,
    _dedup_key,
    _detect_github_install_cmd,
    _extract_credentials,
    _registry,
    _relevance_score,
    _works_now_score,
)
from kitsune_mcp.session import (  # noqa: E402, F401
    SKILLS_PATH,
    _load_skills,
    _restore_crafted_tools,
    _save_skills,
    _save_state,
    session,
)
from kitsune_mcp.shapeshift import (  # noqa: E402, F401
    _do_shed,
    _json_type_to_py,
    _make_proxy,
    _register_proxy_prompts,
    _register_proxy_resources,
    _register_proxy_tools,
)
from kitsune_mcp.tools import (  # noqa: E402, F401
    _BASE_TOOL_NAMES,
    _state,
    auth,
    auto,
    bench,
    call,
    compare,
    connect,
    craft,
    fetch,
    inspect,
    key,
    prewarm,
    release,
    run,
    search,
    setup,
    shapeshift,
    shiftback,
    skill,
    status,
    test,
)
from kitsune_mcp.transport import (  # noqa: E402, F401
    BaseTransport,
    DockerTransport,
    HTTPSSETransport,
    PersistentStdioTransport,
    StdioTransport,
    WebSocketTransport,
    _evict_stale_pool_entries,
    _ping,
    _PoolEntry,
    _process_pool,
    _read_stdio_response,
    _validate_install_cmd,
)
from kitsune_mcp.utils import (  # noqa: E402, F401
    _clean_response,
    _estimate_tokens,
    _extract_content,
    _get_http_client,
    _rss_mb,
    _strip_html,
    _truncate,
    _try_axonmcp,
)

# ── Tool profile selection ────────────────────────────────────────────────────
# All tools registered above via @mcp.tool(). Prune to the requested profile.

_LEAN_TOOLS = _state._LEAN_TOOL_NAMES

_active_tools = _state._active_tool_names()

for _t in _BASE_TOOL_NAMES - _active_tools:
    with contextlib.suppress(Exception):
        mcp.remove_tool(_t)

_restore_crafted_tools()

if __name__ == "__main__":
    mcp.run()
