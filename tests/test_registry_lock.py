"""Tests for _registry_lock — concurrent shapeshift/shiftback safety."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kitsune_mcp.app import _registry_lock
from kitsune_mcp.session import session


def _reset_session():
    session["shapeshift_tools"] = []
    session["shapeshift_resources"] = []
    session["shapeshift_prompts"] = []
    session["current_form"] = None
    session["current_form_pool_key"] = None
    session["current_form_local_install"] = None
    session["crafted_tools"] = {}
    session["grown"] = {}


# --- Lock exists and is an asyncio.Lock ---

def test_registry_lock_exists():
    assert _registry_lock is not None
    assert isinstance(_registry_lock, asyncio.Lock)


# --- Concurrent shapeshifts are serialised ---

@pytest.mark.asyncio
async def test_concurrent_shapeshifts_are_serialised():
    """Two concurrent shapeshifts must not leave both servers' tools mounted.

    Without the lock, Task A sheds, Task B sheds (no-op), A registers, B registers —
    leaving both servers' tools in the registry but session only tracking B's.
    With the lock, they run sequentially and the final state is consistent.
    """
    _reset_session()

    order = []

    async def fake_shapeshift(name: str, tool_names: list[str]):
        async with _registry_lock:
            order.append(f"{name}:shed")
            # Simulate I/O between shed and register (this is the race window)
            await asyncio.sleep(0)
            order.append(f"{name}:register")
            session["shapeshift_tools"] = tool_names
            session["current_form"] = name

    await asyncio.gather(
        fake_shapeshift("server-a", ["tool_a1", "tool_a2"]),
        fake_shapeshift("server-b", ["tool_b1"]),
    )

    # With the lock, one shapeshift completes fully before the other starts
    assert order.index("server-a:shed") < order.index("server-a:register") or \
           order.index("server-b:shed") < order.index("server-b:register")

    # The winner runs completely before the loser starts
    a_shed, a_reg = order.index("server-a:shed"), order.index("server-a:register")
    b_shed, b_reg = order.index("server-b:shed"), order.index("server-b:register")
    assert a_reg < b_shed or b_reg < a_shed, \
        f"Interleaved: {order} — lock did not serialise the operations"

    # Final session state is consistent with the last winner
    assert session["current_form"] in ("server-a", "server-b")
    if session["current_form"] == "server-a":
        assert session["shapeshift_tools"] == ["tool_a1", "tool_a2"]
    else:
        assert session["shapeshift_tools"] == ["tool_b1"]


# --- shiftback sees consistent state ---

@pytest.mark.asyncio
async def test_shiftback_sees_post_shapeshift_tools():
    """shiftback() acquires the same lock, so it always sees a fully registered form."""
    _reset_session()

    async def fake_shapeshift():
        async with _registry_lock:
            await asyncio.sleep(0)  # yield inside lock
            session["shapeshift_tools"] = ["mounted_tool"]
            session["current_form"] = "some-server"

    async def fake_shiftback():
        async with _registry_lock:
            tools = list(session["shapeshift_tools"])
            session["shapeshift_tools"] = []
            session["current_form"] = None
            return tools

    # Run shapeshift first, then shiftback — both through the lock
    await fake_shapeshift()
    removed = await fake_shiftback()
    assert removed == ["mounted_tool"]
    assert session["shapeshift_tools"] == []
    assert session["current_form"] is None


# --- source='local' + HTTP-only returns error WITHOUT shedding current form ---

@pytest.mark.asyncio
async def test_local_http_only_error_does_not_shed_current_form():
    """source='local' on HTTP-only server must return error before touching the registry."""
    from kitsune_mcp.tools.shapeshift import shapeshift

    _reset_session()
    session["shapeshift_tools"] = ["existing_tool"]
    session["current_form"] = "current-server"

    mock_srv = MagicMock()
    mock_srv.transport = "http"
    mock_srv.install_cmd = []  # empty — HTTP-only
    mock_srv.source = "smithery"
    mock_srv.credentials = {}
    mock_srv.tools = [{"name": "tool1", "description": "t", "inputSchema": {}}]

    mock_ctx = MagicMock()
    mock_ctx.session = AsyncMock()

    with (
        patch("kitsune_mcp.tools.shapeshift._state") as mock_state,
        patch("kitsune_mcp.tools.shapeshift.session", session),
    ):
        mock_state._registry = AsyncMock()
        mock_state._registry.get_server = AsyncMock(return_value=mock_srv)
        mock_state._smithery_available = MagicMock(return_value=True)
        mock_state._resolve_config = MagicMock(return_value=({}, {}))
        mock_state._do_shed = MagicMock()

        result = await shapeshift("upstash/context7-mcp", mock_ctx, source="local", confirm=True)

    # Must return an error
    assert "source='local' not available" in result or "HTTP-only" in result

    # Must NOT have called _do_shed — current form is preserved
    mock_state._do_shed.assert_not_called()
    assert session["shapeshift_tools"] == ["existing_tool"]
    assert session["current_form"] == "current-server"
