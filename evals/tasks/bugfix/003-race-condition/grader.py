"""Programmatic grader for 003-race-condition.

Two axes (both required to pass):
  1. Functional — under barrier-aligned, switch-forced high contention, `total`
     and `history` are BOTH exact across many trials. The buggy RMW loses
     `total` updates; a lock-based fix is deterministically correct.
  2. Structural — a synchronisation primitive is present. This defeats the
     fake fix of merely deleting the latency (which would pass functionally on
     CPython but is not thread-safety).

Invocation:
    python grader.py --workdir <path> --result <result.json> --out <score.json>
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import threading
from pathlib import Path


N_THREADS = 16
PER_THREAD = 2500
TRIALS = 8

SYNC_PATTERNS = [
    r"\bLock\s*\(",
    r"\bRLock\s*\(",
    r"\bSemaphore\s*\(",
    r"\bBoundedSemaphore\s*\(",
    r"\bCondition\s*\(",
    r"\bQueue\s*\(",
    r"with\s+[\w\.]*lock",
]


def _has_sync(src: str) -> bool:
    low = src
    for pat in SYNC_PATTERNS:
        if re.search(pat, low, re.IGNORECASE):
            return True
    return False


def _run_stress(cls) -> list[tuple[int, int, int]]:
    old = sys.getswitchinterval()
    sys.setswitchinterval(1e-9)
    results: list[tuple[int, int, int]] = []
    try:
        for _ in range(TRIALS):
            obj = cls()
            barrier = threading.Barrier(N_THREADS)

            def work():
                barrier.wait()
                for _ in range(PER_THREAD):
                    obj.add(1)

            threads = [threading.Thread(target=work) for _ in range(N_THREADS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            results.append((obj.total, len(obj.history), N_THREADS * PER_THREAD))
    finally:
        sys.setswitchinterval(old)
    return results


def grade(workdir: Path) -> dict:
    failures: list[str] = []
    breakdown = {
        "synchronization_present": False,
        "trials_total_correct": 0,
        "trials_history_correct": 0,
        "trials_total": TRIALS,
        "no_extra_files": False,
        "within_diff_limit": True,
    }

    path = workdir / "metrics.py"
    if not path.exists():
        failures.append("metrics.py missing")
        return _verdict(False, 0.0, breakdown, failures)

    src = path.read_text(encoding="utf-8", errors="replace")

    # --- Axis 2: structural sync check --------------------------------------
    breakdown["synchronization_present"] = _has_sync(src)
    if not breakdown["synchronization_present"]:
        failures.append("no synchronization primitive found (Lock/RLock/Semaphore/Condition/Queue)")

    allowed = {"metrics.py", "test_metrics.py"}
    actual = {p.name for p in workdir.iterdir() if p.is_file() and not p.name.startswith(".")}
    extras = actual - allowed
    breakdown["no_extra_files"] = (extras == set())
    if extras:
        failures.append(f"extra files created: {sorted(extras)}")

    # --- Axis 1: functional stress ------------------------------------------
    spec = importlib.util.spec_from_file_location("submission_metrics", path)
    if spec is None or spec.loader is None:
        failures.append("could not import metrics.py")
        return _verdict(False, 0.0, breakdown, failures)
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as e:
        failures.append(f"import error: {e!r}")
        return _verdict(False, 0.0, breakdown, failures)

    cls = getattr(mod, "MetricsCollector", None)
    if cls is None:
        failures.append("MetricsCollector not exported")
        return _verdict(False, 0.0, breakdown, failures)

    try:
        results = _run_stress(cls)
    except Exception as e:
        failures.append(f"stress run crashed: {e!r}")
        return _verdict(False, 0.0, breakdown, failures)

    for total, hist, expected in results:
        if total == expected:
            breakdown["trials_total_correct"] += 1
        if hist == expected:
            breakdown["trials_history_correct"] += 1
    if breakdown["trials_total_correct"] < TRIALS:
        ex = next(((t, h, e) for t, h, e in results if t != e), None)
        failures.append(f"lost updates: {TRIALS - breakdown['trials_total_correct']}/{TRIALS} trials wrong (e.g. total={ex[0]} expected={ex[2]})")
    if breakdown["trials_history_correct"] < TRIALS:
        failures.append(f"history incomplete in {TRIALS - breakdown['trials_history_correct']}/{TRIALS} trials (persistence dropped)")

    # --- Scoring -------------------------------------------------------------
    func_ok = (breakdown["trials_total_correct"] == TRIALS and
               breakdown["trials_history_correct"] == TRIALS)
    func_frac = (breakdown["trials_total_correct"] + breakdown["trials_history_correct"]) / (2 * TRIALS)
    overall = round(
        0.6 * func_frac
        + 0.4 * (1.0 if breakdown["synchronization_present"] else 0.0),
        3,
    )
    passed = func_ok and breakdown["synchronization_present"] and breakdown["no_extra_files"]
    return _verdict(passed, overall, breakdown, failures)


def _verdict(passed: bool, score: float, breakdown: dict, failures: list[str]) -> dict:
    return {"task_id": "003-race-condition", "pass": passed, "score": score,
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
