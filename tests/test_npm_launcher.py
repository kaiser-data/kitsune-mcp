"""The npm wrapper (bin/kitsune-mcp.js) falls back to a pip-installed server."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
SHIM = Path(__file__).resolve().parent.parent / "bin" / "kitsune-mcp.js"
pytestmark = [
    pytest.mark.skipif(NODE is None, reason="node not installed"),
    pytest.mark.skipif(os.name == "nt", reason="uses sh scripts"),
]


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _run(bin_dir: Path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "KITSUNE_MCP_NPM_SHIM"}
    env["PATH"] = os.pathsep.join([str(bin_dir), "/usr/bin", "/bin"])  # no uvx
    return subprocess.run(
        [NODE, str(SHIM), "--flag"], env=env, capture_output=True, text=True, timeout=20
    )


def test_falls_back_to_pip_install_when_uvx_missing(tmp_path):
    _script(tmp_path / "kitsune-mcp", 'echo "pip-server $@"')
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "pip-server --flag" in r.stdout


def test_fallback_to_itself_fails_instead_of_looping(tmp_path):
    _script(tmp_path / "kitsune-mcp", f'exec "{NODE}" "{SHIM}" "$@"')
    r = _run(tmp_path)
    assert r.returncode == 1
    assert r.stderr.count("could not start server") == 1


def test_uvx_exit_code_passes_through(tmp_path):
    _script(tmp_path / "uvx", "exit 7")
    r = _run(tmp_path)
    assert r.returncode == 7
