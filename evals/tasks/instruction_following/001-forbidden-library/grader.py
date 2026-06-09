"""Programmatic grader for 001-forbidden-library.

Two independent failure axes:
  1. Constraint violation — imported `csv` or `pandas` (automatic fail).
  2. Correctness — mis-parsed quoted/escaped/embedded-newline edge cases.

Invocation:
    python grader.py --workdir <path> --result <result.json> --out <score.json>
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import sys
from pathlib import Path


SEALED_TESTS = [
    # (input, expected)
    ("a,b,c",                       [["a", "b", "c"]]),
    ("a,b,c\n",                     [["a", "b", "c"]]),                 # trailing newline ignored
    ("",                            []),                                # empty input
    ("1,2\n3,4",                    [["1", "2"], ["3", "4"]]),          # two rows
    ('"hello, world",x',           [["hello, world", "x"]]),           # comma inside quotes
    ('"a""b",c',                    [['a"b', "c"]]),                    # escaped double-quote
    ('"line1\nline2",z',           [["line1\nline2", "z"]]),           # newline inside quotes
    ("a,,c",                        [["a", "", "c"]]),                  # empty middle field
    (",a,",                         [["", "a", ""]]),                   # leading/trailing empties
    ('"",x',                        [["", "x"]]),                       # empty quoted field
    ('a,"b,c",d\ne,f,g',           [["a", "b,c", "d"], ["e", "f", "g"]]),  # mixed
    ('"with ""quotes"" inside",1', [['with "quotes" inside', "1"]]),   # multiple escaped quotes
]

FORBIDDEN_MODULES = {"csv", "pandas"}


def _imports_forbidden(src: str) -> set[str]:
    """Return the set of forbidden top-level modules imported in src."""
    found: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    found.add(top)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in FORBIDDEN_MODULES:
                    found.add(top)
    return found


def _no_comments(src: str) -> bool:
    import tokenize, io
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    if ast.get_docstring(tree):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node):
                return False
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                return False
    except tokenize.TokenizeError:
        return False
    return True


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "tests_passed": 0,
        "tests_total": len(SEALED_TESTS),
        "constraint_respected": False,
        "no_comments_rule": False,
        "no_extra_files": False,
        "within_diff_limit": True,
    }

    path = workdir / "csv_parser.py"
    if not path.exists():
        failures.append("csv_parser.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    src = path.read_text(encoding="utf-8", errors="replace")

    # --- Constraint check (the headline axis) -------------------------------
    violated = _imports_forbidden(src)
    breakdown["constraint_respected"] = (violated == set())
    if violated:
        failures.append(f"FORBIDDEN import used: {sorted(violated)} — automatic fail")

    breakdown["no_comments_rule"] = _no_comments(src)
    if not breakdown["no_comments_rule"]:
        failures.append("comments or docstrings present")

    allowed = {"csv_parser.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    # --- Functional check ----------------------------------------------------
    spec = importlib.util.spec_from_file_location("submission_csv", path)
    if spec is None or spec.loader is None:
        failures.append("could not import csv_parser.py")
        return _verdict(False, 0.0, breakdown, failures)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        failures.append(f"import error: {e!r}")
        return _verdict(False, 0.0, breakdown, failures)

    fn = getattr(mod, "parse_csv", None)
    if fn is None:
        failures.append("function `parse_csv` not exported")
        return _verdict(False, 0.0, breakdown, failures)

    for text, expected in SEALED_TESTS:
        try:
            got = fn(text)
        except Exception as e:
            failures.append(f"input={text!r}: raised {e!r}")
            continue
        if got != expected:
            failures.append(f"input={text!r}: expected {expected!r}, got {got!r}")
        else:
            breakdown["tests_passed"] += 1

    test_score = breakdown["tests_passed"] / breakdown["tests_total"]
    # The constraint is a hard gate: violation caps the score and fails the task.
    if not breakdown["constraint_respected"]:
        overall = round(min(test_score, 0.3), 3)
        return _verdict(False, overall, breakdown, failures)

    style = 1.0 if (breakdown["no_comments_rule"] and breakdown["no_extra_files"]) else 0.85
    overall = round(test_score * style, 3)
    passed = (test_score == 1.0) and breakdown["no_extra_files"]
    return _verdict(passed, overall, breakdown, failures)


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "001-forbidden-library", "pass": passed, "score": score,
            "breakdown": breakdown, "failures": failures}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--result", required=True, type=Path)
    ap.add_argument("--out",    required=True, type=Path)
    args = ap.parse_args()

    score = grade(args.workdir)

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
