"""Tests for UX friction-reduction changes (Changes 1–8 + uninstall).

Covers:
- _credentials_ready() helper
- _infer_install_cmd() helper
- _local_uninstall_cmd() helper
- status() first-run onboarding
- shapeshift() source='local' confirmation gate
- shapeshift() credential check before _do_shed (bug fix)
- shapeshift() lean hint when >4 tools loaded
- KITSUNE_TRUST env var bypasses community/local gate
- shiftback(uninstall=True) for uvx and npx packages
- shiftback() with local install but no uninstall → hint in output
- MultiRegistry last_registry_errors populated on failure
- search() reports registry failures via ⚠️ Skipped:
"""
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helper: _credentials_ready
# ---------------------------------------------------------------------------

class TestCredentialsReady:
    def setup_method(self):
        # Make sure we're not leaking env vars between tests
        os.environ.pop("API_KEY", None)
        os.environ.pop("TEST_TOKEN", None)

    def test_no_credentials_official_source_is_free(self):
        # v0.11.0: official sources without creds are explicit "free", not the
        # ambiguous "no creds declared" that misled users in v0.10.x.
        from kitsune_mcp.credentials import _credentials_ready
        result = _credentials_ready({}, "official")
        assert "free" in result
        assert "✅" in result

    def test_smithery_without_key_says_needs_smithery_api_key(self):
        # v0.11.0 fix for issue #8: Smithery-hosted servers always need
        # SMITHERY_API_KEY regardless of whether per-server creds are declared.
        # Old "no creds declared (may use OAuth)" silently led users into walls.
        from unittest.mock import patch
        from kitsune_mcp.credentials import _credentials_ready
        # Patch _smithery_available so the test isn't affected by a real .env
        # file that may have a key set.
        with patch("kitsune_mcp.credentials._smithery_available", return_value=False):
            result = _credentials_ready({}, "smithery")
        assert "SMITHERY_API_KEY" in result
        assert "🔑" in result

    def test_smithery_with_key_set_shows_env_set(self):
        from unittest.mock import patch
        from kitsune_mcp.credentials import _credentials_ready
        with patch("kitsune_mcp.credentials._smithery_available", return_value=True):
            result = _credentials_ready({}, "smithery")
        assert "env set" in result
        assert "✓" in result

    def test_no_credentials_community_source_warns(self):
        # npm/pypi/github without declared creds — undeclared ≠ free.
        from kitsune_mcp.credentials import _credentials_ready
        result = _credentials_ready({}, "npm")
        assert "community" in result
        assert "⚠" in result

    def test_glama_without_creds_warns(self):
        # mcpregistry/glama without declared creds — same warning tier.
        from kitsune_mcp.credentials import _credentials_ready
        result = _credentials_ready({}, "glama")
        # mcpregistry/glama are TRUST_MEDIUM but not Smithery-tagged → may need OAuth
        assert "🔑" in result

    def test_credential_present_in_env_returns_set(self):
        from kitsune_mcp.credentials import _credentials_ready
        os.environ["API_KEY"] = "sk-test"
        try:
            result = _credentials_ready({"apiKey": "Your API key"})
            assert "✓" in result
            assert "env set" in result
        finally:
            del os.environ["API_KEY"]

    def test_credential_missing_returns_needs(self):
        from kitsune_mcp.credentials import _credentials_ready
        os.environ.pop("API_KEY", None)
        result = _credentials_ready({"apiKey": "Your API key"})
        assert "🔑" in result
        assert "API_KEY" in result

    def test_multiple_missing_shows_all(self):
        from kitsune_mcp.credentials import _credentials_ready
        os.environ.pop("API_KEY", None)
        os.environ.pop("AUTH_TOKEN", None)
        # Use creds that generate env vars matching CRED_SUFFIXES patterns
        result = _credentials_ready({"apiKey": "key", "authToken": "tok"})
        assert "🔑" in result
        assert "API_KEY" in result
        assert "AUTH_TOKEN" in result


# ---------------------------------------------------------------------------
# Helper: _infer_install_cmd
# ---------------------------------------------------------------------------

class TestInferInstallCmd:
    def _fn(self):
        from kitsune_mcp.tools import _infer_install_cmd
        return _infer_install_cmd

    def test_at_scope_package_uses_npx(self):
        fn = self._fn()
        assert fn("@scope/pkg") == ["npx", "-y", "@scope/pkg"]

    def test_slash_in_id_uses_npx(self):
        fn = self._fn()
        assert fn("owner/repo") == ["npx", "-y", "owner/repo"]

    def test_simple_name_no_dots_uses_npx(self):
        fn = self._fn()
        assert fn("brave") == ["npx", "-y", "brave"]

    def test_dotted_name_uses_uvx(self):
        fn = self._fn()
        assert fn("my.python.tool") == ["uvx", "my.python.tool"]

    def test_long_npm_package_uses_npx(self):
        fn = self._fn()
        assert fn("@modelcontextprotocol/server-brave-search") == [
            "npx", "-y", "@modelcontextprotocol/server-brave-search"
        ]


# ---------------------------------------------------------------------------
# Helper: _local_uninstall_cmd
# ---------------------------------------------------------------------------

class TestLocalUninstallCmd:
    def _fn(self):
        from kitsune_mcp.tools import _local_uninstall_cmd
        return _local_uninstall_cmd

    def test_uvx_returns_uv_tool_uninstall(self):
        fn = self._fn()
        assert fn(["uvx", "mypkg"]) == ["uv", "tool", "uninstall", "mypkg"]

    def test_uvx_takes_last_element_as_package(self):
        fn = self._fn()
        result = fn(["uvx", "some-long-package-name"])
        assert result == ["uv", "tool", "uninstall", "some-long-package-name"]

    def test_npx_returns_none(self):
        fn = self._fn()
        assert fn(["npx", "-y", "brave"]) is None

    def test_empty_cmd_returns_none(self):
        fn = self._fn()
        assert fn([]) is None

    def test_unknown_cmd_returns_none(self):
        fn = self._fn()
        assert fn(["pip", "install", "something"]) is None


# ---------------------------------------------------------------------------
# status() — first-run onboarding
# ---------------------------------------------------------------------------

class TestStatusOnboarding:
    async def test_clean_session_shows_getting_started(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        # Ensure clean session state
        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {}
        session["grown"] = {}
        session["stats"] = {"total_calls": 0, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            # v0.11.0: clean-session preamble points users to the onboard() tool
            # rather than embedding tutorial text directly.
            assert "onboard()" in result
            # PROVIDERS section is now headlined regardless of session state
            assert "PROVIDERS" in result
        finally:
            for k, v in original.items():
                session[k] = v

    async def test_providers_section_appears_before_perf_stats(self):
        """v0.11.0 commit 6: PROVIDERS is the headline section."""
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {}
        session["grown"] = {}
        session["stats"] = {"total_calls": 0, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            assert result.index("PROVIDERS") < result.index("PERFORMANCE STATS")
        finally:
            for k, v in original.items():
                session[k] = v

    async def test_explored_session_hides_onboarding(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {"brave": {"name": "Brave", "desc": "search", "status": "explored"}}
        session["grown"] = {}
        session["stats"] = {"total_calls": 0, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            assert "Getting started:" not in result
        finally:
            for k, v in original.items():
                session[k] = v

    async def test_nonzero_calls_hides_onboarding(self):
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import status

        original = {k: session[k] for k in ("explored", "grown", "stats", "current_form", "shapeshift_tools")}
        session["explored"] = {}
        session["grown"] = {}
        session["stats"] = {"total_calls": 5, "tokens_sent": 0, "tokens_received": 0, "tokens_saved_browse": 0}
        session["current_form"] = None
        session["shapeshift_tools"] = []
        try:
            result = await status()
            assert "Getting started:" not in result
        finally:
            for k, v in original.items():
                session[k] = v


# ---------------------------------------------------------------------------
# shapeshift() — source='local' confirmation gate
# ---------------------------------------------------------------------------

class TestShapeshiftLocalGate:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_srv(self, source="npm", transport="stdio", install_cmd=None, credentials=None):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id="test-server",
            name="Test Server",
            description="A test server",
            source=source,
            transport=transport,
            url="",
            install_cmd=install_cmd or [],
            credentials=credentials or {},
            tools=[],
            token_cost=0,
        )

    async def test_local_without_confirm_shows_gate(self):
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(source="official", transport="stdio")

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("test-server", ctx, source="local", confirm=False)

        assert "source='local' will run" in result
        assert "npx" in result or "uvx" in result
        assert "confirm=True" in result

    async def test_local_gate_shows_exact_command(self):
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(source="official", transport="stdio", install_cmd=["npx", "-y", "@scope/test"])

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("test-server", ctx, source="local", confirm=False)

        assert "npx -y @scope/test" in result

    async def test_local_gate_bypassed_with_kitsune_trust(self):
        """KITSUNE_TRUST=community bypasses the local confirmation gate."""
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(source="official", transport="stdio", install_cmd=["npx", "-y", "test"])

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._do_shed"), \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_transport_cls, \
             patch.dict(os.environ, {"KITSUNE_TRUST": "community"}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=[
                {"name": "test_tool", "description": "A tool", "inputSchema": {"type": "object", "properties": {}, "required": []}}
            ])
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_cls.return_value = mock_transport

            result = await shapeshift("test-server", ctx, source="local", confirm=False)

        # Should NOT show the gate message (proceeds past it)
        assert "source='local' will run" not in result


# ---------------------------------------------------------------------------
# shapeshift() — credential check BEFORE _do_shed (bug fix)
# ---------------------------------------------------------------------------

class TestShapeshiftCredBugFix:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    async def test_do_shed_not_called_when_creds_missing(self):
        """If credentials are missing, _do_shed should NOT be called — current form preserved."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = ServerInfo(
            id="needs-key",
            name="Needs Key",
            description="Requires an API key",
            source="smithery",
            transport="http",
            url="https://example.com",
            install_cmd=[],
            credentials={"apiKey": "Your API key"},
            tools=[],
            token_cost=0,
        )

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._do_shed") as mock_shed, \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {"apiKey": "Your API key"})), \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("needs-key", ctx, confirm=True)

        mock_shed.assert_not_called()
        assert "missing credentials" in result.lower() or "Cannot shapeshift" in result

    async def test_do_shed_called_when_creds_ok(self):
        """When credentials pass, _do_shed should be called."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = ServerInfo(
            id="free-server",
            name="Free Server",
            description="No credentials needed",
            source="smithery",
            transport="http",
            url="https://example.com",
            install_cmd=[],
            credentials={},
            tools=[{"name": "my_tool", "description": "A tool", "inputSchema": {"type": "object", "properties": {}, "required": []}}],
            token_cost=0,
        )

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._do_shed", return_value=[]) as mock_shed, \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._state._get_transport") as mock_transport_fn, \
             patch("kitsune_mcp.tools._state._register_proxy_tools", return_value=["my_tool"]), \
             patch("kitsune_mcp.tools._state._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._state._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_fn.return_value = mock_transport

            await shapeshift("free-server", ctx)

        mock_shed.assert_called_once()


# ---------------------------------------------------------------------------
# shapeshift() — lean hint
# ---------------------------------------------------------------------------

class TestShapeshiftLeanHint:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_srv(self, n_tools=6):
        from kitsune_mcp.registry import ServerInfo
        tools = [
            {"name": f"tool_{i}", "description": f"Tool {i}", "inputSchema": {"type": "object", "properties": {}, "required": []}}
            for i in range(n_tools)
        ]
        return ServerInfo(
            id="heavy-server", name="Heavy Server", description="Has many tools",
            source="smithery", transport="http", url="https://example.com",
            install_cmd=[], credentials={}, tools=tools, token_cost=0,
        )

    async def _shapeshift_with_mock(self, n_tools=6, tools_filter=None):
        from kitsune_mcp.tools import shapeshift

        ctx = self._make_ctx()
        srv = self._make_srv(n_tools)
        registered = [f"tool_{i}" for i in range(n_tools)]

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._do_shed", return_value=[]), \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._state._get_transport") as mock_transport_fn, \
             patch("kitsune_mcp.tools._state._register_proxy_tools", return_value=registered[:len(tools_filter)] if tools_filter else registered), \
             patch("kitsune_mcp.tools._state._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._state._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_fn.return_value = mock_transport

            return await shapeshift("heavy-server", ctx, tools=tools_filter)

    async def test_many_tools_no_filter_shows_lean_hint(self):
        result = await self._shapeshift_with_mock(n_tools=6, tools_filter=None)
        assert "💡" in result
        assert "tokens" in result
        assert "shapeshift(" in result

    async def test_few_tools_no_hint(self):
        result = await self._shapeshift_with_mock(n_tools=3, tools_filter=None)
        assert "💡" not in result

    async def test_filter_applied_no_hint(self):
        result = await self._shapeshift_with_mock(n_tools=6, tools_filter=["tool_0", "tool_1"])
        assert "💡" not in result


class TestShapeshiftCallExample:
    """The `call(...)` example must use the schema of the tool actually shown,
    not blindly tool_schemas[0] — otherwise a filtered/collision-renamed first
    tool gets paired with another tool's required args."""

    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_srv_two_tools(self):
        from kitsune_mcp.registry import ServerInfo
        tools = [
            {"name": "first_tool", "description": "First",
             "inputSchema": {"type": "object", "properties": {"alpha": {"type": "string"}}, "required": ["alpha"]}},
            {"name": "second_tool", "description": "Second",
             "inputSchema": {"type": "object", "properties": {"beta": {"type": "integer"}}, "required": ["beta"]}},
        ]
        return ServerInfo(
            id="multi-server", name="Multi", description="Two tools with different args",
            source="smithery", transport="http", url="https://example.com",
            install_cmd=[], credentials={}, tools=tools, token_cost=0,
        )

    async def _shapeshift(self, tools_filter):
        from kitsune_mcp.tools import shapeshift
        ctx = self._make_ctx()
        srv = self._make_srv_two_tools()
        registered = tools_filter if tools_filter else [t["name"] for t in srv.tools]

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._do_shed", return_value=[]), \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._state._get_transport") as mock_transport_fn, \
             patch("kitsune_mcp.tools._state._register_proxy_tools", return_value=registered), \
             patch("kitsune_mcp.tools._state._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._state._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_transport_fn.return_value = mock_transport
            return await shapeshift("multi-server", ctx, tools=tools_filter)

    async def test_filtered_second_tool_shows_its_own_args(self):
        result = await self._shapeshift(tools_filter=["second_tool"])
        assert "call('second_tool'" in result
        assert "beta" in result
        assert "alpha" not in result

    async def test_first_tool_unfiltered_shows_first_args(self):
        result = await self._shapeshift(tools_filter=None)
        assert "call('first_tool'" in result
        assert "alpha" in result


# ---------------------------------------------------------------------------
# Trust gate — KITSUNE_TRUST env var
# ---------------------------------------------------------------------------

class TestKitsuneTrustGate:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        return ctx

    def _make_community_srv(self):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id="community-server", name="Community", description="From npm",
            source="npm", transport="stdio", url="",
            install_cmd=["npx", "-y", "community-server"],
            credentials={}, tools=[], token_cost=0,
        )

    async def test_community_server_without_confirm_shows_gate(self):
        from kitsune_mcp.tools import shapeshift
        ctx = self._make_ctx()
        srv = self._make_community_srv()

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)

            result = await shapeshift("community-server", ctx, confirm=False)

        assert "community" in result.lower()
        assert "confirm=True" in result
        assert "KITSUNE_TRUST" in result  # teaches the feature

    async def test_kitsune_trust_community_bypasses_gate(self):
        from kitsune_mcp.tools import shapeshift
        ctx = self._make_ctx()
        srv = self._make_community_srv()
        srv = srv.__class__(
            id=srv.id, name=srv.name, description=srv.description,
            source=srv.source, transport=srv.transport, url=srv.url,
            install_cmd=srv.install_cmd, credentials={},
            tools=[{"name": "t", "description": "d", "inputSchema": {"type": "object", "properties": {}, "required": []}}],
            token_cost=0,
        )

        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._do_shed", return_value=[]), \
             patch("kitsune_mcp.tools._state._resolve_config", return_value=({}, {})), \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch("kitsune_mcp.tools._state._register_proxy_tools", return_value=["t"]), \
             patch("kitsune_mcp.tools._state._register_proxy_resources", return_value=[]), \
             patch("kitsune_mcp.tools._state._register_proxy_prompts", return_value=[]), \
             patch("kitsune_mcp.tools._state._probe_requirements", return_value={}), \
             patch.dict(os.environ, {"KITSUNE_TRUST": "community"}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_reg._get = MagicMock(return_value=mock_reg)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=srv.tools)
            mock_transport.list_resources = AsyncMock(return_value=[])
            mock_transport.list_prompts = AsyncMock(return_value=[])
            mock_cls.return_value = mock_transport

            result = await shapeshift("community-server", ctx, confirm=False)

        # The GATE message contains "Review before trusting" — should NOT appear when bypassed
        assert "Review before trusting" not in result


# ---------------------------------------------------------------------------
# shiftback() — uninstall behaviour
# ---------------------------------------------------------------------------

class TestShiftbackUninstall:
    def _make_ctx(self):
        ctx = MagicMock()
        ctx.session = MagicMock()
        ctx.session.send_tool_list_changed = AsyncMock()
        ctx.session.send_resource_list_changed = AsyncMock()
        ctx.session.send_prompt_list_changed = AsyncMock()
        return ctx

    def _prime_session(self, package="brave", cmd=None, manager="npx"):
        """Set up session as if a local shapeshift just happened."""
        from kitsune_mcp.session import session
        install_cmd = cmd or (["npx", "-y", package] if manager == "npx" else ["uvx", package])
        session["shapeshift_tools"] = ["test_tool"]
        session["shapeshift_resources"] = []
        session["shapeshift_prompts"] = []
        session["current_form"] = package
        session["current_form_pool_key"] = None
        session["current_form_local_install"] = {"cmd": install_cmd, "package": package}

    def _reset_session(self):
        from kitsune_mcp.session import session
        session["shapeshift_tools"] = []
        session["shapeshift_resources"] = []
        session["shapeshift_prompts"] = []
        session["current_form"] = None
        session["current_form_pool_key"] = None
        session["current_form_local_install"] = None

    async def test_shiftback_without_uninstall_shows_cached_hint(self):
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("brave", manager="npx")
        try:
            with patch("kitsune_mcp.tools._state._do_shed", return_value=["test_tool"]):
                result = await shiftback(ctx, kill=False, uninstall=False)
            assert "still cached" in result or "cached" in result
            assert "shiftback(uninstall=True)" in result
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_npx_notes_ephemeral(self):
        """npx packages have no targeted uninstall — output should say so."""
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("brave", manager="npx")
        try:
            with patch("kitsune_mcp.tools._state._do_shed", return_value=["test_tool"]):
                result = await shiftback(ctx, kill=False, uninstall=True)
            assert "npx" in result.lower() or "cached" in result.lower() or "permanently" in result.lower()
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_uvx_runs_uv_command(self):
        """uvx packages trigger `uv tool uninstall <pkg>`."""
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("mypkg", manager="uvx")
        try:
            mock_proc = AsyncMock()
            mock_proc.returncode = 0
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))

            with patch("kitsune_mcp.tools._state._do_shed", return_value=["test_tool"]), \
                 patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
                result = await shiftback(ctx, kill=False, uninstall=True)

            # Should have called uv tool uninstall mypkg
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args == ("uv", "tool", "uninstall", "mypkg")
            assert "Uninstalled" in result
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_uvx_failed(self):
        """If uv tool uninstall fails, report the error without crashing."""
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        self._prime_session("mypkg", manager="uvx")
        try:
            mock_proc = AsyncMock()
            mock_proc.returncode = 1
            mock_proc.communicate = AsyncMock(return_value=(b"", b"Package not found"))

            with patch("kitsune_mcp.tools._state._do_shed", return_value=["test_tool"]), \
                 patch("asyncio.create_subprocess_exec", return_value=mock_proc):
                result = await shiftback(ctx, kill=False, uninstall=True)

            assert "Uninstall failed" in result or "error" in result.lower()
        finally:
            self._reset_session()

    async def test_shiftback_uninstall_no_local_install_is_noop(self):
        """uninstall=True with no local install tracked — just normal shiftback."""
        from kitsune_mcp.session import session
        from kitsune_mcp.tools import shiftback
        ctx = self._make_ctx()
        session["shapeshift_tools"] = ["test_tool"]
        session["shapeshift_resources"] = []
        session["shapeshift_prompts"] = []
        session["current_form"] = "some-server"
        session["current_form_pool_key"] = None
        session["current_form_local_install"] = None
        try:
            with patch("kitsune_mcp.tools._state._do_shed", return_value=["test_tool"]):
                result = await shiftback(ctx, kill=False, uninstall=True)
            # Should not crash, should not show cached hint
            assert "still cached" not in result
            assert "Shifted back" in result
        finally:
            self._reset_session()


# ---------------------------------------------------------------------------
# MultiRegistry — last_registry_errors
# ---------------------------------------------------------------------------

class TestRegistryErrors:
    async def test_failing_registry_recorded_in_errors(self):
        """A registry that raises populates last_registry_errors."""
        from kitsune_mcp.registry import MultiRegistry, ServerInfo

        mr = MultiRegistry()
        # Replace all registries with one that succeeds and one that fails
        good_reg = AsyncMock()
        good_reg.search = AsyncMock(return_value=[
            ServerInfo("s1", "S1", "desc", "official", "stdio")
        ])
        bad_reg = AsyncMock()
        bad_reg.search = AsyncMock(side_effect=TimeoutError("timeout"))
        bad_reg.__class__.__name__ = "BadRegistry"

        mr._registries = [good_reg, bad_reg]
        mr._search_cache.clear()

        results = await mr.search("test", 5)

        assert len(mr.last_registry_errors) == 1
        assert len(results) == 1  # only the good result

    async def test_no_failures_means_empty_errors(self):
        from kitsune_mcp.registry import MultiRegistry, ServerInfo

        mr = MultiRegistry()
        good1 = AsyncMock()
        good1.search = AsyncMock(return_value=[ServerInfo("s1", "S1", "d", "official", "stdio")])
        good2 = AsyncMock()
        good2.search = AsyncMock(return_value=[ServerInfo("s2", "S2", "d", "npm", "stdio")])
        mr._registries = [good1, good2]
        mr._search_cache.clear()

        await mr.search("test", 5)

        assert mr.last_registry_errors == {}


# ---------------------------------------------------------------------------
# search() — registry failure warning in output
# ---------------------------------------------------------------------------

class TestSearchRegistryWarning:
    async def test_search_shows_warning_when_registry_fails(self):
        """When a registry fails during search('all'), ⚠️ Skipped: appears."""
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import search

        mock_servers = [
            ServerInfo("brave", "Brave", "Web search", "smithery", "http"),
        ]

        mock_registry = MagicMock()
        mock_registry.search = AsyncMock(return_value=mock_servers)
        mock_registry.last_registry_errors = {"glama": "TimeoutError"}

        with patch("kitsune_mcp.tools._state._registry", mock_registry):
            result = await search("web search", registry="all", limit=5)

        assert "⚠️" in result
        assert "Skipped" in result
        assert "glama" in result

    async def test_search_no_warning_when_no_failures(self):
        from kitsune_mcp.registry import ServerInfo
        from kitsune_mcp.tools import search

        mock_servers = [
            ServerInfo("brave", "Brave", "Web search", "smithery", "http"),
        ]

        mock_registry = MagicMock()
        mock_registry.search = AsyncMock(return_value=mock_servers)
        mock_registry.last_registry_errors = {}

        with patch("kitsune_mcp.tools._state._registry", mock_registry):
            result = await search("web search", registry="all", limit=5)

        assert "Skipped" not in result


# ---------------------------------------------------------------------------
# inspect() — surface live-probe failure instead of lying
# ---------------------------------------------------------------------------

class TestInspectProbeFailure:
    def _make_srv(self, credentials=None):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id="needs-init",
            name="Needs Init",
            description="Server that fails to initialize without a key",
            source="npm",
            transport="stdio",
            install_cmd=["npx", "-y", "needs-init"],
            credentials=credentials or {},
            tools=[],
            token_cost=0,
        )

    async def test_probe_failure_surfaces_error_message(self):
        """When the live probe raises, inspect() must surface the error, not claim 'not listed in registry'."""
        from kitsune_mcp.tools import inspect

        srv = self._make_srv()
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(
                side_effect=RuntimeError("No initialize response from npx")
            )
            mock_cls.return_value = mock_transport

            result = await inspect("needs-init", probe=True)

        assert "live probe failed" in result
        assert "No initialize response" in result
        assert "not listed in registry" not in result

    async def test_probe_failure_with_declared_cred_suggests_key_and_retry(self):
        """Probe failed AND registry declares a cred → concrete key(...) then inspect(...) hint."""
        from kitsune_mcp.tools import inspect

        srv = self._make_srv(credentials={"apiKey": "Your API key"})
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("API_KEY", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(side_effect=RuntimeError("boom"))
            mock_cls.return_value = mock_transport

            result = await inspect("needs-init", probe=True)

        assert "Probe may have failed due to missing creds" in result
        assert 'key("API_KEY"' in result
        assert 'inspect("needs-init")' in result

    async def test_probe_failure_no_declared_creds_shows_generic_hint(self):
        """Probe failed and no creds declared → generic 'maybe set an undeclared cred' hint."""
        from kitsune_mcp.tools import inspect

        srv = self._make_srv()  # no credentials
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(side_effect=RuntimeError("boom"))
            mock_cls.return_value = mock_transport

            result = await inspect("needs-init", probe=True)

        assert "credentials not declared in registry" in result
        assert "retry inspect" in result
        # Should NOT wrongly suggest a specific key name
        assert 'key("' not in result or "Probe may have failed due to missing creds" not in result

    async def test_probe_success_unchanged(self):
        """Happy path: probe returns tools → existing 'TOOLS (live)' + shapeshift hint preserved."""
        from kitsune_mcp.tools import inspect

        srv = self._make_srv()  # no creds
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_transport = AsyncMock()
            mock_transport.list_tools = AsyncMock(return_value=[
                {"name": "hello", "description": "say hi",
                 "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": []}},
            ])
            mock_cls.return_value = mock_transport

            result = await inspect("needs-init", probe=True)

        assert "TOOLS (live" in result
        assert "hello" in result
        assert 'shapeshift("needs-init"' in result
        assert "live probe failed" not in result


class TestInspectProbeTrustGate:
    """The probe consent gate for inspect — community sources must opt in."""

    @staticmethod
    def _srv(source="npm", install_cmd=None):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id="x", name="X", description="", source=source, transport="stdio",
            install_cmd=install_cmd if install_cmd is not None else ["npx", "-y", "x"],
        )

    async def test_low_trust_source_is_gated_by_default(self):
        from kitsune_mcp.tools import inspect
        srv = self._srv(source="npm")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[]))
            result = await inspect("x")
        assert "TOOLS: not probed" in result
        assert "probe=True" in result
        # The transport must NOT have been called.
        mock_cls.assert_not_called()

    async def test_probe_true_overrides_gate(self):
        from kitsune_mcp.tools import inspect
        srv = self._srv(source="npm")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[
                {"name": "hello", "inputSchema": {"properties": {}}}
            ]))
            result = await inspect("x", probe=True)
        assert "TOOLS (live" in result
        mock_cls.assert_called_once()

    async def test_kitsune_trust_community_overrides_gate(self):
        from kitsune_mcp.tools import inspect
        srv = self._srv(source="npm")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {"KITSUNE_TRUST": "community"}):
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[
                {"name": "hello", "inputSchema": {"properties": {}}}
            ]))
            result = await inspect("x")
        assert "TOOLS (live" in result
        mock_cls.assert_called_once()

    async def test_high_trust_source_probes_automatically(self):
        from kitsune_mcp.tools import inspect
        srv = self._srv(source="mcpregistry")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[
                {"name": "hello", "inputSchema": {"properties": {}}}
            ]))
            result = await inspect("x")
        assert "TOOLS (live" in result
        mock_cls.assert_called_once()

    async def test_github_install_cmd_is_gated_even_when_source_trusted(self):
        from kitsune_mcp.tools import inspect
        # glama is medium-trust, but the actual install runs github code → gate.
        srv = self._srv(source="glama", install_cmd=["npx", "github:owner/repo"])
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[]))
            result = await inspect("x")
        assert "TOOLS: not probed" in result
        assert "github" in result
        mock_cls.assert_not_called()

    async def test_tools_line_shows_install_cmd_source(self):
        from kitsune_mcp.tools import inspect
        srv = self._srv(source="mcpregistry", install_cmd=["npx", "-y", "@org/srv"])
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.get_server = AsyncMock(return_value=srv)
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[
                {"name": "t", "inputSchema": {"properties": {}}}
            ]))
            result = await inspect("x")
        assert "via npx -y @org/srv" in result


class TestProbeEnvSanitization:
    """The probe subprocess must run with a sanitized environment."""

    async def test_probe_env_passed_to_create_subprocess_exec(self):
        from kitsune_mcp.constants import STDIO_BUFFER_LIMIT
        from server import PersistentStdioTransport
        env = {"PATH": "/usr/bin", "HOME": "/tmp/x"}
        spy = AsyncMock(return_value=MagicMock(
            stdin=MagicMock(write=MagicMock(), drain=AsyncMock(), close=MagicMock()),
            stdout=MagicMock(readline=AsyncMock(return_value=b"")),
            returncode=None, kill=MagicMock(), wait=AsyncMock(return_value=0),
        ))
        with patch("asyncio.create_subprocess_exec", spy):
            transport = PersistentStdioTransport(["echo"], probe_env=env)
            try:
                await transport._start_process()
            except RuntimeError:
                pass
        assert spy.call_args.kwargs["env"] == env
        assert spy.call_args.kwargs["limit"] == STDIO_BUFFER_LIMIT

    async def test_default_transport_inherits_host_env(self):
        from server import PersistentStdioTransport
        spy = AsyncMock(return_value=MagicMock(
            stdin=MagicMock(write=MagicMock(), drain=AsyncMock(), close=MagicMock()),
            stdout=MagicMock(readline=AsyncMock(return_value=b"")),
            returncode=None, kill=MagicMock(), wait=AsyncMock(return_value=0),
        ))
        with patch("asyncio.create_subprocess_exec", spy):
            transport = PersistentStdioTransport(["echo"])  # no probe_env
            try:
                await transport._start_process()
            except RuntimeError:
                pass
        # env=None means inherit from parent.
        assert spy.call_args.kwargs["env"] is None

    async def test_probe_pool_key_isolated_from_prod_pool_key(self):
        from server import PersistentStdioTransport
        prod = PersistentStdioTransport(["npx", "x"])
        probe = PersistentStdioTransport(["npx", "x"], probe_env={"PATH": "/usr/bin"})
        assert prod._pool_key != probe._pool_key
        assert probe._pool_key.endswith("#probe")


class TestProbeEnvHeuristicPassthrough:
    """Host env vars matching the server's identity should be passed through
    even when the registry didn't declare them — the common case for npm
    servers like @notionhq/notion-mcp-server which need NOTION_TOKEN."""

    @staticmethod
    def _srv(id, name="x", source="npm", credentials=None):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(id=id, name=name, description="", source=source,
                          transport="stdio", credentials=credentials or {})

    def test_notion_token_passes_to_notion_server(self):
        from kitsune_mcp.tools import _probe_env
        with patch.dict(os.environ, {"NOTION_TOKEN": "sek", "AWS_KEY": "leak"}):
            env = _probe_env(self._srv("@notionhq/notion-mcp-server"))
        assert env.get("NOTION_TOKEN") == "sek"
        assert "AWS_KEY" not in env

    def test_unrelated_creds_blocked(self):
        from kitsune_mcp.tools import _probe_env
        with patch.dict(os.environ, {"OPENAI_API_KEY": "x", "AWS_SECRET_ACCESS_KEY": "y"}):
            env = _probe_env(self._srv("@notionhq/notion-mcp-server"))
        assert "OPENAI_API_KEY" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env

    def test_declared_creds_still_pass_even_without_id_match(self):
        from kitsune_mcp.tools import _probe_env
        srv = self._srv("some-package", credentials={"apiKey": ""})
        with patch.dict(os.environ, {"API_KEY": "set"}):
            env = _probe_env(srv)
        assert env.get("API_KEY") == "set"

    def test_short_substrings_dont_match(self):
        from kitsune_mcp.tools import _probe_env
        # 'mcp' is in many env var names but it's only 3 chars — below the
        # 4-char minimum that prevents accidental matches.
        with patch.dict(os.environ, {"MCP_TOKEN": "x"}):
            env = _probe_env(self._srv("notion"))
        assert "MCP_TOKEN" not in env


class TestCompareTool:
    """compare() probes search candidates in parallel and tabulates token cost."""

    @staticmethod
    def _srv(id, source="official", install_cmd=None, tools=None):
        from kitsune_mcp.registry import ServerInfo
        return ServerInfo(
            id=id, name=id.split("/")[-1], description="x",
            source=source, transport="stdio",
            install_cmd=install_cmd if install_cmd is not None else ["npx", "-y", id],
            tools=tools or [],
        )

    async def test_returns_no_servers_message_on_empty_search(self):
        from kitsune_mcp.tools import compare
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[])
            result = await compare("nothing")
        assert "No servers found" in result

    async def test_uses_registry_cached_tools_when_present(self):
        from kitsune_mcp.tools import compare
        cached_tools = [
            {"name": "t1", "description": "x" * 40, "inputSchema": {"properties": {}}},
            {"name": "t2", "description": "x" * 40, "inputSchema": {"properties": {}}},
        ]
        srv = self._srv("foo/cached", source="official", tools=cached_tools)
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.search = AsyncMock(return_value=[srv])
            result = await compare("foo")
            mock_cls.assert_not_called()  # no live probe needed
        assert "registry" in result
        assert "foo/cached" in result

    async def test_sorts_by_token_cost_ascending(self):
        from kitsune_mcp.tools import compare
        small = self._srv("s/cheap", source="official",
                           tools=[{"name": "t", "description": "x", "inputSchema": {"properties": {}}}])
        big_tools = [{"name": f"t{i}", "description": "x" * 200, "inputSchema": {"properties": {}}} for i in range(20)]
        big = self._srv("s/expensive", source="official", tools=big_tools)
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[big, small])
            result = await compare("s")
        # cheap should appear before expensive in the table
        assert result.index("s/cheap") < result.index("s/expensive")

    async def test_gates_low_trust_without_probe_flag(self):
        from kitsune_mcp.tools import compare
        srv = self._srv("@some/package", source="npm")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.search = AsyncMock(return_value=[srv])
            result = await compare("any")
            mock_cls.assert_not_called()
        assert "gated" in result
        assert "probe=True" in result

    async def test_probe_true_overrides_gate_for_low_trust(self):
        from kitsune_mcp.tools import compare
        srv = self._srv("@some/package", source="npm")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[
                {"name": "t", "description": "x", "inputSchema": {"properties": {}}}
            ]))
            result = await compare("any", probe=True)
            mock_cls.assert_called_once()
        assert "live" in result

    async def test_recommends_cheapest_ready_to_use(self):
        from kitsune_mcp.tools import compare
        a = self._srv("foo/a", source="official",
                       tools=[{"name": "t", "description": "x", "inputSchema": {"properties": {}}}])
        b = self._srv("foo/b", source="official",
                       tools=[{"name": "t", "description": "x" * 800, "inputSchema": {"properties": {}}}])
        with patch("kitsune_mcp.tools._state._registry") as mock_reg:
            mock_reg.search = AsyncMock(return_value=[a, b])
            result = await compare("foo")
        # The cheapest-of-two ready candidates should be recommended.
        assert "Cheapest ready" in result
        assert "foo/a" in result.split("Cheapest ready")[1]

    async def test_smithery_without_key_shows_actionable_status(self):
        from kitsune_mcp.tools import compare
        from kitsune_mcp.registry import ServerInfo
        srv = ServerInfo(id="notion", name="Notion", description="x",
                         source="smithery", transport="http", url="https://x.run.tools")
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state._smithery_available", return_value=False):
            mock_reg.search = AsyncMock(return_value=[srv])
            result = await compare("any")
        assert "needs SMITHERY_API_KEY" in result

    async def test_description_tool_count_yields_estimate_when_probe_fails(self):
        from kitsune_mcp.tools import compare
        from kitsune_mcp.registry import ServerInfo
        srv = ServerInfo(
            id="x/y", name="y",
            description="Markdown-first Notion MCP — 26 tools, low token cost",
            source="glama", transport="http", url="",
            install_cmd=["npx", "github:x/y"],
        )
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KITSUNE_TRUST", None)
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_cls.return_value = MagicMock(list_tools=AsyncMock(return_value=[]))
            result = await compare("any", probe=True)
        # 26 tools × 600 = 15,600
        assert "15,600" in result
        assert "26" in result
        assert "est" in result

    async def test_exception_text_appears_in_status(self):
        from kitsune_mcp.tools import compare
        from kitsune_mcp.registry import ServerInfo
        srv = ServerInfo(
            id="@x/y", name="y", description="", source="npm", transport="stdio",
            install_cmd=["npx", "-y", "@x/y"],
        )
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_cls.return_value = MagicMock(
                list_tools=AsyncMock(side_effect=RuntimeError("npx package not found")),
            )
            result = await compare("any", probe=True)
        assert "failed:" in result
        assert "npx package" in result


class TestComparePolish:
    """Polish behaviors: humanized errors, strict cred check, sensible actions."""

    @staticmethod
    def _srv(**kw):
        from kitsune_mcp.registry import ServerInfo
        defaults = dict(id="x", name="x", description="", source="npm",
                        transport="stdio", install_cmd=["npx", "-y", "x"])
        defaults.update(kw)
        return ServerInfo(**defaults)

    def test_humanize_init_timeout(self):
        from kitsune_mcp.tools import _humanize_probe_error
        assert _humanize_probe_error("No initialize response from npx") == "init timeout (60s)"

    def test_humanize_binary_not_found(self):
        from kitsune_mcp.tools import _humanize_probe_error
        assert _humanize_probe_error("Cannot find 'npx'") == "binary not found"

    def test_humanize_passes_through_short_unknown(self):
        from kitsune_mcp.tools import _humanize_probe_error
        assert _humanize_probe_error("weird thing") == "weird thing"

    def test_strict_cred_check_catches_non_suffix_creds(self):
        """The registry-driven check must catch creds like *_WORKSPACE_ROOT
        that _resolve_config skips because they don't end in _KEY/_TOKEN/etc."""
        from kitsune_mcp.tools import _compare_missing_creds
        srv = self._srv(credentials={"NOTION_LOCAL_OPS_WORKSPACE_ROOT": "path"})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOTION_LOCAL_OPS_WORKSPACE_ROOT", None)
            missing = _compare_missing_creds(srv)
        assert missing == ["NOTION_LOCAL_OPS_WORKSPACE_ROOT"]

    def test_strict_cred_check_skips_when_set(self):
        from kitsune_mcp.tools import _compare_missing_creds
        srv = self._srv(credentials={"NOTION_LOCAL_OPS_WORKSPACE_ROOT": "path"})
        with patch.dict(os.environ, {"NOTION_LOCAL_OPS_WORKSPACE_ROOT": "/tmp"}):
            assert _compare_missing_creds(srv) == []

    async def test_compare_uses_strict_cred_for_path_style_creds(self):
        from kitsune_mcp.tools import compare
        srv = self._srv(
            id="catoncat/notion-local-ops-mcp",
            credentials={"NOTION_LOCAL_OPS_WORKSPACE_ROOT": "Workspace dir"},
        )
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls, \
             patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOTION_LOCAL_OPS_WORKSPACE_ROOT", None)
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_cls.return_value = MagicMock(
                list_tools=AsyncMock(side_effect=RuntimeError("No initialize response from npx"))
            )
            result = await compare("any", probe=True)
        # New behaviour: strict cred check fires before "init timeout".
        # The status column truncates at 24 chars but the action line carries
        # the full cred name.
        assert "needs NOTION_LOCAL_OPS" in result  # truncated form in table
        assert 'key("NOTION_LOCAL_OPS_WORKSPACE_ROOT"' in result  # full in action

    async def test_compare_action_for_failed_row_is_inspect_not_shapeshift(self):
        from kitsune_mcp.tools import compare
        srv = self._srv(id="foo/bar", credentials={})
        with patch("kitsune_mcp.tools._state._registry") as mock_reg, \
             patch("kitsune_mcp.tools._state.PersistentStdioTransport") as mock_cls:
            mock_reg.search = AsyncMock(return_value=[srv])
            mock_cls.return_value = MagicMock(
                list_tools=AsyncMock(side_effect=RuntimeError("No initialize response"))
            )
            result = await compare("any", probe=True)
        # Action for failed row should be inspect, not the default shapeshift.
        next_steps = result.split("Next steps for the rest:")[1] if "Next steps" in result else ""
        assert 'inspect("foo/bar"' in next_steps
        assert 'shapeshift("foo/bar")' not in next_steps
