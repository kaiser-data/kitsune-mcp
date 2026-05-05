"""Tests for issues #12, #13, #14, #15."""
import os
import stat
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --- #12: __version__ ---

def test_version_attr_exists():
    import kitsune_mcp
    assert kitsune_mcp.__version__ is not None
    assert kitsune_mcp.__version__ != ""


def test_version_is_string():
    import kitsune_mcp
    assert isinstance(kitsune_mcp.__version__, str)


# --- #13: .env file permissions and key() masking ---

def test_save_to_env_sets_restrictive_permissions(tmp_path):
    env_file = tmp_path / ".env"
    with patch("kitsune_mcp.credentials.ENV_PATH", str(env_file)):
        from kitsune_mcp.credentials import _save_to_env
        _save_to_env("TEST_KEY", "secret123")
        mode = stat.S_IMODE(os.stat(str(env_file)).st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


def test_save_to_env_chmod_on_update(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=val\n")
    os.chmod(str(env_file), 0o644)  # start with loose permissions
    with patch("kitsune_mcp.credentials.ENV_PATH", str(env_file)):
        from kitsune_mcp.credentials import _save_to_env
        _save_to_env("NEW_KEY", "newval")
        mode = stat.S_IMODE(os.stat(str(env_file)).st_mode)
        assert mode == 0o600


@pytest.mark.asyncio
async def test_key_tool_returns_masked_value():
    from kitsune_mcp.tools.onboarding import key
    with (
        patch("kitsune_mcp.tools.onboarding._save_to_env"),
        patch("kitsune_mcp.tools.onboarding._state") as mock_state,
    ):
        mock_state._registry.bust_cache = MagicMock()
        result = await key("MY_API_KEY", "sm-abc123secret")
    assert "sm-a" in result
    assert "sm-abc123secret" not in result
    assert "***" in result
    assert "0o600" in result


@pytest.mark.asyncio
async def test_key_tool_short_value_masked():
    from kitsune_mcp.tools.onboarding import key
    with (
        patch("kitsune_mcp.tools.onboarding._save_to_env"),
        patch("kitsune_mcp.tools.onboarding._state") as mock_state,
    ):
        mock_state._registry.bust_cache = MagicMock()
        result = await key("MY_KEY", "abc")
    assert "abc" not in result
    assert "***" in result


# --- #14: _infer_args_from_task multiple required strings ---

def test_infer_returns_empty_for_multiple_required_strings():
    from kitsune_mcp.tools.onboarding import _infer_args_from_task
    schema = {
        "name": "translate",
        "inputSchema": {
            "properties": {
                "text": {"type": "string"},
                "target_language": {"type": "string"},
            },
            "required": ["text", "target_language"],
        },
    }
    result = _infer_args_from_task(schema, "hello world")
    assert result == {}, f"Expected {{}} for ambiguous multi-string schema, got {result}"


def test_infer_still_works_for_single_required_string():
    from kitsune_mcp.tools.onboarding import _infer_args_from_task
    schema = {
        "name": "search",
        "inputSchema": {
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
    result = _infer_args_from_task(schema, "python tutorials")
    assert result == {"query": "python tutorials"}


def test_infer_returns_empty_for_zero_required_strings():
    from kitsune_mcp.tools.onboarding import _infer_args_from_task
    schema = {
        "name": "ping",
        "inputSchema": {"properties": {}, "required": []},
    }
    result = _infer_args_from_task(schema, "anything")
    assert result == {}


def test_infer_common_name_beats_fallback_for_single():
    from kitsune_mcp.tools.onboarding import _infer_args_from_task
    schema = {
        "name": "find",
        "inputSchema": {
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    }
    result = _infer_args_from_task(schema, "cats")
    assert result == {"text": "cats"}


# --- #15: auto() surfaces registry failures ---

@pytest.mark.asyncio
async def test_auto_surfaces_registry_errors_on_no_tools():
    from kitsune_mcp.tools.onboarding import auto

    mock_srv = MagicMock()
    mock_srv.tools = []
    mock_srv.transport = "http"
    mock_srv.source = "smithery"
    mock_srv.id = "weathermap"
    mock_srv.name = "weathermap"
    mock_srv.credentials = {}

    mock_registry = AsyncMock()
    mock_registry.get_server = AsyncMock(return_value=mock_srv)
    mock_registry.last_registry_errors = {"glama": "HTTPStatusError", "mcpregistry": "HTTPStatusError"}

    with (
        patch("kitsune_mcp.tools.onboarding._state") as mock_state,
        patch("kitsune_mcp.credentials._smithery_available", return_value=False),
    ):
        mock_state._registry = mock_registry
        mock_state._resolve_config = MagicMock(return_value=({}, {}))
        result = await auto("weather in Tokyo", server_hint="weathermap")

    assert "could not fetch tool schema" in result
    assert "glama" in result or "mcpregistry" in result
    assert "SMITHERY_API_KEY" in result
    assert "key(" in result
