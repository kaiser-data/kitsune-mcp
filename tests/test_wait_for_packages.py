"""publish.yml waits until npm and PyPI serve the exact server.json versions
before registering with the MCP Registry, which otherwise rejects the publish
with 400 'version not found' (seen on v0.22.3, v0.22.5, v0.22.6)."""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "wait_for_packages.py"
_spec = importlib.util.spec_from_file_location("wait_for_packages", _SCRIPT)
wfp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wfp)


def _manifest(tmp_path, version="1.2.3", npm="1.2.3", pypi="1.2.3"):
    p = tmp_path / "server.json"
    p.write_text(
        json.dumps(
            {
                "version": version,
                "packages": [
                    {"registryType": "npm", "identifier": "kitsune-mcp", "version": npm},
                    {"registryType": "pypi", "identifier": "kitsune-mcp", "version": pypi},
                ],
            }
        )
    )
    return p


def test_package_urls_point_at_exact_versions(tmp_path):
    urls = wfp.package_urls(json.loads(_manifest(tmp_path).read_text()))
    assert urls == [
        "https://registry.npmjs.org/kitsune-mcp/1.2.3",
        "https://pypi.org/pypi/kitsune-mcp/1.2.3/json",
    ]


def test_scoped_npm_name_is_url_encoded(tmp_path):
    manifest = {
        "packages": [{"registryType": "npm", "identifier": "@acme/pkg", "version": "1.0.0"}]
    }
    assert wfp.package_urls(manifest) == ["https://registry.npmjs.org/@acme%2Fpkg/1.0.0"]


def test_waits_until_every_package_is_live(tmp_path):
    answers = {
        "https://registry.npmjs.org/kitsune-mcp/1.2.3": [404, 404, 200],
        "https://pypi.org/pypi/kitsune-mcp/1.2.3/json": [200],
    }
    calls, sleeps = [], []

    def fetch(url):
        calls.append(url)
        seq = answers[url]
        return seq.pop(0) if len(seq) > 1 else seq[0]

    assert wfp.wait(_manifest(tmp_path), fetch=fetch, sleep=sleeps.append, timeout=600) == 0
    assert calls.count("https://registry.npmjs.org/kitsune-mcp/1.2.3") == 3
    assert len(sleeps) == 2
    assert sleeps == sorted(sleeps)  # backoff grows


def test_gives_up_after_timeout(tmp_path, capsys):
    sleeps = []
    rc = wfp.wait(_manifest(tmp_path), fetch=lambda url: 404, sleep=sleeps.append, timeout=60)
    assert rc == 1
    assert sum(sleeps) <= 60
    assert "registry.npmjs.org/kitsune-mcp/1.2.3" in capsys.readouterr().err


def test_network_errors_count_as_not_live(tmp_path):
    state = {"n": 0}

    def fetch(url):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError("reset")
        return 200

    assert wfp.wait(_manifest(tmp_path), fetch=fetch, sleep=lambda s: None, timeout=600) == 0


@pytest.mark.parametrize("npm,pypi", [("1.2.2", "1.2.3"), ("1.2.3", "1.2.4")])
def test_package_version_must_match_server_version(tmp_path, npm, pypi):
    rc = wfp.wait(
        _manifest(tmp_path, npm=npm, pypi=pypi), fetch=lambda url: 200, sleep=lambda s: None
    )
    assert rc == 2


def test_repo_server_json_is_consistent():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "server.json").read_text())
    assert wfp.version_mismatches(manifest) == []
    assert len(wfp.package_urls(manifest)) == 2
