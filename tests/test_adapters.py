"""Tests for kitsune_mcp/adapters — Phase 3 adapter module."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Registry lookup ────────────────────────────────────────────────────────

class TestAdapterRegistry:
    def test_get_adapter_by_exact_id(self):
        from kitsune_mcp.adapters import get_adapter
        a = get_adapter("brave-search")
        assert a is not None
        assert a.CATEGORY == "web_search"

    def test_get_adapter_by_scoped_id(self):
        # "@modelcontextprotocol/server-github" → strips scope → "server-github"
        from kitsune_mcp.adapters import get_adapter
        a = get_adapter("@modelcontextprotocol/server-github")
        assert a is not None
        assert a.CATEGORY == "code_ops"

    def test_get_adapter_unknown_returns_none(self):
        from kitsune_mcp.adapters import get_adapter
        assert get_adapter("completely-unknown-server-xyz") is None

    def test_get_adapter_for_category_web_search(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        a = get_adapter_for_category("web_search")
        assert a is not None
        assert a.CATEGORY == "web_search"

    def test_get_adapter_for_category_none_returns_none(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        assert get_adapter_for_category(None) is None

    def test_get_adapter_for_category_unknown_returns_none(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        assert get_adapter_for_category("nonexistent_category") is None

    def test_all_categories_registered(self):
        from kitsune_mcp.adapters import _BY_CATEGORY
        expected = {"web_search", "file_ops", "code_ops", "database", "shell"}
        assert expected <= set(_BY_CATEGORY.keys())


# ── WebSearchAdapter ────────────────────────────────────────────────────────

class TestWebSearchAdapter:
    def _get(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        return get_adapter_for_category("web_search")

    def test_setup_hint_brave(self):
        hint = self._get().setup_hint("brave-search", ["BRAVE_API_KEY"])
        assert "brave.com/search/api" in hint
        assert "free" in hint.lower() or "Free" in hint

    def test_setup_hint_exa(self):
        hint = self._get().setup_hint("exa-search", ["EXA_API_KEY"])
        assert "exa.ai" in hint

    def test_setup_hint_unknown_cred_returns_empty(self):
        hint = self._get().setup_hint("brave-search", ["UNKNOWN_KEY"])
        assert hint == ""

    def test_infer_args_returns_none(self):
        # Handled by Rule 1 — adapter defers to generic inference
        schema = {"inputSchema": {"properties": {"query": {"type": "string"}}, "required": ["query"]}}
        assert self._get().infer_args("search for news", schema) is None


# ── FileOpsAdapter ──────────────────────────────────────────────────────────

class TestFileOpsAdapter:
    def _get(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        return get_adapter_for_category("file_ops")

    def test_setup_hint_filesystem(self):
        hint = self._get().setup_hint("server-filesystem", [])
        assert "server_args" in hint
        assert "filesystem" in hint

    def test_setup_hint_non_filesystem_empty(self):
        hint = self._get().setup_hint("mcp-server-git", [])
        assert hint == ""

    def test_infer_args_single_path_returns_none(self):
        # Single path param is handled by Rule 2a — adapter defers
        schema = {
            "inputSchema": {
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            }
        }
        result = self._get().infer_args("list files in /tmp", schema)
        assert result is None

    def test_infer_args_multi_path_extracts_both(self):
        schema = {
            "inputSchema": {
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            }
        }
        result = self._get().infer_args("copy /tmp/foo.txt to /tmp/bar.txt", schema)
        assert result == {"source": "/tmp/foo.txt", "destination": "/tmp/bar.txt"}

    def test_infer_args_multi_path_no_paths_returns_none(self):
        schema = {
            "inputSchema": {
                "properties": {
                    "source": {"type": "string"},
                    "destination": {"type": "string"},
                },
                "required": ["source", "destination"],
            }
        }
        result = self._get().infer_args("copy the config file to backup", schema)
        assert result is None


# ── CodeOpsAdapter ──────────────────────────────────────────────────────────

class TestCodeOpsAdapter:
    def _get(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        return get_adapter_for_category("code_ops")

    def _schema(self, extra_required=None):
        props = {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
        }
        required = ["owner", "repo"] + (extra_required or [])
        if extra_required:
            for p in extra_required:
                props[p] = {"type": "string"}
        return {"inputSchema": {"type": "object", "properties": props, "required": required}}

    def test_extracts_owner_and_repo(self):
        result = self._get().infer_args("check issues in kaiser-data/kitsune-mcp", self._schema())
        assert result == {"owner": "kaiser-data", "repo": "kitsune-mcp"}

    def test_extracts_from_url_style(self):
        result = self._get().infer_args("list PRs for anthropics/claude-code", self._schema())
        assert result == {"owner": "anthropics", "repo": "claude-code"}

    def test_no_owner_repo_in_task_returns_none(self):
        result = self._get().infer_args("check my github issues", self._schema())
        assert result is None

    def test_no_owner_param_in_schema_returns_none(self):
        schema = {
            "inputSchema": {
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            }
        }
        result = self._get().infer_args("search kaiser-data/kitsune-mcp", schema)
        assert result is None

    def test_partial_fill_with_extra_required_params(self):
        result = self._get().infer_args(
            "create issue in kaiser-data/kitsune-mcp",
            self._schema(extra_required=["title"]),
        )
        # Fills owner+repo but not title — partial fill is better than {}
        assert result == {"owner": "kaiser-data", "repo": "kitsune-mcp"}

    def test_setup_hint_github_token(self):
        hint = self._get().setup_hint("server-github", ["GITHUB_PERSONAL_ACCESS_TOKEN"])
        assert "github.com/settings/tokens" in hint

    def test_setup_hint_github_token_short(self):
        hint = self._get().setup_hint("server-github", ["GITHUB_TOKEN"])
        assert "github.com/settings/tokens" in hint

    def test_setup_hint_unknown_cred_empty(self):
        hint = self._get().setup_hint("server-github", ["SOME_OTHER_KEY"])
        assert hint == ""


# ── DatabaseAdapter ─────────────────────────────────────────────────────────

class TestDatabaseAdapter:
    def _get(self):
        from kitsune_mcp.adapters import get_adapter_for_category
        return get_adapter_for_category("database")

    def test_setup_hint_database_url(self):
        hint = self._get().setup_hint("server-postgres", ["DATABASE_URL"])
        assert "postgresql://" in hint

    def test_setup_hint_sqlite_path(self):
        hint = self._get().setup_hint("mcp-server-sqlite", ["SQLITE_DB_PATH"])
        assert ".db" in hint

    def test_setup_hint_generic_fallback(self):
        hint = self._get().setup_hint("server-postgres", ["SOME_DB_KEY"])
        assert "connection" in hint.lower()

    def test_infer_args_returns_none(self):
        # Handled by Rule 2.5 — adapter defers
        schema = {"inputSchema": {"properties": {"query": {"type": "string", "description": "SQL query"}}, "required": ["query"]}}
        assert self._get().infer_args("SELECT * FROM users", schema) is None
