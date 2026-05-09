"""Session persistence tests — crafted_tools and connections survive restart."""

import json
import pytest


@pytest.fixture(autouse=True)
def _patch_state_path(tmp_path, monkeypatch):
    """Redirect _STATE_PATH to a temp file for each test."""
    import kitsune_mcp.session as sess_mod
    monkeypatch.setattr(sess_mod, "_STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(sess_mod, "_KITSUNE_HOME", tmp_path)
    # Reset crafted_tools / connections / explored before each test
    sess_mod.session["crafted_tools"] = {}
    sess_mod.session["connections"] = {}
    sess_mod.session["explored"] = {}
    yield


def test_save_load_crafted_tools(tmp_path):
    from kitsune_mcp.session import _load_state, _save_state, session
    session["crafted_tools"] = {
        "my_tool": {"url": "https://example.com/api", "method": "POST",
                    "description": "test tool", "params": {}}
    }
    _save_state()
    session["crafted_tools"] = {}
    _load_state()
    assert "my_tool" in session["crafted_tools"]
    assert session["crafted_tools"]["my_tool"]["url"] == "https://example.com/api"


def test_pids_not_persisted(tmp_path):
    from kitsune_mcp.session import _load_state, _save_state, session
    session["connections"] = {
        "key1": {"name": "test", "pid": 12345, "command": "npx foo", "started_at": "2026-01-01"}
    }
    _save_state()
    session["connections"] = {}
    _load_state()
    assert "key1" in session["connections"]
    assert "pid" not in session["connections"]["key1"]
    assert "started_at" not in session["connections"]["key1"]
    assert session["connections"]["key1"]["name"] == "test"


def test_explored_capped_at_100(tmp_path):
    from kitsune_mcp.session import _load_state, _save_state, session
    session["explored"] = {str(i): {"name": f"server-{i}"} for i in range(150)}
    _save_state()
    session["explored"] = {}
    _load_state()
    # Only the last 100 entries are kept
    assert len(session["explored"]) == 100
    # Most recent 100 (indices 50-149)
    assert "149" in session["explored"]
    assert "0" not in session["explored"]


def test_corrupt_state_is_ignored(tmp_path, monkeypatch):
    import kitsune_mcp.session as sess_mod
    state_path = tmp_path / "state.json"
    state_path.write_text("not valid json")
    monkeypatch.setattr(sess_mod, "_STATE_PATH", state_path)
    # Should not raise
    sess_mod._load_state()
    assert sess_mod.session["crafted_tools"] == {}


def test_missing_state_file_is_ignored(tmp_path):
    from kitsune_mcp.session import _load_state, session
    _load_state()  # file doesn't exist — should not raise
    assert session["crafted_tools"] == {}
