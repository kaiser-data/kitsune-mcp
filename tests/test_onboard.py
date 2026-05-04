"""Tests for v0.11.0 commit 4 — onboard() first-run wizard."""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.mark.asyncio
class TestOnboard:
    async def test_shows_provider_section_first(self):
        from kitsune_mcp.tools import onboard
        with patch("kitsune_mcp.tools.onboarding._smithery_available", return_value=True):
            result = await onboard()
        assert "PROVIDERS" in result
        # PROVIDERS must come before "FASTEST PATH"
        assert result.index("PROVIDERS") < result.index("FASTEST PATH")

    async def test_smithery_unconfigured_shows_upgrade_path(self):
        from kitsune_mcp.tools import onboard
        with patch("kitsune_mcp.tools.onboarding._smithery_available", return_value=False):
            result = await onboard()
        assert "🔑" in result
        assert "smithery.ai/account/api-keys" in result
        assert "UPGRADE PATH" in result

    async def test_smithery_configured_no_upgrade_section(self):
        from kitsune_mcp.tools import onboard
        with patch("kitsune_mcp.tools.onboarding._smithery_available", return_value=True):
            result = await onboard()
        assert "UPGRADE PATH" not in result

    async def test_recommends_zero_config_servers(self):
        """Free-tier list must be present — these are the no-API-key servers
        that get a new user to a working call in <3 steps."""
        from kitsune_mcp.tools import onboard
        with patch("kitsune_mcp.tools.onboarding._smithery_available", return_value=True):
            result = await onboard()
        # Must mention at least the time server (the headline 3-step check)
        assert "mcp-server-time" in result
        assert "shapeshift" in result

    async def test_includes_3_step_verification(self):
        """The "if step 2 returns a timestamp" sanity check is explicit."""
        from kitsune_mcp.tools import onboard
        with patch("kitsune_mcp.tools.onboarding._smithery_available", return_value=True):
            result = await onboard()
        assert "3-STEP CHECK" in result
        assert 'call("get_current_time"' in result
        assert "shiftback()" in result

    async def test_kitsune_trust_env_warning_appears_when_set(self):
        from kitsune_mcp.tools import onboard
        with patch.dict(os.environ, {"KITSUNE_TRUST": "community"}), \
             patch("kitsune_mcp.tools.onboarding._smithery_available", return_value=True):
            result = await onboard()
        assert "KITSUNE_TRUST" in result
        assert "community" in result.lower()
