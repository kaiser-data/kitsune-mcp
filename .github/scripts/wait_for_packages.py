"""Wait until npm and PyPI serve the exact versions listed in server.json.

The MCP Registry validates every package in server.json at publish time and
rejects a version npm or PyPI doesn't serve yet (400 "version not found").
A fresh npm release can take a few minutes to appear, so publish.yml runs this
before `mcp-publisher publish`.

Usage: python .github/scripts/wait_for_packages.py [server.json] [timeout_seconds]
Exit codes: 0 all live, 1 timed out, 2 server.json versions disagree.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_URLS = {
    "npm": "https://registry.npmjs.org/{name}/{version}",
    "pypi": "https://pypi.org/pypi/{name}/{version}/json",
}


def package_urls(manifest: dict) -> list[str]:
    urls = []
    for pkg in manifest.get("packages", []):
        template = _URLS.get(pkg.get("registryType", ""))
        if template:
            name = urllib.parse.quote(pkg["identifier"], safe="@")
            urls.append(template.format(name=name, version=pkg["version"]))
    return urls


def version_mismatches(manifest: dict) -> list[str]:
    want = manifest.get("version")
    return [
        f"{p.get('registryType')}:{p.get('identifier')} is {p.get('version')}, server.json is {want}"
        for p in manifest.get("packages", [])
        if p.get("version") != want
    ]


def _status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def wait(path, fetch=_status, sleep=time.sleep, timeout: float = 600) -> int:
    manifest = json.loads(Path(path).read_text())
    mismatches = version_mismatches(manifest)
    if mismatches:
        print("✗ " + "; ".join(mismatches), file=sys.stderr)
        return 2

    pending = package_urls(manifest)
    waited, delay = 0.0, 5.0
    while True:
        still = []
        for url in pending:
            try:
                live = fetch(url) == 200
            except OSError:
                live = False
            if live:
                print(f"✓ live: {url}")
            else:
                still.append(url)
        pending = still
        if not pending:
            return 0
        if waited + delay > timeout:
            print(f"✗ not live after {int(waited)}s: {', '.join(pending)}", file=sys.stderr)
            return 1
        print(f"… waiting {int(delay)}s for: {', '.join(pending)}")
        sleep(delay)
        waited += delay
        delay = min(delay * 2, 60.0)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "server.json"
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 600
    sys.exit(wait(path, timeout=timeout))
