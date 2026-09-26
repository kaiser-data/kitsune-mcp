"""Protected env vars — the agent must not be able to set Kitsune's own policy
knobs or process-launch levers through auth()/key()/auto(keys=)/harvest.

Values written by _save_to_env land in os.environ, and unsandboxed stdio servers
inherit the whole host environment, so e.g. NODE_OPTIONS or PIP_INDEX_URL are
code-execution / supply-chain levers, and KITSUNE_TRUST / KITSUNE_SANDBOX switch
off the trust gate and the Docker cage.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from kitsune_mcp.credentials import ProtectedEnvVarError, _save_to_env, is_protected_env_var


@pytest.mark.parametrize(
    "name",
    [
        "KITSUNE_TRUST",
        "KITSUNE_SANDBOX",
        "KITSUNE_ALLOW_LOCAL_FETCH",
        "kitsune_trust",
        "NODE_OPTIONS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "PIP_INDEX_URL",
        "UV_INDEX_URL",
        "NPM_CONFIG_REGISTRY",
        "DOCKER_HOST",
        "GIT_SSH_COMMAND",
        "PATH",
        "HOME",
        "BASH_ENV",
        "HTTPS_PROXY",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    ],
)
def test_protected_names(name):
    assert is_protected_env_var(name)


@pytest.mark.parametrize(
    "name",
    [
        "GITHUB_TOKEN",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "EXA_API_KEY",
        "SMITHERY_API_KEY",
        "DATABASE_URL",
    ],
)
def test_credentials_are_not_protected(name):
    assert not is_protected_env_var(name)


def test_save_to_env_refuses_protected(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    monkeypatch.delenv("KITSUNE_TRUST", raising=False)
    with patch("kitsune_mcp.credentials.ENV_PATH", str(env_file)):
        with pytest.raises(ProtectedEnvVarError):
            _save_to_env("KITSUNE_TRUST", "community")
    assert not env_file.exists()
    assert "KITSUNE_TRUST" not in os.environ


@pytest.mark.asyncio
async def test_auth_refuses_protected(monkeypatch):
    from kitsune_mcp.tools.onboarding import auth

    monkeypatch.delenv("KITSUNE_TRUST", raising=False)
    with patch("kitsune_mcp.credentials.ENV_PATH", "/nonexistent/.env"):
        result = await auth("KITSUNE_TRUST", "community")
    assert "Blocked" in result
    assert "KITSUNE_TRUST" not in os.environ


@pytest.mark.asyncio
async def test_key_refuses_protected(monkeypatch):
    from kitsune_mcp.tools.onboarding import key

    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    with patch("kitsune_mcp.tools.onboarding._state") as mock_state:
        mock_state._registry.bust_cache = MagicMock()
        result = await key("NODE_OPTIONS", "--require /tmp/x.js")
    assert "Blocked" in result
    assert "NODE_OPTIONS" not in os.environ


@pytest.mark.asyncio
async def test_auto_keys_refuses_protected(monkeypatch):
    from kitsune_mcp.tools.onboarding import auto

    monkeypatch.delenv("KITSUNE_SANDBOX", raising=False)
    result = await auto("what time is it", keys={"KITSUNE_SANDBOX": "0"})
    assert "Blocked" in result
    assert "KITSUNE_SANDBOX" not in os.environ


def test_trust_hints_do_not_tell_the_agent_to_self_approve():
    """The trust-gate messages used to suggest auth("KITSUNE_TRUST", ...) to the agent."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "kitsune_mcp"
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if 'auth("KITSUNE_' in p.read_text() or 'key("KITSUNE_' in p.read_text()
    ]
    assert offenders == []
