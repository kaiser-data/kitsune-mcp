"""Programmatic grader for 001-slugify.

Invocation contract:
    python grader.py --workdir <path-to-applied-result> --result <path-to-result.json> --out <path-for-score.json>

The grader is run AFTER the system's diff has been applied to a clean copy of
the fixture. It is sealed — the system under test must never see this file.

Score JSON schema (a separate concern from result.schema.json):
{
  "task_id": "001-slugify",
  "pass": bool,
  "score": float,            # 0.0–1.0
  "breakdown": {
      "tests_passed": int,
      "tests_total": int,
      "no_comments_rule": bool,
      "no_extra_files": bool,
      "within_diff_limit": bool
  },
  "failures": [str, ...]      # human-readable reasons, empty on pass
}
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


SEALED_TESTS = [
    # (input, max_length, expected) — covers normal, edge, unicode, truncation
    ("Hello World",      50, "hello-world"),
    ("  spaces   here ", 50, "spaces-here"),
    ("UPPER lower",      50, "upper-lower"),
    ("a!@#$%b",          50, "a-b"),
    ("---leading---",    50, "leading"),
    ("",                 50, ""),
    ("!!!---!!!",        50, ""),
    ("multi   spaces",   50, "multi-spaces"),
    ("This is a longer string that exceeds the limit", 20, "this-is-a-longer"),
    ("nobreakwithinlimit", 10, "nobreakwit"),  # forced cut, no hyphen boundary available
    ("café latte",       50, "caf-latte"),   # non-ASCII handled as non-alphanumeric (acceptable)
    ("trailing-hyphen-", 50, "trailing-hyphen"),
]


def _no_comments(slugify_src: str) -> bool:
    """The task says no comments. Check: no # comments and no docstrings."""
    try:
        tree = ast.parse(slugify_src)
    except SyntaxError:
        return False
    # Walk for docstrings on functions and the module.
    if ast.get_docstring(tree):
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if ast.get_docstring(node):
                return False
    # Check for # comments by re-tokenising.
    import tokenize
    import io
    try:
        for tok in tokenize.generate_tokens(io.StringIO(slugify_src).readline):
            if tok.type == tokenize.COMMENT:
                return False
    except tokenize.TokenError:
        return False
    return True


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "tests_passed": 0,
        "tests_total": len(SEALED_TESTS),
        "no_comments_rule": False,
        "no_extra_files": False,
        "within_diff_limit": True,  # set by the harness, optimistic default
    }

    slugify_path = workdir / "slugify.py"
    if not slugify_path.exists():
        failures.append("slugify.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    # Sealed comment-rule check
    src = slugify_path.read_text(encoding="utf-8", errors="replace")
    breakdown["no_comments_rule"] = _no_comments(src)
    if not breakdown["no_comments_rule"]:
        failures.append("comments or docstrings present (system prompt forbade them)")

    # No-extra-files check — only allow slugify.py changes
    allowed = {"slugify.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    # Load and exercise
    spec = importlib.util.spec_from_file_location("submission_slugify", slugify_path)
    if spec is None or spec.loader is None:
        failures.append("could not import slugify.py")
        return _verdict(False, 0.0, breakdown, failures)
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        failures.append(f"import error: {e!r}")
        return _verdict(False, 0.0, breakdown, failures)

    fn = getattr(module, "slugify", None)
    if fn is None:
        failures.append("function `slugify` not exported")
        return _verdict(False, 0.0, breakdown, failures)

    for text, max_len, expected in SEALED_TESTS:
        try:
            got = fn(text, max_len)
        except Exception as e:
            failures.append(f"input={text!r}, max={max_len}: raised {e!r}")
            continue
        if got != expected:
            failures.append(f"input={text!r}, max={max_len}: expected {expected!r}, got {got!r}")
        else:
            breakdown["tests_passed"] += 1

    test_score = breakdown["tests_passed"] / breakdown["tests_total"]
    style_score = 1.0 if (breakdown["no_comments_rule"] and breakdown["no_extra_files"]) else 0.7
    overall = test_score * style_score
    passed = (test_score == 1.0) and breakdown["no_comments_rule"] and breakdown["no_extra_files"]

    return _verdict(passed, round(overall, 3), breakdown, failures)


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {
        "task_id": "001-slugify",
        "pass": passed,
        "score": score,
        "breakdown": breakdown,
        "failures": failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--result", required=True, type=Path, help="result.json from the runner (for diff-line check)")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    score = grade(args.workdir.resolve())

    # Diff-line limit check (read from result.json)
    try:
        result = json.loads(args.result.read_text())
        diff_lines = len((result.get("diff") or "").splitlines())
        if diff_lines > 60:
            score["breakdown"]["within_diff_limit"] = False
            score["failures"].append(f"diff exceeds 60-line limit: {diff_lines} lines")
            score["pass"] = False
            score["score"] = min(score["score"], 0.5)
    except Exception:
        pass

    args.out.write_text(json.dumps(score, indent=2))
    print(json.dumps(score, indent=2))
    return 0 if score["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
