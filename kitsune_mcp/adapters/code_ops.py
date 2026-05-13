"""Adapter for code/repository MCP servers: GitHub, GitLab."""

import re

from kitsune_mcp.adapters import Adapter, _register

_OWNER_REPO_RE = re.compile(r'\b([a-zA-Z0-9_-]+)/([a-zA-Z0-9_.-]+)\b')

_SETUP_HINTS: dict[str, str] = {
    "GITHUB_PERSONAL_ACCESS_TOKEN": (
        "Create a free token at github.com/settings/tokens — classic, repo scope"
    ),
    "GITHUB_TOKEN": "Create a free token at github.com/settings/tokens — classic, repo scope",
    "GITLAB_PERSONAL_ACCESS_TOKEN": (
        "Create at gitlab.com/-/user_settings/personal_access_tokens — api scope"
    ),
}


class CodeOpsAdapter(Adapter):
    CATEGORY = "code_ops"
    KNOWN_IDS = frozenset({
        "server-github",
        "github-mcp-server",
        "server-gitlab",
        "gitlab-mcp-server",
    })

    def infer_args(self, task: str, tool_schema: dict) -> dict | None:
        """Extract owner + repo from task when tool requires them as separate params."""
        schema = tool_schema.get("inputSchema") or {}
        required = set(schema.get("required") or [])

        # Identify owner and repo params by name
        owner_param = next((p for p in required if p in ("owner", "namespace")), None)
        repo_param = next((p for p in required if p in ("repo", "repository", "project")), None)

        if not owner_param or not repo_param:
            return None

        m = _OWNER_REPO_RE.search(task)
        if not m:
            return None

        result: dict[str, str] = {owner_param: m.group(1), repo_param: m.group(2)}

        # Fill any other required string params that are empty — leave them to the caller
        # (returning partial fill is better than returning {} for multi-param tools)
        return result

    def setup_hint(self, server_id: str, missing_creds: list[str]) -> str:
        for cred in missing_creds:
            hint = _SETUP_HINTS.get(cred.upper())
            if hint:
                return hint
        return ""


_register(CodeOpsAdapter())
