# bugfix/

Tasks where the fixture contains a failing test (or reproducer) and the system must locate and fix the bug.

## Task shape
- `fixture/` includes the buggy code AND a failing test (visible to the system)
- A sealed test file (outside `fixture/`) used by the grader — same scenarios, slightly different inputs, so the system can't just delete-the-test-and-pass
- Grader runs the sealed tests + lints + checks `allowed_paths`

## Surfaces these should exercise
- Single-line bugs (off-by-one, wrong operator)
- Logic bugs in flow control
- Concurrency bugs (race, deadlock, ordering)
- Boundary bugs (empty input, max int, recursion depth)
- Bugs caused by stale/inconsistent imports or deps

See ROADMAP.md → Phase 1 → bugfix for the initial set.
