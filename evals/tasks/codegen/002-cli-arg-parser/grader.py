"""Programmatic grader for 002-cli-arg-parser.

Invocation:
    python grader.py --workdir <path> --result <result.json> --out <score.json>
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


# Test data with known counts
# Content: "hello world\nfoo bar baz\n"
#   lines = 2, words = 5, chars = 24
SAMPLE_CONTENT = "hello world\nfoo bar baz\n"
SAMPLE_LINES = 2
SAMPLE_WORDS = 5
SAMPLE_CHARS = 24

# Additional fixtures for edge cases
SINGLE_LINE = "one two three"           # lines=0 (no \n), words=3, chars=13
EMPTY = ""                              # lines=0, words=0, chars=0
MULTILINE = "a\nb\nc\nd\n"             # lines=4, words=4, chars=8


def _run(script: Path, args: list[str], cwd: Path | None = None, timeout: int = 10) -> tuple[int, str, str]:
    result = subprocess.run(
        [sys.executable, str(script)] + args,
        capture_output=True, text=True, timeout=timeout,
        cwd=cwd or script.parent,
    )
    return result.returncode, result.stdout, result.stderr


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown: dict = {
        "tests_passed": 0,
        "tests_total": 0,
        "no_comments_rule": False,
        "no_extra_files": False,
        "within_diff_limit": True,
    }

    script = workdir / "wordcount.py"
    if not script.exists():
        failures.append("wordcount.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    # Comment/docstring check
    src = script.read_text(encoding="utf-8", errors="replace")
    breakdown["no_comments_rule"] = _no_comments(src)
    if not breakdown["no_comments_rule"]:
        failures.append("comments or docstrings present")

    # No extra files
    allowed = {"wordcount.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    # Create temp test files
    import os
    tmp = workdir / "_test_data"
    tmp.mkdir(exist_ok=True)
    sample_f  = tmp / "sample.txt";  sample_f.write_text(SAMPLE_CONTENT)
    single_f  = tmp / "single.txt";  single_f.write_text(SINGLE_LINE)
    empty_f   = tmp / "empty.txt";   empty_f.write_text(EMPTY)
    multi_f   = tmp / "multi.txt";   multi_f.write_text(MULTILINE)

    def check(label: str, args: list[str], expected_rc: int, expected_stdout: str | None = None,
               stderr_nonempty: bool = False, cwd: Path | None = None) -> None:
        breakdown["tests_total"] += 1
        try:
            rc, out, err = _run(script, args, cwd=cwd)
        except subprocess.TimeoutExpired:
            failures.append(f"{label}: timed out")
            return
        except Exception as e:
            failures.append(f"{label}: error {e!r}")
            return
        if rc != expected_rc:
            failures.append(f"{label}: exit code {rc} (expected {expected_rc}); stderr={err.strip()!r}")
            return
        if expected_stdout is not None and out.strip() != expected_stdout.strip():
            failures.append(f"{label}: stdout {out.strip()!r} != {expected_stdout.strip()!r}")
            return
        if stderr_nonempty and not err.strip():
            failures.append(f"{label}: expected non-empty stderr")
            return
        breakdown["tests_passed"] += 1

    # Run file-based tests with cwd=tmp and bare filenames so output is "5 sample.txt" not full path
    # -w / --words
    check("-w sample",   ["-w",      "sample.txt"], 0, f"{SAMPLE_WORDS} sample.txt", cwd=tmp)
    check("--words",     ["--words", "sample.txt"], 0, f"{SAMPLE_WORDS} sample.txt", cwd=tmp)

    # -l / --lines
    check("-l sample",   ["-l",      "sample.txt"], 0, f"{SAMPLE_LINES} sample.txt", cwd=tmp)
    check("--lines",     ["--lines", "sample.txt"], 0, f"{SAMPLE_LINES} sample.txt", cwd=tmp)

    # -c / --chars
    check("-c sample",   ["-c",      "sample.txt"], 0, f"{SAMPLE_CHARS} sample.txt", cwd=tmp)
    check("--chars",     ["--chars", "sample.txt"], 0, f"{SAMPLE_CHARS} sample.txt", cwd=tmp)

    # Default (no flags) — must output lines, words, chars in that order
    expected_default = f"{SAMPLE_LINES} sample.txt\n{SAMPLE_WORDS} sample.txt\n{SAMPLE_CHARS} sample.txt"
    check("default all", ["sample.txt"], 0, expected_default, cwd=tmp)

    # Multiple flags — fixed order: lines, words, chars
    expected_lw = f"{SAMPLE_LINES} sample.txt\n{SAMPLE_WORDS} sample.txt"
    check("-l -w order", ["-l", "-w", "sample.txt"], 0, expected_lw, cwd=tmp)

    # Empty file
    check("-w empty",    ["-w", "empty.txt"], 0, "0 empty.txt", cwd=tmp)
    check("-l empty",    ["-l", "empty.txt"], 0, "0 empty.txt", cwd=tmp)
    check("-c empty",    ["-c", "empty.txt"], 0, "0 empty.txt", cwd=tmp)

    # Multiline file
    check("-l multi",    ["-l", "multi.txt"], 0, "4 multi.txt", cwd=tmp)
    check("-w multi",    ["-w", "multi.txt"], 0, "4 multi.txt", cwd=tmp)
    check("-c multi",    ["-c", "multi.txt"], 0, "8 multi.txt", cwd=tmp)

    # No trailing newline — lines counts \n chars (0), not splitlines() (1)
    check("-l single",   ["-l", "single.txt"], 0, "0 single.txt", cwd=tmp)
    check("-w single",   ["-w", "single.txt"], 0, "3 single.txt", cwd=tmp)
    check("-c single",   ["-c", "single.txt"], 0, "13 single.txt", cwd=tmp)

    # Missing file → exit 1 (run from workdir, file genuinely absent)
    check("missing file", ["-w", "nonexistent.txt"], 1, stderr_nonempty=True)

    # --help → exit 0
    check("--help", ["--help"], 0)

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    n = breakdown["tests_total"]
    passed = breakdown["tests_passed"]
    test_score = passed / n if n else 0.0
    style_bonus = 1.0 if (breakdown["no_comments_rule"] and breakdown["no_extra_files"]) else 0.85
    overall = round(test_score * style_bonus, 3)
    ok = (passed == n) and breakdown["no_comments_rule"] and breakdown["no_extra_files"]
    return _verdict(ok, overall, breakdown, failures)


def _no_comments(src: str) -> bool:
    import ast, tokenize, io
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
    except tokenize.TokenError:
        return False
    return True


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "002-cli-arg-parser", "pass": passed, "score": score,
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
        if diff_lines > 100:
            score["breakdown"]["within_diff_limit"] = False
            score["failures"].append(f"diff exceeds 100-line limit: {diff_lines}")
            score["pass"] = False
            score["score"] = min(score["score"], 0.5)
    except Exception:
        pass

    args.out.write_text(json.dumps(score, indent=2))
    print(json.dumps(score, indent=2))
    return 0 if score["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
