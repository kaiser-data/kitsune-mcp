"""Correctness fixes from the 2026-11-22 external reviews (batch 4a).

Grok #7, #13, #14, #19; Codex #19 / Grok #12.
"""

import json

import pytest

from kitsune_mcp.registry import MultiRegistry, ServerInfo
from kitsune_mcp.tools.onboarding import _looks_like_auth_failure


def _srv(id_, source, tools=None, install_cmd=None):
    return ServerInfo(
        id=id_,
        name=id_,
        description="",
        source=source,
        transport="stdio",
        install_cmd=install_cmd or ["uvx", id_],
        credentials={},
        tools=tools or [],
        token_cost=0,
    )


# --- Grok #7: a successful result that mentions 401 is not an auth failure --


@pytest.mark.parametrize(
    "text",
    [
        "Auth failed for EXA_API_KEY",
        "HTTP 401 Unauthorized",
        "Error: status 403 Forbidden",
        "OAuth failed for brave: invalid_grant",
        "Invalid token",
    ],
)
def test_auth_failure_messages_detected(text):
    assert _looks_like_auth_failure(text)


@pytest.mark.parametrize(
    "text",
    [
        '{"issues": [{"title": "Login returns 401 after upgrade"}]}',
        "Found 401 results for 'kitsune'",
        "Summary of the page.\n\nThe API answers 403 Forbidden when the key is missing.",
        "Line one is fine\nunauthorized access attempts: 3",
    ],
)
def test_successful_content_mentioning_auth_codes_not_a_failure(text):
    assert not _looks_like_auth_failure(text)


# --- Grok #13: a registry error must not be cached as "not found" ----------


class _Reg:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    async def get_server(self, id):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def _multi(*regs):
    m = MultiRegistry.__new__(MultiRegistry)
    MultiRegistry.__init__(m)
    m._registries = list(regs)
    m._reg_names = [f"r{i}" for i in range(len(regs))]
    return m


async def test_registry_error_not_cached_as_not_found():
    flaky = _Reg(exc=TimeoutError())
    miss = _Reg(result=None)
    m = _multi(flaky, miss)

    assert await m.get_server("x") is None
    flaky.exc, flaky.result = None, _srv("x", "mcpregistry")
    found = await m.get_server("x")
    assert found is not None and found.id == "x"


async def test_clean_miss_is_still_cached():
    miss = _Reg(result=None)
    m = _multi(miss)
    assert await m.get_server("x") is None
    assert await m.get_server("x") is None
    assert miss.calls == 1


# --- Grok #19: the user's absorbed config beats an official listing --------


async def test_absorbed_wins_over_official_same_id():
    official = _Reg(result=_srv("mcp-server-time", "official"))
    absorbed = _Reg(
        result=_srv("mcp-server-time", "absorbed", install_cmd=["uvx", "mcp-server-time", "--tz"])
    )
    m = _multi(official, absorbed)
    got = await m.get_server("mcp-server-time")
    assert got.source == "absorbed"


# --- Codex #19 / Grok #12: state.json is written atomically ----------------


def test_state_written_atomically(tmp_path, monkeypatch):
    from kitsune_mcp import session as sess

    path = tmp_path / "state.json"
    monkeypatch.setattr(sess, "_STATE_PATH", path)
    monkeypatch.setattr(sess, "_KITSUNE_HOME", tmp_path)

    replaced = []
    real_replace = sess.os.replace

    def _spy(src, dst):
        replaced.append((str(src), str(dst)))
        return real_replace(src, dst)

    monkeypatch.setattr(sess.os, "replace", _spy)
    sess._save_state()

    assert replaced and replaced[-1][1] == str(path)
    assert isinstance(json.loads(path.read_text()), dict)
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("*.tmp"))


# --- Grok #14: setup(name=) uses the argv connect() stored -----------------


async def test_setup_uses_stored_install_cmd(monkeypatch):
    import sys

    import kitsune_mcp.tools.onboarding  # noqa: F401

    ob = sys.modules["kitsune_mcp.tools.onboarding"]
    seen = {}

    class _T:
        def __init__(self, cmd, *a, **k):
            seen["cmd"] = cmd

        async def list_tools(self):
            raise RuntimeError("stop")

    monkeypatch.setattr(ob._state, "PersistentStdioTransport", _T)
    key = json.dumps(["uvx", "--from", "/path/with spaces", "server"])
    ob.session["connections"][key] = {
        "name": "dev",
        "command": 'uvx --from "/path/with spaces" server',
        "install_cmd": ["uvx", "--from", "/path/with spaces", "server"],
    }
    try:
        with pytest.raises(RuntimeError, match="stop"):
            await ob.setup(name="dev")
    finally:
        ob.session["connections"].pop(key, None)
    assert seen["cmd"] == ["uvx", "--from", "/path/with spaces", "server"]
