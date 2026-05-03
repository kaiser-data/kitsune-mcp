"""Release smoke test: import every public module + the entry point.

This test exists to catch the v0.10.0/v0.10.1 class of failure: a module
being imported by transport.py but not committed/published, which causes
ImportError at startup. CI runs pytest before publish, so any missing-file
import error fails the build before reaching PyPI/npm.
"""
import importlib


def test_server_module_imports():
    """server.py — the actual entry point — must import without ImportError."""
    # If this fails in CI, look for newly-untracked .py files in kitsune_mcp/
    import server
    assert hasattr(server, "mcp")


def test_all_kitsune_modules_import():
    """Every module under kitsune_mcp.* must import. Catches missing files
    like the v0.10.0/v0.10.1 oauth.py-not-shipped bug.

    Imports without sys.modules.pop() because some test fixtures rely on
    module-level state (e.g. patched _registry, _process_pool); resetting
    the module cache mid-suite poisons downstream tests. The first import
    is sufficient to surface ImportError, which is what this test is for.
    """
    modules = [
        "kitsune_mcp.app",
        "kitsune_mcp.constants",
        "kitsune_mcp.credentials",
        "kitsune_mcp.oauth",  # the v0.10.0/v0.10.1 missing module
        "kitsune_mcp.official_registry",
        "kitsune_mcp.probe",
        "kitsune_mcp.registry",
        "kitsune_mcp.session",
        "kitsune_mcp.shapeshift",
        "kitsune_mcp.transport",
        "kitsune_mcp.utils",
        "kitsune_mcp._fastmcp_compat",
        "kitsune_mcp.tools",
        "kitsune_mcp.tools._state",
        "kitsune_mcp.tools.discovery",
        "kitsune_mcp.tools.exec",
        "kitsune_mcp.tools.morph",
        "kitsune_mcp.tools.onboarding",
    ]
    for name in modules:
        importlib.import_module(name)


def test_oauth_exports_required_symbols():
    """transport.py imports specific names from oauth — assert they exist."""
    from kitsune_mcp import oauth
    assert hasattr(oauth, "ensure_token")
    assert hasattr(oauth, "delete_tokens")
    assert hasattr(oauth, "_origin")
