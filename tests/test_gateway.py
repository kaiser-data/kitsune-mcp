"""Tests for v0.20 Gateway Mode — config discovery, credential harvest, absorption."""

import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


class TestClientConfigPaths:
    def test_returns_dict(self):
        from kitsune_mcp.gateway import _client_config_paths
        result = _client_config_paths()
        assert isinstance(result, dict)

    def test_only_existing_paths_returned(self):
        from kitsune_mcp.gateway import _client_config_paths
        result = _client_config_paths()
        for path in result.values():
            assert path.exists(), f"{path} does not exist"


class TestParseMcpServers:
    def test_extracts_servers(self):
        from kitsune_mcp.gateway import _parse_mcp_servers
        config = {
            "mcpServers": {
                "brave-search": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-brave-search"],
                    "env": {"BRAVE_API_KEY": "sk-abc123"},
                },
                "kitsune": {
                    "command": "npx",
                    "args": ["-y", "kitsune-mcp"],
                },
            }
        }
        servers = _parse_mcp_servers(config, "claude-desktop")
        assert len(servers) == 2
        ids = {s.id for s in servers}
        assert ids == {"brave-search", "kitsune"}

    def test_client_field_set(self):
        from kitsune_mcp.gateway import _parse_mcp_servers
        servers = _parse_mcp_servers(
            {"mcpServers": {"x": {"command": "npx", "args": []}}}, "cursor"
        )
        assert servers[0].client == "cursor"

    def test_env_captured(self):
        from kitsune_mcp.gateway import _parse_mcp_servers
        servers = _parse_mcp_servers(
            {"mcpServers": {"s": {"command": "npx", "env": {"MY_API_KEY": "val"}}}},
            "claude-code",
        )
        assert servers[0].env == {"MY_API_KEY": "val"}

    def test_empty_mcpservers(self):
        from kitsune_mcp.gateway import _parse_mcp_servers
        assert _parse_mcp_servers({}, "claude-desktop") == []

    def test_non_dict_entry_skipped(self):
        from kitsune_mcp.gateway import _parse_mcp_servers
        servers = _parse_mcp_servers({"mcpServers": {"bad": "string"}}, "x")
        assert servers == []


class TestFindMcpConfigs:
    def test_returns_list(self):
        from kitsune_mcp.gateway import _find_mcp_configs
        result = _find_mcp_configs()
        assert isinstance(result, list)

    def test_with_fake_config(self, tmp_path):
        config = {"mcpServers": {"test-server": {"command": "npx", "args": []}}}
        cfg_file = tmp_path / "mcp.json"
        cfg_file.write_text(json.dumps(config))

        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"fake-client": cfg_file},
        ):
            result = _find_mcp_configs()

        assert len(result) == 1
        assert result[0].client == "fake-client"
        assert len(result[0].servers) == 1
        assert result[0].servers[0].id == "test-server"

    def test_unreadable_config_skipped(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json{{")

        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"bad-client": bad_file},
        ):
            result = _find_mcp_configs()

        assert result == []


class TestClaudeCodeUserConfig:
    """~/.claude.json (claude-code-user) discovery — issue #40."""

    def _write_claude_json(self, tmp_path, data):
        cfg_file = tmp_path / ".claude.json"
        cfg_file.write_text(json.dumps(data))
        return cfg_file

    def test_client_config_paths_includes_claude_json(self, tmp_path):
        from kitsune_mcp.gateway import _client_config_paths
        self._write_claude_json(tmp_path, {"mcpServers": {}})
        with patch("kitsune_mcp.gateway.Path.home", return_value=tmp_path):
            result = _client_config_paths()
        assert result.get("claude-code-user") == tmp_path / ".claude.json"

    def test_top_level_mcpservers_discovered(self, tmp_path):
        cfg_file = self._write_claude_json(
            tmp_path,
            {"mcpServers": {"notion": {"command": "npx", "args": ["-y", "notion-mcp"]}}},
        )
        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"claude-code-user": cfg_file},
        ):
            result = _find_mcp_configs()
        assert len(result) == 1
        assert result[0].client == "claude-code-user"
        assert {s.id for s in result[0].servers} == {"notion"}

    def test_project_scoped_servers_merged_for_cwd(self, tmp_path):
        import pathlib
        cfg_file = self._write_claude_json(
            tmp_path,
            {
                "mcpServers": {"notion": {"command": "npx"}},
                "projects": {
                    str(pathlib.Path.cwd()): {
                        "mcpServers": {"github": {"command": "npx"}}
                    },
                    "/some/other/project": {
                        "mcpServers": {"unrelated": {"command": "npx"}}
                    },
                },
            },
        )
        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"claude-code-user": cfg_file},
        ):
            result = _find_mcp_configs()
        ids = {s.id for s in result[0].servers}
        assert ids == {"notion", "github"}
        assert "unrelated" not in ids

    def test_project_entry_wins_over_top_level(self, tmp_path):
        import pathlib
        cfg_file = self._write_claude_json(
            tmp_path,
            {
                "mcpServers": {"github": {"command": "old-cmd"}},
                "projects": {
                    str(pathlib.Path.cwd()): {
                        "mcpServers": {"github": {"command": "new-cmd"}}
                    }
                },
            },
        )
        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"claude-code-user": cfg_file},
        ):
            result = _find_mcp_configs()
        assert len(result[0].servers) == 1
        assert result[0].servers[0].command == "new-cmd"

    def test_claude_json_wins_over_legacy_mcp_json(self, tmp_path):
        legacy_file = tmp_path / "mcp.json"
        legacy_file.write_text(json.dumps(
            {"mcpServers": {
                "github": {"command": "legacy-cmd"},
                "only-legacy": {"command": "npx"},
            }}
        ))
        cfg_file = self._write_claude_json(
            tmp_path, {"mcpServers": {"github": {"command": "modern-cmd"}}}
        )
        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"claude-code": legacy_file, "claude-code-user": cfg_file},
        ):
            result = _find_mcp_configs()
        all_servers = [s for cfg in result for s in cfg.servers]
        github = [s for s in all_servers if s.id == "github"]
        assert len(github) == 1, "duplicate server id must not be double-counted"
        assert github[0].command == "modern-cmd"
        assert {s.id for s in all_servers} == {"github", "only-legacy"}

    def test_legacy_config_dropped_when_fully_shadowed(self, tmp_path):
        legacy_file = tmp_path / "mcp.json"
        legacy_file.write_text(json.dumps(
            {"mcpServers": {"github": {"command": "legacy-cmd"}}}
        ))
        cfg_file = self._write_claude_json(
            tmp_path, {"mcpServers": {"github": {"command": "modern-cmd"}}}
        )
        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"claude-code": legacy_file, "claude-code-user": cfg_file},
        ):
            result = _find_mcp_configs()
        assert [cfg.client for cfg in result] == ["claude-code-user"]

    def test_malformed_projects_block_ignored(self, tmp_path):
        cfg_file = self._write_claude_json(
            tmp_path,
            {"mcpServers": {"notion": {"command": "npx"}}, "projects": "not-a-dict"},
        )
        from kitsune_mcp.gateway import _find_mcp_configs
        with patch(
            "kitsune_mcp.gateway._client_config_paths",
            return_value={"claude-code-user": cfg_file},
        ):
            result = _find_mcp_configs()
        assert {s.id for s in result[0].servers} == {"notion"}


class TestHarvestCredentials:
    def test_extracts_credential_keys(self):
        from kitsune_mcp.gateway import AbsorbedServer, _harvest_credentials
        servers = [
            AbsorbedServer(
                id="brave-search", command="npx",
                env={"BRAVE_API_KEY": "sk-abc", "LOGGING_LEVEL": "debug"},
                client="claude-desktop",
            )
        ]
        result = _harvest_credentials(servers)
        assert "BRAVE_API_KEY" in result
        assert result["BRAVE_API_KEY"] == "sk-abc"
        assert "LOGGING_LEVEL" not in result

    def test_skips_empty_values(self):
        from kitsune_mcp.gateway import AbsorbedServer, _harvest_credentials
        servers = [
            AbsorbedServer(id="x", command="npx", env={"MY_API_KEY": ""}, client="c")
        ]
        assert _harvest_credentials(servers) == {}

    def test_multiple_servers(self):
        from kitsune_mcp.gateway import AbsorbedServer, _harvest_credentials
        servers = [
            AbsorbedServer(id="a", command="n", env={"EXA_API_KEY": "exa-1"}, client="c"),
            AbsorbedServer(id="b", command="n", env={"NOTION_TOKEN": "ntn-2"}, client="c"),
        ]
        result = _harvest_credentials(servers)
        assert len(result) == 2


class TestAbsorbedServerPersistence:
    def test_save_and_load_roundtrip(self, tmp_path):
        from kitsune_mcp.gateway import (
            AbsorbedServer,
            _load_absorbed_servers,
            _save_absorbed_servers,
        )
        servers = [
            AbsorbedServer(
                id="my-server", command="npx", args=["-y", "my-pkg"],
                env={"MY_API_KEY": "v"}, client="claude-code", absorbed_at="2026-01-01T00:00:00",
            )
        ]
        absorbed_path = tmp_path / "absorbed_servers.json"
        with (
            patch("kitsune_mcp.gateway._KITSUNE_HOME", tmp_path),
            patch("kitsune_mcp.gateway._ABSORBED_PATH", absorbed_path),
        ):
            _save_absorbed_servers(servers)
            loaded = _load_absorbed_servers()

        assert len(loaded) == 1
        assert loaded[0].id == "my-server"
        assert loaded[0].command == "npx"

    def test_load_absent_file_returns_empty(self, tmp_path):
        from kitsune_mcp.gateway import _load_absorbed_servers
        with patch("kitsune_mcp.gateway._ABSORBED_PATH", tmp_path / "nonexistent.json"):
            assert _load_absorbed_servers() == []


class TestToServerInfo:
    def test_basic_conversion(self):
        from kitsune_mcp.gateway import AbsorbedServer, _to_server_info
        a = AbsorbedServer(
            id="my-pg", command="npx", args=["-y", "my-pg"],
            env={"DATABASE_URL": "postgresql://..."}, client="claude-desktop",
        )
        srv = _to_server_info(a)
        assert srv.id == "my-pg"
        assert srv.source == "absorbed"
        assert srv.transport == "stdio"
        assert "DATABASE_URL" not in srv.credentials  # not a CRED_SUFFIX match

    def test_credential_env_keys_extracted(self):
        from kitsune_mcp.gateway import AbsorbedServer, _to_server_info
        a = AbsorbedServer(
            id="s", command="n", args=[],
            env={"BRAVE_API_KEY": "x", "LOG": "debug"}, client="c",
        )
        srv = _to_server_info(a)
        assert "BRAVE_API_KEY" in srv.credentials
        assert "LOG" not in srv.credentials

    def test_install_cmd_built(self):
        from kitsune_mcp.gateway import AbsorbedServer, _to_server_info
        a = AbsorbedServer(id="s", command="npx", args=["-y", "pkg"], env={}, client="c")
        srv = _to_server_info(a)
        assert srv.install_cmd == ["npx", "-y", "pkg"]


class TestAbsorbedRegistry:
    def test_search_returns_absorbed_servers(self, tmp_path):
        import asyncio

        from kitsune_mcp.gateway import AbsorbedServer, _save_absorbed_servers
        from kitsune_mcp.registry import AbsorbedRegistry

        servers = [AbsorbedServer(id="my-tool", command="npx", args=[], env={}, client="c")]
        absorbed_path = tmp_path / "absorbed_servers.json"
        with (
            patch("kitsune_mcp.gateway._KITSUNE_HOME", tmp_path),
            patch("kitsune_mcp.gateway._ABSORBED_PATH", absorbed_path),
        ):
            _save_absorbed_servers(servers)
            reg = AbsorbedRegistry()
            results = asyncio.run(reg.search("my-tool", 10))

        assert any(r.id == "my-tool" for r in results)

    def test_get_server_found(self, tmp_path):
        import asyncio

        from kitsune_mcp.gateway import AbsorbedServer, _save_absorbed_servers
        from kitsune_mcp.registry import AbsorbedRegistry

        servers = [AbsorbedServer(id="found-me", command="npx", args=[], env={}, client="c")]
        absorbed_path = tmp_path / "absorbed_servers.json"
        with (
            patch("kitsune_mcp.gateway._KITSUNE_HOME", tmp_path),
            patch("kitsune_mcp.gateway._ABSORBED_PATH", absorbed_path),
        ):
            _save_absorbed_servers(servers)
            reg = AbsorbedRegistry()
            result = asyncio.run(reg.get_server("found-me"))

        assert result is not None
        assert result.id == "found-me"

    def test_get_server_missing_returns_none(self, tmp_path):
        import asyncio

        from kitsune_mcp.registry import AbsorbedRegistry

        absorbed_path = tmp_path / "absorbed_servers.json"
        with patch("kitsune_mcp.gateway._ABSORBED_PATH", absorbed_path):
            reg = AbsorbedRegistry()
            result = asyncio.run(reg.get_server("nope"))

        assert result is None


class TestIsCredentialKey:
    def test_api_key_matches(self):
        from kitsune_mcp.gateway import _is_credential_key
        assert _is_credential_key("BRAVE_API_KEY") is True
        assert _is_credential_key("NOTION_TOKEN") is True
        assert _is_credential_key("GITHUB_TOKEN") is True
        assert _is_credential_key("DB_PASSWORD") is True

    def test_non_credential_keys(self):
        from kitsune_mcp.gateway import _is_credential_key
        assert _is_credential_key("LOGGING_LEVEL") is False
        assert _is_credential_key("DATABASE_URL") is False
        assert _is_credential_key("PORT") is False
