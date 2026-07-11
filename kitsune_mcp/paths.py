"""Single source of truth for the Kitsune state directory (issue #39).

Every module that persists state (credentials, gateway absorption, OAuth
tokens, session/skills) must derive its paths from kitsune_home() so that
KITSUNE_HOME=/some/dir yields a fully self-contained state directory —
required for benchmarks, CI, and multi-tenant isolation.
"""
import os
from pathlib import Path


def kitsune_home() -> Path:
    """Return the Kitsune state directory: $KITSUNE_HOME or ~/.kitsune."""
    return Path(os.getenv("KITSUNE_HOME", str(Path.home() / ".kitsune")))
