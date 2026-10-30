"""P0: credential values must not be able to inject extra lines into ~/.kitsune/.env.

A value containing a newline would otherwise add a second line such as
KITSUNE_SANDBOX=off, which dotenv then loads, bypassing the protected-name check.
"""

import os
from unittest.mock import patch

import pytest

from kitsune_mcp.credentials import InvalidEnvEntryError, _save_to_env


@pytest.mark.parametrize(
    "value", ["abc\nKITSUNE_SANDBOX=off", "abc\rKITSUNE_TRUST=community", "abc\x00def"]
)
def test_save_to_env_rejects_line_breaking_values(tmp_path, monkeypatch, value):
    env_file = tmp_path / ".env"
    monkeypatch.delenv("SOME_API_KEY", raising=False)
    with patch("kitsune_mcp.credentials.ENV_PATH", str(env_file)):
        with pytest.raises(InvalidEnvEntryError):
            _save_to_env("SOME_API_KEY", value)
    assert not env_file.exists()
    assert "SOME_API_KEY" not in os.environ


@pytest.mark.parametrize(
    "name", ["BAD NAME", "BAD=NAME", "1STARTS_WITH_DIGIT", "", "X\nKITSUNE_SANDBOX"]
)
def test_save_to_env_rejects_invalid_names(tmp_path, name):
    env_file = tmp_path / ".env"
    with patch("kitsune_mcp.credentials.ENV_PATH", str(env_file)):
        with pytest.raises(InvalidEnvEntryError):
            _save_to_env(name, "value")
    assert not env_file.exists()


def test_save_to_env_still_writes_normal_values(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.delenv("SOME_API_KEY", raising=False)
    with patch("kitsune_mcp.credentials.ENV_PATH", str(env_file)):
        _save_to_env("SOME_API_KEY", "sk-abc=123")
    assert env_file.read_text() == "SOME_API_KEY=sk-abc=123\n"
    assert oct(env_file.stat().st_mode & 0o777) == "0o600"
    monkeypatch.delenv("SOME_API_KEY", raising=False)


@pytest.mark.asyncio
async def test_key_tool_reports_invalid_value_instead_of_raising(monkeypatch):
    from kitsune_mcp.tools.onboarding import key

    monkeypatch.delenv("SOME_API_KEY", raising=False)
    with patch("kitsune_mcp.credentials.ENV_PATH", "/nonexistent/.env"):
        result = await key("SOME_API_KEY", "abc\nKITSUNE_SANDBOX=off")
    assert "Blocked" in result
    assert "SOME_API_KEY" not in os.environ
    assert os.getenv("KITSUNE_SANDBOX") != "off"


@pytest.mark.asyncio
async def test_auth_tool_reports_invalid_value_instead_of_raising(monkeypatch):
    from kitsune_mcp.tools.onboarding import auth

    monkeypatch.delenv("SOME_API_KEY", raising=False)
    with patch("kitsune_mcp.credentials.ENV_PATH", "/nonexistent/.env"):
        result = await auth("SOME_API_KEY", "abc\nKITSUNE_SANDBOX=off")
    assert "Blocked" in result
    assert "SOME_API_KEY" not in os.environ
