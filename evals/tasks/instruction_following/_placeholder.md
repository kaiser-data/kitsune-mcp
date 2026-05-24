# instruction_following/

Tasks where the meta-instructions matter as much as the task itself.

## Task shape
- Fixture includes a meta-instruction file: `CLAUDE.md`, `.cursorrules`, `AGENTS.md`, or a system-prompt addendum in `task.yaml`
- The task itself is simple
- The grader checks adherence to the meta-instructions:
  - "No inline comments" → count comments in the diff
  - "Do not use library X" → grep imports
  - "Match snake_case style" → AST check on identifiers
  - "Edit only these paths" → already covered by `allowed_paths`

## Surfaces these should exercise
- Honouring `CLAUDE.md` / `.cursorrules` / `AGENTS.md`
- Style matching (the model's defaults vs. the project's style)
- Forbidden-library / forbidden-pattern adherence
- Comment density limits
- File-creation prohibitions

See ROADMAP.md → Phase 1 → instruction_following for the initial set.
