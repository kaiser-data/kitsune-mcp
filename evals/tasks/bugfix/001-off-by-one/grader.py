"""Programmatic grader for 001-off-by-one.

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
    # (nums, target, expected)  — covers found/not-found/boundary/single
    ([1, 2, 3, 4, 5], 3,  2),   # found in middle
    ([1, 2, 3, 4, 5], 1,  0),   # found at start
    ([1, 2, 3, 4, 5], 5,  4),   # found at end
    ([1, 2, 3, 4, 5], 6, -1),   # not found — larger than all (the bug case)
    ([1, 2, 3, 4, 5], 0, -1),   # not found — smaller than all
    ([42],            42, 0),   # single element, found
    ([42],             1,-1),   # single element, not found
    ([1, 3, 5, 7, 9], 7,  3),   # odd-length, found right half
    ([1, 2, 3, 4],    2,  1),   # even-length, found left half
    ([1, 2, 3, 4],    3,  2),   # even-length, found right half
    ([1, 2, 3, 4],    5, -1),   # even-length, not found larger (bug case)
    ([2, 4, 6, 8, 10],10, 4),   # found last in larger list
]


class _BoundsProbe(list):
    """List that behaves normally but records any read past the end.

    A real bound fix never reads index >= len(nums); masking the resulting
    IndexError (try/except, contextlib.suppress, exec'd handlers) hides the
    exception but the out-of-range read itself is still recorded here.
    """

    def __init__(self, data):
        super().__init__(data)
        self.out_of_bounds = False

    def __getitem__(self, index):
        if isinstance(index, int) and index >= len(self):
            self.out_of_bounds = True
        return super().__getitem__(index)


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "tests_passed": 0,
        "tests_total": len(SEALED_TESTS),
        "minimal_diff": False,
        "no_exception_masking": True,
        "no_out_of_bounds_reads": True,
        "no_extra_files": False,
        "within_diff_limit": True,
    }

    bs_path = workdir / "binary_search.py"
    if not bs_path.exists():
        failures.append("binary_search.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    # No extra files (test_binary_search.py is allowed — it was in the fixture)
    allowed = {"binary_search.py", "test_binary_search.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    # Load module
    spec = importlib.util.spec_from_file_location("submission_bs", bs_path)
    if spec is None or spec.loader is None:
        failures.append("could not import binary_search.py")
        return _verdict(False, 0.0, breakdown, failures)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        failures.append(f"import error: {e!r}")
        return _verdict(False, 0.0, breakdown, failures)

    fn = getattr(mod, "binary_search", None)
    if fn is None:
        failures.append("function `binary_search` not exported")
        return _verdict(False, 0.0, breakdown, failures)

    for nums, target, expected in SEALED_TESTS:
        probe = _BoundsProbe(nums)
        try:
            got = fn(probe, target)
        except Exception as e:
            failures.append(f"binary_search({nums}, {target}): raised {e!r}")
            continue
        finally:
            if probe.out_of_bounds:
                breakdown["no_out_of_bounds_reads"] = False
        if got != expected:
            failures.append(f"binary_search({nums}, {target}): expected {expected}, got {got}")
        else:
            breakdown["tests_passed"] += 1
    if not breakdown["no_out_of_bounds_reads"]:
        failures.append("submission reads past the end of the list — search bound not fixed")

    # Minimal diff check: the fix is a one-word change (len(nums) → len(nums)-1)
    src = bs_path.read_text()
    breakdown["minimal_diff"] = "len(nums) - 1" in src or "len(nums)-1" in src

    # Catching IndexError returns -1 exactly where -1 is expected, so the
    # sealed tests cannot distinguish masking from a real bound fix. The
    # _BoundsProbe above is the behavioral backstop; this syntactic check
    # also rejects contextlib.suppress and exec/eval, which can hide a
    # handler from the AST walk.
    try:
        tree = ast.parse(src)
        breakdown["no_exception_masking"] = not any(
            _is_masking_node(n) for n in ast.walk(tree))
    except SyntaxError:
        breakdown["no_exception_masking"] = False
    if not breakdown["no_exception_masking"]:
        failures.append("exception handling masks the bug instead of fixing the search bound")

    test_score = breakdown["tests_passed"] / breakdown["tests_total"]
    # Reward minimal fix; penalise (but don't fail) verbose rewrites
    style = 1.0 if breakdown["minimal_diff"] and breakdown["no_extra_files"] else 0.85
    overall = round(test_score * style, 3)
    passed = (test_score == 1.0) and breakdown["no_extra_files"] \
        and breakdown["no_exception_masking"] and breakdown["no_out_of_bounds_reads"]
    return _verdict(passed, overall, breakdown, failures)


def _is_masking_node(node: ast.AST) -> bool:
    if isinstance(node, ast.ExceptHandler):
        return True
    if isinstance(node, ast.Call):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        return name in {"suppress", "exec", "eval"}
    return False


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "001-off-by-one", "pass": passed, "score": score,
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
        if diff_lines > 20:
            score["breakdown"]["within_diff_limit"] = False
            score["failures"].append(f"diff exceeds 20-line limit: {diff_lines}")
            score["pass"] = False
            score["score"] = min(score["score"], 0.5)
    except Exception:
        pass

    args.out.write_text(json.dumps(score, indent=2))
    print(json.dumps(score, indent=2))
    return 0 if score["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
