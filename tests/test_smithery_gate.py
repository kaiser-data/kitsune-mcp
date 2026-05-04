"""Tests for v0.11.0 commit 3 — pre-flight Smithery cred gate.

Issue #8 reproduction: shapeshift onto a Smithery-hosted server succeeds
even when SMITHERY_API_KEY is missing; the user only learns this when the
first tool call fails with "Auth failed". The pre-flight gate fails fast
with an actionable message instead.
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def _ctx():
    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.send_tool_list_changed = AsyncMock()
    ctx.session.send_resource_list_changed = AsyncMock()
    ctx.session.send_prompt_list_changed = AsyncMock()
    return ctx


def _smithery_srv(server_id="smithery-server"):
    from kitsune_mcp.registry import ServerInfo
    return ServerInfo(
        id=server_id, name=server_id, description="Smithery-hosted",
        source="smithery", transport="http", url=f"https://server.smithery.ai/{server_id}",
        install_cmd=[], credentials={}, tools=[],
    )


@pytest.mark.asyncio
class TestSmitheryPreflightGate:
    async def test_smithery_without_key_fails_fast_with_actionable_message(self):
        """The headline issue #8 fix — agents see the auth gap BEFORE shapeshift,
        not after the first tool call."""
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        with patch.object(_registry, "get_server", AsyncMock(return_value=_smithery_srv())), \
             patch("kitsune_mcp.tools._state._smithery_available", return_value=False):
            result = await shapeshift("smithery-server", _ctx())

        assert result.startswith("❌")
        assert "SMITHERY_API_KEY" in result
        assert "smithery.ai/account/api-keys" in result
        # Must offer a workaround, not just block
        assert 'source="local"' in result

    async def test_smithery_with_key_proceeds_normally(self):
        """When SMITHERY_API_KEY IS set, the gate is transparent."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        srv = ServerInfo(
            id="smithery-server", name="smithery-server", description="",
            source="smithery", transport="http", url="https://server.smithery.ai/smithery-server",
            install_cmd=[], credentials={},
            tools=[{"name": "ping", "description": "", "inputSchema": {"type": "object", "properties": {}}}],
        )
        fake_transport = MagicMock()
        fake_transport.list_tools = AsyncMock(return_value=srv.tools)
        fake_transport.list_resources = AsyncMock(return_value=[])
        fake_transport.list_prompts = AsyncMock(return_value=[])

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("kitsune_mcp.tools._state._smithery_available", return_value=True), \
             patch("kitsune_mcp.tools._state._get_transport", return_value=fake_transport), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={"missing_env": []}):
            result = await shapeshift("smithery-server", _ctx())

        # Successful shapeshift starts with "Shapeshifted into ..."
        assert result.startswith("Shapeshifted")

    async def test_smithery_without_key_can_be_overridden_with_confirm(self):
        """confirm=True bypasses the pre-flight gate (matches existing pattern)."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        srv = ServerInfo(
            id="smithery-server", name="smithery-server", description="",
            source="smithery", transport="http", url="https://server.smithery.ai/smithery-server",
            install_cmd=[], credentials={},
            tools=[{"name": "ping", "description": "", "inputSchema": {"type": "object", "properties": {}}}],
        )
        fake_transport = MagicMock()
        fake_transport.list_tools = AsyncMock(return_value=srv.tools)
        fake_transport.list_resources = AsyncMock(return_value=[])
        fake_transport.list_prompts = AsyncMock(return_value=[])

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("kitsune_mcp.tools._state._smithery_available", return_value=False), \
             patch("kitsune_mcp.tools._state._get_transport", return_value=fake_transport), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={"missing_env": []}):
            result = await shapeshift("smithery-server", _ctx(), confirm=True)

        # Bypassed: shapeshift proceeds even without the key
        assert result.startswith("Shapeshifted")

    async def test_non_smithery_servers_unaffected(self):
        """The gate is Smithery-specific; npm/official sources skip it."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift
        from kitsune_mcp.tools._state import _registry

        # An npm-source server with no creds — should NOT trigger the Smithery gate
        srv = ServerInfo(
            id="npm-server", name="npm-server", description="",
            source="npm", transport="stdio",
            install_cmd=["npx", "-y", "npm-server"], credentials={},
            tools=[{"name": "ping", "description": "", "inputSchema": {"type": "object", "properties": {}}}],
        )
        fake_transport = MagicMock()
        fake_transport.list_tools = AsyncMock(return_value=srv.tools)
        fake_transport.list_resources = AsyncMock(return_value=[])
        fake_transport.list_prompts = AsyncMock(return_value=[])

        with patch.object(_registry, "get_server", AsyncMock(return_value=srv)), \
             patch("kitsune_mcp.tools._state._smithery_available", return_value=False), \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport", return_value=fake_transport), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={"missing_env": []}):
            # Pass confirm=True for community-source gate; that's not what's
            # under test here. We just need to bypass the OTHER gate.
            result = await shapeshift("npm-server", _ctx(), confirm=True)

        # Doesn't trigger Smithery message
        assert "SMITHERY_API_KEY" not in result
