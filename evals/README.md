# evals/ — AI coding-system comparison framework

Compare AI coding agents, IDE assistants, and raw LLMs on the same tasks under controlled conditions.

> **Naming.** This is `evals/`, not `tests/`, because the repo already has a 602-test pytest suite at `tests/` (verifies kitsune-mcp itself). Mixing AI evals with unit tests confuses pytest discovery and humans. Both names mean "tests," but the convention in the AI-eval space (Anthropic, OpenAI, METR, UK AISI) is `evals/`.

## What this framework can compare

| Class | Examples | How |
|---|---|---|
| Agentic coding tools | Claude Code, Cursor (composer), Aider, Continue, Cline | `adapters/agentic.md` — task fed as a prompt + repo; system has tools |
| IDE-interactive assistants | Cursor (inline), GitHub Copilot, Claude Cowork | `adapters/ide_interactive.md` — human-in-the-loop, measure assist quality |
| Raw model APIs | Claude Sonnet/Opus/Haiku, GPT-4o, Llama variants, local models | `adapters/api_only.md` — model gets prompt + repo zip, returns unified diff |

The trick: **the same task** runs under different adapter modes. You're consciously choosing what you vary (model? agent harness? both?), instead of comparing apples to oranges.

## Repo layout

```
evals/
├── README.md                      this file
├── ROADMAP.md                     prioritised checklist of tasks to add
├── METHODOLOGY.md                 statistical approach, grading rules, bias controls
├── pricing.yaml                   per-provider token cost table (manually updated)
├── adapters/                      contracts for each system class
├── tasks/                         the benchmark suites (the "what")
│   ├── schemas/                   task.json + result.json schemas
│   ├── codegen/                   net-new code from a spec
│   ├── bugfix/                    reproduce + fix
│   ├── refactor/                  behaviour-preserving change
│   ├── testgen/                   write tests for given code
│   ├── tool_use/                  multi-tool chains
│   ├── multi_step/                plan + execute
│   ├── instruction_following/     respect project conventions
│   ├── ambiguous/                 underspecified — clarifying behaviour
│   └── reliability/               same task N×, measure variance
├── graders/                       how to score (the "how well")
├── harness/                       runner skeleton + I/O contract
├── results/                       run artifacts (gitignored)
└── analysis/                      post-hoc reporting
```

## Quick start (when you're ready to run)

1. Pick a task from `tasks/codegen/001-slugify/` (the worked example).
2. Pick a system to test, follow the matching `adapters/*.md`.
3. Produce a `result.json` matching `tasks/schemas/result.schema.json`.
4. Run the task's `grader.py` against it; results land in `results/`.
5. Aggregate with the analysis notebooks (`analysis/`).

External users (you, others) don't need to use the harness in this repo — only the schemas. Anyone with any tool can produce a result.json and have it graded.

## Design principles

- **Apples-to-apples first.** Adapter modes make varying axes explicit. Don't compare model-X-in-agent-A vs model-Y-in-agent-B and call it a model comparison.
- **Programmatic graders first, LLM judges as backup.** LLM-judge has documented biases (verbosity, self-preference, position). Use it only where unavoidable, and with anti-bias controls.
- **Worst-case matters as much as average.** A 95%-correct system that fails catastrophically the other 5% is worse than a bounded 90%. Report worst-decile alongside means.
- **Repeated runs are mandatory.** Default `n_runs ≥ 5` per (system, task) pair with reported variance.
- **Cost is a first-class metric.** Cost-per-correct-solution is the real number, not raw pass rate.
- **Reproducibility through pinning.** Repo fixtures pinned to a SHA; prompts versioned; full traces stored.

## What this framework is NOT

- **Not a replacement for SWE-bench, MultiPL-E, LiveCodeBench, etc.** Those exist, are mature, and have published leaderboards. This framework is for *your* specific concerns (workflow fit, your codebase, your constraints). For broad model capability, run the public benchmarks.
- **Not a leaderboard service.** No central submission. Anyone can run it; results live in their own `results/` dirs.
- **Not contamination-proof on its own.** Public test inputs leak into training data. The `tasks/reliability/` category covers contamination checks; private/proprietary tasks are the only true defence.

## See also

- `ROADMAP.md` — what to build next, in order
- `METHODOLOGY.md` — how to grade fairly
- `harness/README.md` — the runner contract
