"""Last items from the first external review.

Grok #9 (guard argument shapes), Codex #18 (.env round trip),
Codex #20 (shed crafted tools for good), Codex #22 / Grok #15 (crafted headers).
"""

import io
from unittest.mock import MagicMock, patch

import pytest
from dotenv import dotenv_values

import kitsune_mcp.credentials as creds
import kitsune_mcp.session as sess_mod
from kitsune_mcp import shapeshift as core
from kitsune_mcp.guard import evaluate, parse_policy
from kitsune_mcp.session import session


def pol(**over):
    data = {"version": 1, "mode": "enforce", "default": "allow"}
    data.update(over)
    return parse_policy(data)


# --- Grok #9: guard sees paths after ; & | and in uri/host-shaped keys -------


@pytest.mark.parametrize(
    "command",
    ["cat /tmp/x;/etc/shadow", "cat /tmp/x&&/etc/shadow", "cat /tmp/x|/etc/shadow"],
)
def test_free_text_path_after_shell_separator_is_checked(command):
    v = evaluate(pol(paths={"write": ["/tmp"]}), "sh", "run", {"command": command})
    assert v.action == "block" and "/etc/shadow" in v.reason


@pytest.mark.parametrize("value", ["/etc/passwd", "file:///etc/passwd"])
def test_uri_key_is_a_path(value):
    v = evaluate(pol(paths={"write": ["/tmp"]}), "fs", "write_resource", {"uri": value})
    assert v.action == "block"


@pytest.mark.parametrize(
    "args",
    [{"host": "169.254.169.254"}, {"hostname": "evil.example"}, {"endpoint": "evil.example:8443"}],
)
def test_host_shaped_keys_are_checked_against_network_allow(args):
    v = evaluate(pol(network={"allow": ["github.com"]}), "net", "connect", args)
    assert v.action == "block" and v.stage == "host"


def test_allowed_host_key_passes():
    v = evaluate(pol(network={"allow": ["github.com"]}), "net", "connect", {"host": "github.com"})
    assert v.action != "block"


# --- Codex #18: .env values come back exactly as written --------------------


@pytest.mark.parametrize(
    "value",
    ["abc #def", '"quoted"', "it's", "back\\slash", "  spaced  ", "'single'", "$HOME", "x=y"],
)
def test_env_value_round_trips(value, tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(creds, "ENV_PATH", str(env))
    monkeypatch.delenv("ROUNDTRIP_TOKEN", raising=False)
    creds._save_to_env("ROUNDTRIP_TOKEN", "first")
    creds._save_to_env("ROUNDTRIP_TOKEN", value)  # replaces the existing line
    assert dotenv_values(env)["ROUNDTRIP_TOKEN"] == value
    assert env.read_text().count("ROUNDTRIP_TOKEN=") == 1


def test_env_value_with_interpolation_syntax_is_refused():
    assert "${" in (creds.invalid_env_entry("X_TOKEN", "pre${HOME}post") or "")


def test_env_encoding_matches_dotenv():
    for v in ["a'b", "c\\'d", "\\"]:
        line = f"K={creds._dotenv_quote(v)}\n"
        assert dotenv_values(stream=io.StringIO(line))["K"] == v


# --- Codex #20: a shed crafted tool is gone for good ------------------------


def test_shed_forgets_crafted_tools(monkeypatch):
    saved = MagicMock()
    monkeypatch.setattr(core, "_save_state", saved)
    monkeypatch.setattr(core.mcp, "remove_tool", MagicMock())
    session["crafted_tools"] = {"hook": {"url": "https://a.example", "method": "POST"}}
    session["shapeshift_tools"] = ["hook", "other"]
    try:
        core._do_shed()
        assert "hook" not in session["crafted_tools"]
        saved.assert_called()
    finally:
        session["crafted_tools"] = {}
        session["shapeshift_tools"] = []


# --- Codex #22 / Grok #15 + #20: restored crafted tools keep headers, are tracked


def test_restore_passes_headers_and_tracks_tools(monkeypatch):
    built = {}

    def fake_proxy(name, url, method, headers, params, description=""):
        built[name] = headers
        f = MagicMock()
        f.__name__ = name
        return f

    session["crafted_tools"] = {
        "api": {
            "url": "https://api.example/x",
            "method": "POST",
            "params": {},
            "description": "",
            "headers": {"Authorization": "Bearer T"},
        }
    }
    session["shapeshift_tools"] = []
    try:
        with (
            patch("kitsune_mcp.tools.shapeshift._make_endpoint_proxy", side_effect=fake_proxy),
            patch("kitsune_mcp.app.mcp.add_tool", MagicMock()),
        ):
            sess_mod._restore_crafted_tools()
        assert built["api"] == {"Authorization": "Bearer T"}
        assert "api" in session["shapeshift_tools"]
    finally:
        session["crafted_tools"] = {}
        session["shapeshift_tools"] = []


async def test_craft_persists_headers(monkeypatch):
    import sys

    import kitsune_mcp.tools.shapeshift  # noqa: F401

    ss = sys.modules["kitsune_mcp.tools.shapeshift"]
    monkeypatch.setattr(ss.mcp, "add_tool", MagicMock())
    try:
        await ss.craft(
            MagicMock(), "api2", "d", {}, "https://api.example/y", headers={"X-Key": "K"}
        )
        assert session["crafted_tools"]["api2"]["headers"] == {"X-Key": "K"}
    finally:
        session["crafted_tools"].pop("api2", None)
        session["shapeshift_tools"] = [t for t in session["shapeshift_tools"] if t != "api2"]
