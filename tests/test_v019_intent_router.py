"""Tests for v0.19 Intent Router — Phase 1 (auto in lean + _blocked) and Phase 2 (category routing + schema inference)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Phase 1: auto in lean + _blocked format ────────────────────────────────


def test_auto_in_lean_profile():
    """auto must be in the lean tool set starting from v0.19."""
    from server import _LEAN_TOOLS
    assert "auto" in _LEAN_TOOLS, "auto must be in lean profile (v0.19+)"


def test_blocked_helper_format():
    """`_blocked()` returns the standard 3-line format."""
    from kitsune_mcp.tools.onboarding import _blocked
    result = _blocked(what="server X needs credentials", why="API_KEY missing", fix="auth('API_KEY', 'val')")
    assert result.startswith("✗ Blocked:")
    assert "  Why:" in result
    assert "  Fix:" in result
    assert "  Alt:" not in result


def test_blocked_helper_with_fallback():
    """`_blocked()` includes Alt line when fallback is given."""
    from kitsune_mcp.tools.onboarding import _blocked
    result = _blocked(
        what="schema fetch failed",
        why="no SMITHERY_API_KEY",
        fix="auth('SMITHERY_API_KEY', 'sm-...')",
        fallback="search() for a free alternative",
    )
    assert "  Alt:" in result
    assert "search()" in result


def test_blocked_format_four_fields():
    """`_blocked()` output has exactly 3 or 4 lines depending on fallback."""
    from kitsune_mcp.tools.onboarding import _blocked
    without_fallback = _blocked("what", "why", "fix")
    assert len(without_fallback.splitlines()) == 3

    with_fallback = _blocked("what", "why", "fix", "alt")
    assert len(with_fallback.splitlines()) == 4


# ── Phase 2: _classify_task ───────────────────────────────────────────────


class TestClassifyTask:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _classify_task
        return _classify_task

    def test_web_search(self):
        assert self._fn()("search the web for AI news") == "web_search"

    def test_web_search_query(self):
        assert self._fn()("find results for python tutorials") == "web_search"

    def test_file_ops(self):
        assert self._fn()("list files in /tmp") == "file_ops"

    def test_file_ops_read(self):
        assert self._fn()("read the file at /home/user/config.json") == "file_ops"

    def test_code_ops_github(self):
        assert self._fn()("check issues in github repo") == "code_ops"

    def test_code_ops_git(self):
        assert self._fn()("run git log in my repository") == "code_ops"

    def test_shell(self):
        assert self._fn()("execute a shell command to install dependencies") == "shell"

    def test_database(self):
        assert self._fn()("query my postgres database for users") == "database"

    def test_database_sql(self):
        assert self._fn()("run sql select from users table") == "database"

    def test_productivity_notion(self):
        assert self._fn()("search my notion workspace") == "productivity"

    def test_communication_slack(self):
        assert self._fn()("send a slack message to #general") == "communication"

    def test_time_util(self):
        assert self._fn()("what time is it in UTC") == "time_util"

    def test_memory(self):
        assert self._fn()("remember this for later") == "memory"

    def test_unknown_returns_none(self):
        assert self._fn()("xyz qrs") is None

    def test_highest_score_wins(self):
        # "sql" and "database" both in database category — should still be database
        result = self._fn()("query the sql database table")
        assert result == "database"


# ── Phase 2: _classify_param ─────────────────────────────────────────────


class TestClassifyParam:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _classify_param
        return _classify_param

    def test_sql_query_by_description(self):
        assert self._fn()("query", "SQL query to execute", "Execute a database query") == "sql_query"

    def test_sql_query_by_name_in_combined(self):
        assert self._fn()("statement", "The sql query string", "") == "sql_query"

    def test_shell_command_by_description(self):
        assert self._fn()("cmd", "Shell command to run", "Execute command in terminal") == "shell_command"

    def test_shell_command_by_tool_desc(self):
        assert self._fn()("command", "", "Execute a bash command in the terminal") == "shell_command"

    def test_repo_identifier(self):
        assert self._fn()("repo", "GitHub repository (owner/repo)", "") == "repo_identifier"

    def test_repo_identifier_github_com(self):
        assert self._fn()("target", "URL like github.com/owner/repo", "") == "repo_identifier"

    def test_file_path_by_description(self):
        assert self._fn()("location", "Path to file to read", "") == "file_path"

    def test_file_path_by_name_is_free_text(self):
        # "path" is in _PATH_PARAM_NAMES so Rule 2a catches it before _classify_param runs.
        # _classify_param only sees params that escaped the name-based rules.
        assert self._fn()("path", "", "") == "free_text"

    def test_search_query_name_is_free_text(self):
        # _classify_param is only called for params NOT caught by Rule 1 (search names).
        # "query" would be handled by Rule 1 before _classify_param is ever called.
        assert self._fn()("query", "", "") == "free_text"

    def test_connection_string_is_free_text(self):
        # No safe inference exists for connection strings — falls through to Rule 3.
        assert self._fn()("dsn", "Database connection string", "") == "free_text"

    def test_free_text_fallback(self):
        result = self._fn()("random_param", "Some random thing", "")
        assert result == "free_text"


# ── Phase 2: _infer_args_from_task enhanced with _classify_param ─────────


class TestInferArgsEnhanced:
    def _fn(self):
        from kitsune_mcp.tools.onboarding import _infer_args_from_task
        return _infer_args_from_task

    def _schema(self, pname, ptype="string", desc="", tool_desc="", required=True):
        return {
            "description": tool_desc,
            "inputSchema": {
                "type": "object",
                "properties": {pname: {"type": ptype, "description": desc}},
                "required": [pname] if required else [],
            },
        }

    def test_sql_param_with_sql_task(self):
        schema = self._schema("statement", desc="SQL query to execute")
        result = self._fn()(schema, "SELECT * FROM users WHERE active=1")
        assert result == {"statement": "SELECT * FROM users WHERE active=1"}

    def test_sql_param_with_nl_task_returns_empty(self):
        schema = self._schema("statement", desc="SQL query to execute")
        result = self._fn()(schema, "get all active users from the database")
        assert result == {}

    def test_shell_param_with_imperative_task(self):
        schema = self._schema("cmd", desc="Shell command to run")
        result = self._fn()(schema, "ls -la /tmp")
        assert result == {"cmd": "ls -la /tmp"}

    def test_shell_param_with_nl_task_returns_empty(self):
        schema = self._schema("cmd", desc="Shell command to run")
        result = self._fn()(schema, "list all files in /tmp")
        # "list" is an NL starter → should not fill shell_command
        assert result == {}

    def test_repo_param_extracts_owner_repo(self):
        schema = self._schema("repo", desc="GitHub repository (owner/repo)")
        result = self._fn()(schema, "check issues in kaiser-data/kitsune-mcp")
        assert result == {"repo": "kaiser-data/kitsune-mcp"}

    def test_repo_param_no_match_returns_empty(self):
        schema = self._schema("repo", desc="GitHub repository (owner/repo)")
        result = self._fn()(schema, "check my github issues")
        assert result == {}
