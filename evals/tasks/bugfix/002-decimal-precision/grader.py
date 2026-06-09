"""Programmatic grader for 002-decimal-precision.

Ground truth = a Decimal half-up reference. The model's float output is compared
to it per case. Naive round() fixes pass the visible test but fail sealed half-up
boundary cases — that divergence is the signal.

Invocation:
    python grader.py --workdir <path> --result <result.json> --out <score.json>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path


# Inputs chosen so float repr error makes naive round() return the wrong cent
# on several of them (the *_boundary cases).
SEALED_INPUTS = [
    (19.99, 3, 0.0),       # simple
    (2.675, 1, 0.0),       # boundary: naive→2.67, correct→2.68
    (1.005, 1, 0.0),       # boundary: naive→1.0,  correct→1.01
    (0.125, 1, 0.0),       # boundary: banker's→0.12, half-up→0.13
    (0.005, 1, 0.0),       # boundary: naive→0.0,  correct→0.01
    (10.00, 1, 0.085),     # tax
    (9.99, 2, 0.07),       # tax, three-dp intermediate
    (100.00, 1, 0.0),      # round number
    (3.33, 3, 0.0),        # repeating-ish
    (1234.565, 1, 0.0),    # boundary at larger magnitude
    (49.95, 4, 0.20),      # tax multi-quantity
    (2.46, 1, 0.0),        # already 2dp
]


def _ref(unit_price, quantity, tax_rate) -> float:
    up = Decimal(str(unit_price))
    qt = Decimal(str(quantity))
    tr = Decimal(str(tax_rate))
    total = up * qt * (Decimal(1) + tr)
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "tests_passed": 0,
        "tests_total": len(SEALED_INPUTS),
        "no_extra_files": False,
        "within_diff_limit": True,
    }

    path = workdir / "invoice.py"
    if not path.exists():
        failures.append("invoice.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    allowed = {"invoice.py", "test_invoice.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    spec = importlib.util.spec_from_file_location("submission_invoice", path)
    if spec is None or spec.loader is None:
        failures.append("could not import invoice.py")
        return _verdict(False, 0.0, breakdown, failures)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        failures.append(f"import error: {e!r}")
        return _verdict(False, 0.0, breakdown, failures)

    fn = getattr(mod, "line_total", None)
    if fn is None:
        failures.append("function `line_total` not exported")
        return _verdict(False, 0.0, breakdown, failures)

    for up, qt, tr in SEALED_INPUTS:
        expected = _ref(up, qt, tr)
        try:
            got = fn(up, qt, tr)
        except Exception as e:
            failures.append(f"line_total({up}, {qt}, {tr}): raised {e!r}")
            continue
        if not isinstance(got, (int, float)):
            failures.append(f"line_total({up}, {qt}, {tr}): returned non-numeric {got!r}")
            continue
        if abs(float(got) - expected) >= 0.0001:
            failures.append(f"line_total({up}, {qt}, {tr}): expected {expected}, got {got}")
        else:
            breakdown["tests_passed"] += 1

    test_score = breakdown["tests_passed"] / breakdown["tests_total"]
    overall = round(test_score * (1.0 if breakdown["no_extra_files"] else 0.85), 3)
    passed = (test_score == 1.0) and breakdown["no_extra_files"]
    return _verdict(passed, overall, breakdown, failures)


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "002-decimal-precision", "pass": passed, "score": score,
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
        if diff_lines > 30:
            score["breakdown"]["within_diff_limit"] = False
            score["failures"].append(f"diff exceeds 30-line limit: {diff_lines}")
            score["pass"] = False
            score["score"] = min(score["score"], 0.5)
    except Exception:
        pass

    args.out.write_text(json.dumps(score, indent=2))
    print(json.dumps(score, indent=2))
    return 0 if score["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
