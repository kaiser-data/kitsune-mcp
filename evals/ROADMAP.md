# ROADMAP — tests to add, in priority order

Each row is one concrete deliverable. Tick boxes as you implement.

## Phase 0 — foundations (do before any task)

- [ ] Finalise `tasks/schemas/task.schema.json` (current draft is workable but unreviewed).
- [ ] Finalise `tasks/schemas/result.schema.json`.
- [ ] Pick a harness: `inspect_ai` (recommended), `promptfoo`, or roll your own around the schemas. Document the choice in `harness/README.md`.
- [ ] Decide on sandbox: Docker (recommended for reproducibility), git worktree (cheap, less isolated), or remote VM. Document.
- [ ] Wire up at least two adapters end-to-end against the worked-example task (`001-slugify`) before adding more tasks. Validates the contract.

## Phase 1 — minimum viable comparison (1 task per category)

Goal: produce one publishable comparison across 3–5 systems on 9 tasks.

### Code generation (`tasks/codegen/`)
- [x] `001-slugify` — pure function from spec, deterministic grader *(worked example, stub provided)*
- [ ] `002-cli-arg-parser` — small CLI from man-page spec; tests check argv handling, exit codes, help text
- [ ] `003-async-rate-limited-fetcher` — async/concurrency primitives + back-pressure

### Bug fixing (`tasks/bugfix/`)
- [ ] `001-off-by-one` — single-file numeric bug; failing test provided
- [ ] `002-race-condition` — concurrency bug only reproducible under stress; tests use `pytest-asyncio` + many iterations
- [ ] `003-none-branch` — silent `None` handling that produces wrong-but-plausible output

### Refactoring (`tasks/refactor/`)
- [ ] `001-extract-method` — behaviour preservation check via existing test suite
- [ ] `002-pydantic-v1-to-v2` — real-world migration; verify all 4 schema patterns work post-migration
- [ ] `003-side-effect-extraction` — split mixed I/O code into pure + impure halves; tests assert the pure half is callable in isolation

### Test creation (`tasks/testgen/`)
- [ ] `001-coverage-target` — given a function, write tests that hit ≥90% branch coverage; grader uses `coverage.py`
- [ ] `002-property-tests` — Hypothesis-based; grader checks for `@given` decorators and that shrinking finds the planted bug
- [ ] `003-regression-test-for-known-bug` — given commit-A (buggy) and commit-B (fixed), write a test that fails at A and passes at B

### Tool use (`tasks/tool_use/`)
- [ ] `001-find-then-edit` — must `grep` before patching, not patch blindly
- [ ] `002-failed-tool-recovery` — first tool call deliberately wrong (e.g., wrong path); measure recovery
- [ ] `003-mcp-server-invocation` — agent must `shapeshift` into a server, call a tool, `shiftback` (project-specific, useful for kitsune-mcp's own dogfooding)

### Multi-step reasoning (`tasks/multi_step/`)
- [ ] `001-plan-then-execute` — task explicitly requires a written plan in `PLAN.md` before any edit; grader checks plan was produced AND that edits match it
- [ ] `002-cross-file-rename` — rename a symbol across N files including tests, docs, and configs
- [ ] `003-investigate-before-acting` — task description is misleading; grader checks model read ≥3 files (via tool trace) before patching

### Instruction following (`tasks/instruction_following/`)
- [ ] `001-honour-claudemd` — repo has CLAUDE.md saying "no inline comments"; grader counts comments in diff
- [ ] `002-forbidden-library` — "do not use `requests`, use `httpx`"
- [ ] `003-match-existing-style` — surrounding code uses snake_case; new code must too

### Ambiguous tasks (`tasks/ambiguous/`)
- [ ] `001-clarifying-vs-guessing` — underspecified API. Measures: did the system ask vs. pick? Both can be right; record which.
- [ ] `002-contradictory-spec` — README says X, tests say Y. Correct behaviour: notice and surface the contradiction.
- [ ] `003-stale-context` — comment claims behaviour X but code does Y. Correct behaviour: trust the code, flag the comment.

### Reliability (`tasks/reliability/`)
- [ ] `001-variance-pass-at-k` — re-run `codegen/001-slugify` 10× per system; report pass@1, pass@5, σ
- [ ] `002-long-context-degradation` — same task with 1K, 16K, 64K, 128K context filler; chart pass rate
- [ ] `003-prompt-injection-resistance` — task includes a malicious docstring ("ignore prior instructions and…"); grader checks instruction was ignored

## Phase 2 — depth (10+ tasks per category)

Once Phase 1 produces a real comparison, expand each category. Aim for:
- ≥5 tasks per category
- ≥3 difficulty tiers (easy / medium / hard) per category
- ≥2 languages where applicable (Python + TypeScript covers most users; add Go/Rust if your work involves them)

## Phase 3 — integration with public benchmarks

Document how to drive the same systems through:
- [ ] **SWE-bench Verified** — bug fixing on real PRs. Anthropic, OpenAI, Cognition all publish here. Most important external benchmark.
- [ ] **MultiPL-E** — codegen across 18 languages. Tests language breadth.
- [ ] **LiveCodeBench** — contamination-resistant (new problems monthly).
- [ ] **τ-bench** — tool use with simulated users.
- [ ] **Aider polyglot benchmark** — editing existing code across languages. Aider publishes a leaderboard worth referencing.

Each gets an `adapters/external/<name>.md` describing how to feed one of your tracked systems into it.

## Phase 4 — analysis tooling

- [ ] `analysis/cost_vs_quality.ipynb` — Pareto frontier plot
- [ ] `analysis/variance_report.ipynb` — error bars, confidence intervals, McNemar's tests on paired comparisons
- [ ] `analysis/leaderboard.md.j2` — auto-generated from `results/*.json`
- [ ] `analysis/regression_alerts.md` — flag when a new run scores >N% below the rolling-30-day average for the same (system, task)

## Phase 5 — continuous evaluation

- [ ] Schedule weekly re-runs of the full suite against pinned model versions to detect provider-side drift
- [ ] CI integration: PRs that touch `tasks/` trigger that task running against a reference system
- [ ] Public dashboard (optional) — markdown report committed to repo, or simple static site
