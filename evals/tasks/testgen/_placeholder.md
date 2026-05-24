# testgen/

Tasks where the system must produce tests for given code. Quality is measured by coverage and by ability to find planted bugs.

## Task shape
- `fixture/` includes a function/module to test, but NO test file
- Hidden mutant versions of the code (one or more bugs planted)
- Grader runs the system's tests against:
  1. The correct code (must pass)
  2. Each mutant (must FAIL — bug caught)
- Coverage measured via `coverage.py`; minimum threshold per task

## Surfaces these should exercise
- Parametric/property-based test generation (Hypothesis usage)
- Mock/fake generation for I/O code
- Regression-test creation from a bug report

See ROADMAP.md → Phase 1 → testgen for the initial set.
