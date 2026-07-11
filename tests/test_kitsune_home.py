"""Tests for issue #39 — KITSUNE_HOME must be honored by ALL state modules.

Before this fix only session.py read KITSUNE_HOME; credentials, gateway,
oauth, and the skills path hardcoded ~/.kitsune, breaking isolation for
benchmarks, CI, and multi-tenant testing.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestKitsuneHomeHelper:
    def test_default_is_home_dot_kitsune(self, monkeypatch):
        monkeypatch.delenv("KITSUNE_HOME", raising=False)
        from kitsune_mcp.paths import kitsune_home
        assert kitsune_home() == Path.home() / ".kitsune"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("KITSUNE_HOME", "/tmp/kitsune-iso")
        from kitsune_mcp.paths import kitsune_home
        assert kitsune_home() == Path("/tmp/kitsune-iso")


class TestAllModulesHonorKitsuneHome:
    """Module-level path constants are bound at import time, so derivation is
    asserted in a subprocess with KITSUNE_HOME set — full isolation, no
    importlib.reload side effects on the rest of the suite."""

    def test_every_state_path_derives_from_kitsune_home(self, tmp_path):
        iso = tmp_path / "iso-home"
        code = (
            "import json\n"
            "import kitsune_mcp.session as s\n"
            "import kitsune_mcp.credentials as c\n"
            "import kitsune_mcp.gateway as g\n"
            "import kitsune_mcp.oauth as o\n"
            "print(json.dumps({\n"
            "    'state': str(s._STATE_PATH),\n"
            "    'skills': str(s.SKILLS_PATH),\n"
            "    'env': str(c.ENV_PATH),\n"
            "    'absorbed': str(g._ABSORBED_PATH),\n"
            "    'backup': str(g._BACKUP_DIR),\n"
            "    'oauth': str(o._KITSUNE_DIR),\n"
            "}))\n"
        )
        env = {**os.environ, "KITSUNE_HOME": str(iso)}
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, env=env, cwd=_REPO_ROOT, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        paths = json.loads(out.stdout.strip().splitlines()[-1])
        for name, p in paths.items():
            assert str(iso) in p, f"{name} ignores KITSUNE_HOME: {p}"

    def test_server_dotenv_load_honors_kitsune_home(self, tmp_path):
        # server.py loads $KITSUNE_HOME/.env at startup — a key written there
        # must be visible to the process, and ~/.kitsune must not be involved.
        iso = tmp_path / "iso-home"
        iso.mkdir()
        (iso / ".env").write_text("KITSUNE_ISO_MARKER_KEY=from-iso-home\n")
        code = (
            "import os\n"
            "import server\n"
            "print(os.getenv('KITSUNE_ISO_MARKER_KEY', 'MISSING'))\n"
        )
        env = {**os.environ, "KITSUNE_HOME": str(iso), "KITSUNE_TOOLS": "lean"}
        env.pop("KITSUNE_ISO_MARKER_KEY", None)
        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, env=env, cwd=_REPO_ROOT, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip().splitlines()[-1] == "from-iso-home"
