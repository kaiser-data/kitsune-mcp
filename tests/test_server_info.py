"""serverInfo in the initialize response names Kitsune, not the mcp SDK."""


def test_initialize_reports_kitsune_version():
    from kitsune_mcp import __version__
    from kitsune_mcp.app import mcp

    opts = mcp._mcp_server.create_initialization_options()
    assert opts.server_name == "kitsune"
    assert opts.server_version == __version__
