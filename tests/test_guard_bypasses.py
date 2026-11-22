"""Guard bypasses from the 2026-11-22 external review (Codex): #1, #5, #10."""

import json

import pytest

from kitsune_mcp import guard
from kitsune_mcp.guard import evaluate, parse_policy


def pol(**over):
    data = {"version": 1, "mode": "enforce"}
    data.update(over)
    return parse_policy(data)


# --- #1: both ends of a move are paths ---------------------------------------


def test_move_source_is_checked(tmp_path, monkeypatch):
    monkeypatch.setenv("KITSUNE_HOME", str(tmp_path / "kh"))
    p = pol(default="allow", paths={"write": ["/tmp"]})
    v = evaluate(
        p,
        "fs",
        "move_file",
        {"source": str(tmp_path / "kh" / "policy.json"), "destination": "/tmp/saved.json"},
    )
    assert v.action == "block"


@pytest.mark.parametrize("key", ["source", "src", "target", "from", "to", "old_path", "new_path"])
def test_path_endpoint_keys_checked_when_value_is_a_path(key):
    p = pol(default="allow", paths={"write": ["/tmp"]})
    v = evaluate(p, "fs", "move_file", {key: "/etc/passwd", "destination": "/tmp/x"})
    assert v.action == "block"


def test_endpoint_keys_with_non_path_values_are_not_paths():
    # translate(target="es") and send_mail(to="a@b.c") must not become paths.
    p = pol(default="allow", paths={"write": ["/tmp"]})
    assert evaluate(p, "t", "translate_text", {"target": "es"}).action == "allow"
    assert evaluate(p, "m", "send_mail", {"to": "a@example.com"}).action == "allow"


def test_policy_removed_while_running_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("KITSUNE_HOME", str(tmp_path))
    guard._policy_cache.clear()
    monkeypatch.setattr(guard, "_policy_seen", set())
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({"version": 1, "mode": "enforce", "default": "allow"}))
    assert isinstance(guard.load_policy(), guard.Policy)

    policy_file.unlink()
    assert isinstance(guard.load_policy(), guard.PolicyError)


def test_no_policy_ever_means_guard_off(tmp_path, monkeypatch):
    monkeypatch.setenv("KITSUNE_HOME", str(tmp_path))
    guard._policy_cache.clear()
    monkeypatch.setattr(guard, "_policy_seen", set())
    assert guard.load_policy() is None


# --- #5: hosts come from a URL parser ----------------------------------------


@pytest.mark.parametrize(
    "url",
    ["https://evil.example?x=@allowed.example", "https://evil.example#@allowed.example"],
)
def test_query_or_fragment_at_sign_does_not_fake_the_host(url):
    p = pol(default="allow", network={"allow": ["allowed.example"]})
    assert evaluate(p, "web", "fetch", {"url": url}).action == "block"


def test_explicit_url_host_ending_in_file_extension_is_checked():
    p = pol(default="allow", network={"allow": ["allowed.example"]})
    assert evaluate(p, "web", "fetch", {"url": "https://files.zip/payload"}).action == "block"


def test_userinfo_host_still_parsed_correctly():
    p = pol(default="allow", network={"allow": ["allowed.example"]})
    v = evaluate(p, "web", "fetch", {"url": "https://user@allowed.example/x"})
    assert v.action == "allow"


# --- #10: crafted tools go through the guard ----------------------------------


async def test_crafted_tool_consults_guard(monkeypatch, respx_mock):
    import sys

    import httpx

    import kitsune_mcp.tools.shapeshift  # noqa: F401  (package re-exports a function of that name)

    ss = sys.modules["kitsune_mcp.tools.shapeshift"]

    seen = {}

    async def _block(server_id, tool, args):
        seen.update(server_id=server_id, tool=tool, args=args)
        return "⛔ Blocked by Kitsune guard"

    monkeypatch.setattr(ss, "guard_call", _block)
    route = respx_mock.post("https://api.example.com/hook").mock(return_value=httpx.Response(200))

    proxy = ss._make_endpoint_proxy("hook", "https://api.example.com/hook", "POST", {}, {})
    result = await proxy(text="hi")

    assert "Blocked" in result
    assert not route.called
    assert seen["server_id"] == "craft"
    assert seen["args"]["url"] == "https://api.example.com/hook"
