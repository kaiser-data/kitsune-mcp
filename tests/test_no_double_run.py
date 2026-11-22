"""A tool call that may have run is never sent again (review 2: Codex #1, #2, #3)."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import kitsune_mcp.credentials as _creds
from kitsune_mcp.registry import ServerInfo
from kitsune_mcp.transport import PersistentStdioTransport, _as_text, _PoolEntry, _process_pool

from .conftest import make_mock_process

_SCHEMA = {
    "name": "search",
    "inputSchema": {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
}


def _srv(id_, credentials=None):
    return ServerInfo(
        id=id_,
        name=id_,
        description="",
        source="mcpregistry",
        transport="http",
        url=f"https://{id_}.example/mcp",
        install_cmd=[],
        credentials=credentials or {},
        tools=[_SCHEMA],
    )


def _ok(text):
    return {"content": [{"type": "text", "text": text}]}


async def _run_auto(servers, outcomes, monkeypatch):
    """Run auto() over *servers*; outcomes[id] is what that server's call returns."""
    monkeypatch.delenv("B_TOKEN", raising=False)
    calls: list[str] = []
    by_id = {s.id: s for s in servers}

    def make_transport(server_id, srv):
        t = MagicMock()

        async def call_tool(tool, args, config):
            calls.append(server_id)
            return outcomes[server_id]

        async def execute(tool, args, config):
            return _as_text(await call_tool(tool, args, config))

        t.call_tool = call_tool
        t.execute = execute
        return t

    with (
        patch("kitsune_mcp.tools._state._registry") as reg,
        patch("kitsune_mcp.tools._state.shutil.which", return_value=None),
        patch("kitsune_mcp.tools._state._get_transport", side_effect=make_transport),
    ):
        reg.search = AsyncMock(return_value=servers)
        reg.get_server = AsyncMock(side_effect=lambda sid, source_preference=None: by_id.get(sid))
        from kitsune_mcp.tools import auto

        result = await auto(task="web search", arguments={"query": "x"})
    return calls, result


class TestAutoFallback:
    async def test_successful_result_mentioning_unauthorized_is_not_retried(self, monkeypatch):
        calls, result = await _run_auto(
            [_srv("a"), _srv("c")],
            {"a": _ok("Created issue #12: Unauthorized login investigation"), "c": _ok("c ran")},
            monkeypatch,
        )
        assert calls == ["a"], "a successful call was repeated on another server"
        assert "Created issue #12" in result

    async def test_error_result_with_auth_failure_falls_back(self, monkeypatch):
        calls, result = await _run_auto(
            [_srv("a"), _srv("c")],
            {"a": {**_ok("HTTP 401 Unauthorized"), "isError": True}, "c": _ok("c ran")},
            monkeypatch,
        )
        assert calls == ["a", "c"]
        assert "c ran" in result

    async def test_skipping_unusable_fallback_does_not_rerun_first(self, monkeypatch):
        calls, result = await _run_auto(
            [_srv("a"), _srv("b", {"B_TOKEN": "token for b"}), _srv("c")],
            {"a": "Auth failed for a", "b": _ok("b ran"), "c": _ok("c ran")},
            monkeypatch,
        )
        assert calls.count("a") == 1, f"provider a ran again: {calls}"
        assert "b" not in calls
        assert calls == ["a", "c"]

    async def test_no_usable_fallback_stops_after_first(self, monkeypatch):
        calls, result = await _run_auto(
            [_srv("a"), _srv("b", {"B_TOKEN": "token for b"})],
            {"a": "Auth failed for a", "b": _ok("b ran")},
            monkeypatch,
        )
        assert calls == ["a"]
        assert "Auth failed for a" in result


class TestStdioDrainFailure:
    @pytest.mark.parametrize("exc", [BrokenPipeError, ConnectionResetError])
    async def test_drain_failure_after_write_is_outcome_unknown(self, exc):
        t = PersistentStdioTransport(["drain-cmd"])
        proc = make_mock_process()
        proc.stdin.drain = AsyncMock(side_effect=exc())
        e = _PoolEntry(proc=proc, install_cmd=["drain-cmd"], started_at=time.monotonic())
        e.dotenv_revision = _creds._dotenv_revision
        _process_pool[t._pool_key] = e
        start = AsyncMock()
        with patch.object(t, "_start_process", start):
            result = await t.execute("charge", {"amount": 5}, {})
        assert "outcome unknown" in result and "charge" in result
        start.assert_not_called()
        writes = [json.loads(c.args[0]) for c in proc.stdin.write.call_args_list]
        assert [w["method"] for w in writes] == ["tools/call"]

    async def test_write_failure_before_anything_sent_still_retries(self):
        t = PersistentStdioTransport(["write-cmd"])
        flaky = make_mock_process()
        flaky.stdin.write = MagicMock(side_effect=BrokenPipeError())
        good = make_mock_process()
        from .conftest import make_stdout_with_responses

        good.stdout = make_stdout_with_responses(
            [{"jsonrpc": "2.0", "id": 3, "result": _ok("ran once")}]
        )
        entries = [
            _PoolEntry(proc=p, install_cmd=["write-cmd"], started_at=time.monotonic())
            for p in (flaky, good)
        ]
        with (
            patch.object(t, "_get_or_start", AsyncMock(side_effect=entries)),
            patch("kitsune_mcp.transport._kill_process_tree", MagicMock()),
        ):
            result = await t.execute("charge", {}, {})
        assert "ran once" in result
