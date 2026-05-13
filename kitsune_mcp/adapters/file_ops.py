"""Adapter for file/filesystem MCP servers: filesystem, git."""

import re

from kitsune_mcp.adapters import Adapter, _register


def _extract_paths(task: str) -> list[str]:
    """Extract all path-like substrings from a task string."""
    return re.findall(r'(?:^|\s)((?:/|~|\.{1,2}/)\S+)', task)


class FileOpsAdapter(Adapter):
    CATEGORY = "file_ops"
    KNOWN_IDS = frozenset({
        "server-filesystem",
        "server-git",
        "mcp-server-git",
    })

    def infer_args(self, task: str, tool_schema: dict) -> dict | None:
        schema = tool_schema.get("inputSchema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])

        # Only activate for multi-required-string tools — single-param handled by Rule 2a.
        # On a file_ops server, any 2+ required string params are almost certainly paths.
        str_required = [p for p in props if p in required and props[p].get("type") == "string"]
        if len(str_required) < 2:
            return None

        paths = _extract_paths(task)
        if not paths:
            return None

        result = {pname: paths[i] for i, pname in enumerate(str_required) if i < len(paths)}
        return result if result else None

    def setup_hint(self, server_id: str, missing_creds: list[str]) -> str:
        if "filesystem" in server_id:
            return (
                "Filesystem server requires allowed directories — "
                f'shapeshift("{server_id}", server_args=["/your/path"])'
            )
        return ""


_register(FileOpsAdapter())
