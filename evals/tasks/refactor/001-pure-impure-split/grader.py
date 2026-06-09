"""Programmatic grader for 001-pure-impure-split.

Three axes:
  1. compute_stats exists and is structurally PURE (no open/print in its body).
  2. compute_stats is functionally correct, callable in isolation (no files).
  3. Behaviour preserved — the existing test_stats.py suite still passes.

Invocation:
    python grader.py --workdir <path> --result <result.json> --out <score.json>
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


PURE_CASES = [
    ([1, 2, 3, 4],   {"total": 10, "mean": 2.5,  "max": 4,    "count": 4}),
    ([42],           {"total": 42, "mean": 42.0, "max": 42,   "count": 1}),
    ([],             {"total": 0,  "mean": 0.0,  "max": None, "count": 0}),
    ([5, 5, 5],      {"total": 15, "mean": 5.0,  "max": 5,    "count": 3}),
    ([-3, 3],        {"total": 0,  "mean": 0.0,  "max": 3,    "count": 2}),
    ([10, 20, 30, 40, 50], {"total": 150, "mean": 30.0, "max": 50, "count": 5}),
]


def _find_func(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _is_pure(func: ast.FunctionDef) -> tuple[bool, list[str]]:
    """No calls to open/print; no `with open`. Returns (pure, reasons)."""
    reasons: list[str] = []
    for node in ast.walk(func):
        if isinstance(node, ast.Call):
            fn = node.func
            fname = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if fname in {"open", "print", "input"}:
                reasons.append(f"calls {fname}()")
    return (len(reasons) == 0, reasons)


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "pure_function_present": False,
        "purity_verified": False,
        "pure_cases_passed": 0,
        "pure_cases_total": len(PURE_CASES),
        "existing_tests_pass": False,
        "no_extra_files": False,
        "within_diff_limit": True,
    }

    path = workdir / "stats.py"
    if not path.exists():
        failures.append("stats.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    src = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        failures.append(f"syntax error: {e}")
        return _verdict(False, 0.0, breakdown, failures)

    allowed = {"stats.py", "test_stats.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    # --- Axis 1: pure function present & structurally pure -------------------
    cs = _find_func(tree, "compute_stats")
    if cs is None:
        failures.append("compute_stats not defined")
    else:
        breakdown["pure_function_present"] = True
        pure, reasons = _is_pure(cs)
        breakdown["purity_verified"] = pure
        if not pure:
            failures.append(f"compute_stats not pure: {', '.join(reasons)}")

    # --- Axis 2: functional correctness in isolation -------------------------
    spec = importlib.util.spec_from_file_location("submission_stats", path)
    mod = None
    if spec and spec.loader:
        try:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            failures.append(f"import error: {e!r}")

    if mod is not None:
        fn = getattr(mod, "compute_stats", None)
        if fn is None:
            failures.append("compute_stats not importable")
        else:
            for nums, expected in PURE_CASES:
                try:
                    got = fn(list(nums))
                except Exception as e:
                    failures.append(f"compute_stats({nums}): raised {e!r}")
                    continue
                if got != expected:
                    failures.append(f"compute_stats({nums}): expected {expected}, got {got}")
                else:
                    breakdown["pure_cases_passed"] += 1

    # --- Axis 3: behaviour preserved (existing suite green) ------------------
    test_file = workdir / "test_stats.py"
    if test_file.exists():
        proc = subprocess.run(
            [sys.executable, str(test_file)],
            cwd=workdir, capture_output=True, text=True, timeout=30,
        )
        breakdown["existing_tests_pass"] = (proc.returncode == 0)
        if proc.returncode != 0:
            failures.append(f"existing tests fail: {proc.stderr.strip()[-200:]}")
    else:
        failures.append("test_stats.py missing (should not be modified/removed)")

    # --- Scoring -------------------------------------------------------------
    func_score = breakdown["pure_cases_passed"] / breakdown["pure_cases_total"]
    gates = [
        breakdown["purity_verified"],
        func_score == 1.0,
        breakdown["existing_tests_pass"],
        breakdown["no_extra_files"],
    ]
    overall = round(
        0.4 * func_score
        + 0.3 * (1.0 if breakdown["purity_verified"] else 0.0)
        + 0.3 * (1.0 if breakdown["existing_tests_pass"] else 0.0),
        3,
    )
    passed = all(gates)
    return _verdict(passed, overall, breakdown, failures)


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "001-pure-impure-split", "pass": passed, "score": score,
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
        if diff_lines > 60:
            score["breakdown"]["within_diff_limit"] = False
            score["failures"].append(f"diff exceeds 60-line limit: {diff_lines}")
            score["pass"] = False
            score["score"] = min(score["score"], 0.5)
    except Exception:
        pass

    args.out.write_text(json.dumps(score, indent=2))
    print(json.dumps(score, indent=2))
    return 0 if score["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
