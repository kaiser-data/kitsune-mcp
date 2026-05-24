# tasks/ — benchmark suites

Each subdirectory is one **category** (codegen, bugfix, …). Each task within a category is a folder named `NNN-short-slug/` containing:

```
NNN-short-slug/
├── task.yaml            # the task definition (see schemas/task.schema.json)
├── grader.py            # programmatic grader (when applicable)
├── rubric.md            # LLM/human rubric (when applicable)
└── fixture/             # starting repo state — files and dirs as they should appear at t=0
    └── ...
```

## Conventions

- Task IDs are zero-padded 3-digit prefixes (`001-`, `002-`, …) per category. Numbers don't imply difficulty order; treat them as creation order.
- One task = one concern. Resist bundling multiple capabilities in one task — you can't separate the signals.
- The `fixture/` directory is the *initial* state. The system's output is the diff between fixture and final workdir.
- Sealed graders live OUTSIDE `fixture/` so they're never visible to the system.

## Worked example

`codegen/001-slugify/` is fully specified. Use it as a copy-paste template.

## Difficulty levels (rule of thumb)

- **easy**: a competent human can do it in <10 min with no external lookups
- **medium**: 10–60 min, may require reading docs
- **hard**: >1 hour, may require investigating an unfamiliar codebase

Tag each task in `task.yaml`'s `difficulty` field. Sort comparisons by difficulty when reporting.

## Languages

Default to Python. Add TypeScript second (huge user share, different idioms). Go/Rust only if your work involves them — multi-language tasks 4× the maintenance burden.

## Where the categories are

| Category | What it measures |
|---|---|
| `codegen/` | Net-new implementation from spec — no existing code to reason about |
| `bugfix/` | Locate + repair given a failing test or reproducer |
| `refactor/` | Behaviour-preserving structural change (test suite stays green) |
| `testgen/` | Write tests for given code; quality measured by coverage + planted-bug detection |
| `tool_use/` | Multi-tool agentic chains; measures tool selection and recovery |
| `multi_step/` | Plan-then-execute; cross-file coordination |
| `instruction_following/` | Honour `CLAUDE.md` / `.cursorrules` / explicit prohibitions |
| `ambiguous/` | Underspecified or contradictory inputs; measure clarifying behaviour |
| `reliability/` | Same task N×, long context, prompt-injection resistance |

Empty categories have a `_placeholder.md` explaining what tasks belong there.
