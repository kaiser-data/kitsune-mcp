"""Category-level adapters for auto() argument inference and credential guidance.

Each adapter handles one category of MCP servers (web_search, file_ops, etc.)
and provides two capabilities:
  - infer_args(): multi-param argument extraction that generic schema inference can't handle
  - setup_hint(): category-specific credential guidance with direct signup links
"""

from __future__ import annotations


class Adapter:
    """Base class for category adapters."""
    CATEGORY: str = ""
    KNOWN_IDS: frozenset[str] = frozenset()

    def infer_args(self, task: str, tool_schema: dict) -> dict | None:
        """Return inferred args, {} to call with no args, or None to fall through to generic inference."""
        return None

    def setup_hint(self, server_id: str, missing_creds: list[str]) -> str:
        """Return category-appropriate credential guidance, or '' for no additional hint."""
        return ""


# Populated on import of each adapter submodule below
_BY_ID: dict[str, Adapter] = {}
_BY_CATEGORY: dict[str, Adapter] = {}


def _register(adapter: Adapter) -> None:
    _BY_CATEGORY[adapter.CATEGORY] = adapter
    for sid in adapter.KNOWN_IDS:
        _BY_ID[sid] = adapter


def get_adapter(server_id: str) -> Adapter | None:
    """Look up an adapter by exact server ID."""
    # Also try matching on suffix — "@scope/server-name" and "server-name" both hit the same entry
    result = _BY_ID.get(server_id)
    if result:
        return result
    # Strip npm scope prefix if present
    bare = server_id.split("/")[-1] if "/" in server_id else server_id
    return _BY_ID.get(bare)


def get_adapter_for_category(category: str | None) -> Adapter | None:
    """Look up an adapter by task category (from _classify_task)."""
    if not category:
        return None
    return _BY_CATEGORY.get(category)


# Import adapters to populate _BY_ID and _BY_CATEGORY
from kitsune_mcp.adapters import code_ops, database, file_ops, shell, web_search  # noqa: E402, F401
