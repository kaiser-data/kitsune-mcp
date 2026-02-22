"""Chameleon MCP — entry point and re-export facade.

All logic lives in the chameleon_mcp package. This file:
  1. Loads .env before any chameleon_mcp imports read os.getenv() at module level.
  2. Imports all modules so their @mcp.tool() decorators register with the shared mcp instance.
  3. Re-exports public names so existing tests (from server import ...) continue to work.
"""

from dotenv import load_dotenv

# Must run before chameleon_mcp.credentials reads SMITHERY_API_KEY at module level.
load_dotenv()

from chameleon_mcp.app import mcp                                              # noqa: E402
from chameleon_mcp.utils import (                                              # noqa: E402
    _estimate_tokens, _truncate, _clean_response, _strip_html,
    _extract_content, _try_axonmcp,
)
from chameleon_mcp.session import session                                      # noqa: E402
from chameleon_mcp.credentials import (                                        # noqa: E402
    SMITHERY_API_KEY, ENV_PATH,
    _registry_headers, _smithery_available, _to_env_var, _save_to_env,
    _resolve_config, _credentials_guide,
)
from chameleon_mcp.registry import (                                           # noqa: E402
    REGISTRY_BASE, ServerInfo, BaseRegistry,
    SmitheryRegistry, NpmRegistry, MultiRegistry, _registry,
)
from chameleon_mcp.transport import (                                          # noqa: E402
    BaseTransport, _PoolEntry, _process_pool,
    HTTPSSETransport, StdioTransport, PersistentStdioTransport,
)
from chameleon_mcp.probe import (                                              # noqa: E402
    _ENV_VAR_RE, _LOCAL_URL_RE, _probe_requirements, _classify_provider,
    _format_setup_guide, _doc_uri_priority,
)
from chameleon_mcp.morph import (                                              # noqa: E402
    _json_type_to_py, _fetch_tools_list, _make_proxy, _do_shed,
    _register_proxy_tools,
)
from chameleon_mcp.tools import (                                              # noqa: E402
    _BASE_TOOL_NAMES,
    search, inspect, call, run, fetch, skill, key, auto,
    morph, shed, connect, release, test, bench, status, setup,
)
from chameleon_mcp.constants import *                                          # noqa: E402, F401, F403

if __name__ == "__main__":
    mcp.run()
