# Programmatic grading

Default to this. Cheap, deterministic, no judge bias.

## Tools

- **`pytest`** — sealed test files run against the post-diff workdir
- **`coverage.py`** — for testgen tasks
- **`ruff` + `mypy --strict`** — code-quality gates
- **`git apply --check`** — diff validity
- **`ast`** — structural checks (no comments, function count, max length per function)
- **`mutmut` or `cosmic-ray`** — for testgen tasks: do the tests catch planted mutations?
- **`semgrep`** — pattern-based forbidden-construct checks
- **`tokenize`** — counting comments, docstrings

## Grader script contract

Every `grader.py` is invoked as:

```
python grader.py --workdir <applied-result-dir> --result <result.json> --out <score.json>
```

`--workdir` may be passed as a relative path; graders must call
`args.workdir.resolve()` before use so that subprocess `cwd=`, `relative_to()`,
and import-from-file operations are immune to the invoking process's cwd.

Returns exit 0 on pass, non-zero on fail. Writes a score JSON containing:

```json
{
  "task_id": "...",
  "pass": true,
  "score": 0.95,
  "breakdown": {...},
  "failures": [...]
}
```

The breakdown should be granular enough to debug regressions ("which sub-check failed?").

See `tasks/codegen/001-slugify/grader.py` for a complete worked example.

## Caveats

- **Sealed tests must never appear in the fixture.** A system that reads its own grader will solve to-pass-not-to-be-correct. Keep `grader.py` and any sealed test files OUTSIDE `fixture/` and use `forbidden_paths` to prevent agentic systems from reading them.
- **Test the grader.** Run it against a known-good reference implementation (commit one alongside the task as `_reference/`). If your grader says the reference is wrong, the grader is wrong.
- **Don't grade what you didn't specify.** If `task.yaml` doesn't say "no docstrings", don't penalise docstrings.
