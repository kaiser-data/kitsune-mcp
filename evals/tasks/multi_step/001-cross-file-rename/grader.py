"""Programmatic grader for 001-cross-file-rename.

Two axes:
  1. Completeness — the old token `PaymentGateway` must appear ZERO times
     anywhere under the workdir (the multi-file coordination signal).
  2. Behaviour — a sealed test using the NEW name + NEW registry key passes.

A partial rename (misses the string key, __all__, or README) fails axis 1 even
if the code imports fine — that's the whole point.

Invocation:
    python grader.py --workdir <path> --result <result.json> --out <score.json>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


OLD = "PaymentGateway"
NEW = "StripeGateway"

# Files/dirs to scan for residual old-name occurrences (skip caches & the harness)
SKIP_DIRS = {"__pycache__", ".git"}
SCAN_EXT = {".py", ".md", ".txt", ".cfg", ".toml", ".json", ".yaml", ".yml", ""}


def _scan_residual(workdir: Path) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    for p in sorted(workdir.rglob("*")):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if not p.is_file():
            continue
        if p.suffix not in SCAN_EXT:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if OLD in line:
                rel = p.relative_to(workdir)
                hits.append((str(rel), lineno, line.strip()[:80]))
    return hits


SEALED_TEST = '''
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from bank import StripeGateway
from bank.registry import make_gateway
from bank.handlers import process_payment


def run():
    # direct construction + behaviour
    gw = StripeGateway()
    out = gw.charge(100)
    assert out == {"gateway": "StripeGateway", "amount": 100, "status": "ok"}, out

    # registry by NEW string key
    gw2 = make_gateway("StripeGateway")
    assert isinstance(gw2, StripeGateway), type(gw2)
    assert gw2.charge(50)["gateway"] == "StripeGateway"

    # old key must be gone
    try:
        make_gateway("PaymentGateway")
        raise AssertionError("old registry key 'PaymentGateway' still resolves")
    except KeyError:
        pass

    # handler still works
    assert process_payment(25)["status"] == "ok"
    print("SEALED_OK")


if __name__ == "__main__":
    run()
'''


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "residual_old_name": -1,
        "rename_complete": False,
        "sealed_test_pass": False,
        "within_diff_limit": True,
    }

    # --- Axis 1: completeness scan ------------------------------------------
    hits = _scan_residual(workdir)
    breakdown["residual_old_name"] = len(hits)
    breakdown["rename_complete"] = (len(hits) == 0)
    if hits:
        for rel, lineno, snippet in hits[:8]:
            failures.append(f"residual '{OLD}' at {rel}:{lineno}: {snippet}")
        if len(hits) > 8:
            failures.append(f"...and {len(hits) - 8} more residual occurrences")

    # --- Axis 2: sealed behavioural test ------------------------------------
    sealed = workdir / "test_sealed.py"
    sealed.write_text(SEALED_TEST)
    try:
        proc = subprocess.run(
            [sys.executable, str(sealed)],
            cwd=workdir, capture_output=True, text=True, timeout=30,
        )
        breakdown["sealed_test_pass"] = (proc.returncode == 0 and "SEALED_OK" in proc.stdout)
        if not breakdown["sealed_test_pass"]:
            msg = (proc.stderr.strip() or proc.stdout.strip())[-220:]
            failures.append(f"sealed test failed: {msg}")
    finally:
        sealed.unlink(missing_ok=True)

    # --- Scoring -------------------------------------------------------------
    overall = round(
        0.5 * (1.0 if breakdown["rename_complete"] else 0.0)
        + 0.5 * (1.0 if breakdown["sealed_test_pass"] else 0.0),
        3,
    )
    passed = breakdown["rename_complete"] and breakdown["sealed_test_pass"]
    return _verdict(passed, overall, breakdown, failures)


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "001-cross-file-rename", "pass": passed, "score": score,
            "breakdown": breakdown, "failures": failures}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--result", required=True, type=Path)
    ap.add_argument("--out",    required=True, type=Path)
    args = ap.parse_args()

    score = grade(args.workdir.resolve())

    try:
        result = json.loads(args.result.read_text())
        diff_lines = len((result.get("diff") or "").splitlines())
        if diff_lines > 120:
            score["breakdown"]["within_diff_limit"] = False
            score["failures"].append(f"diff exceeds 120-line limit: {diff_lines}")
            score["pass"] = False
            score["score"] = min(score["score"], 0.5)
    except Exception:
        pass

    args.out.write_text(json.dumps(score, indent=2))
    print(json.dumps(score, indent=2))
    return 0 if score["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
