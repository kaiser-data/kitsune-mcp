"""Chameleon Forge — full evaluation + crafting suite (all 17 tools).

Equivalent to: KITSUNE_TOOLS=all kitsune-mcp
"""

import os

os.environ.setdefault("KITSUNE_TOOLS", "all")

from server import mcp  # noqa: E402, F401 — registers all tools, applies profile

if __name__ == "__main__":
    mcp.run()
