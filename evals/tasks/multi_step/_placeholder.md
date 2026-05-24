# multi_step/

Tasks requiring planning and coordinated changes across multiple files or stages.

## Task shape
- Fixture is a small but realistic codebase (5–30 files)
- Task requires either:
  - Cross-file consistency (rename, type change, API migration)
  - Explicit plan-then-execute (a `PLAN.md` is required output)
  - Investigation-before-action (the task description is incomplete; correct answer requires reading multiple files)
- Grader inspects:
  - All affected files updated consistently
  - Plan exists and was followed (where required)
  - Tool trace shows ≥N read operations before first write (where required)

See ROADMAP.md → Phase 1 → multi_step for the initial set.
