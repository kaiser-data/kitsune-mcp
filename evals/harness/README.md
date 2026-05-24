# harness/

The runner skeleton — the thing that ties task + adapter + grader together. **Implementation deferred** (per your instructions); this folder documents the contract and provides a Python stub showing the shape.

## Recommended: `inspect_ai`

[UK AISI's `inspect_ai`](https://github.com/UKGovernmentBEIS/inspect_ai) is the closest match to this framework's needs:

- First-class task + dataset + scorer abstractions
- Built-in solvers for raw-API and agentic patterns
- Sandbox support (Docker, local, k8s)
- Trace storage and review UI
- Already used by major labs for capability evals

You'd map our concepts to inspect_ai as:

| This framework | inspect_ai |
|---|---|
| `task.yaml` | `Task` definition |
| `adapter` | `Solver` (`generate`, `chain`, agent solvers) |
| `grader.py` | `Scorer` |
| `result.json` | `EvalSample` + `EvalLog` |
| `results/` | `~/.local/share/inspect_ai/logs/` |

Pros: don't reinvent the wheel; community + reference implementations.
Cons: ties you to one framework; some agents (Claude Code as a CLI) don't fit cleanly into inspect_ai's solver model.

## Alternative: roll your own around the schemas

If `inspect_ai` doesn't fit (especially for the agentic adapter against CLI tools like Claude Code), build a minimal Python runner:

```
runner.py --task tasks/codegen/001-slugify/task.yaml \
          --adapter agentic \
          --system-config systems/claude-code.yaml \
          --n-runs 5 \
          --out results/2026-05-24/
```

The runner:
1. Validates `task.yaml` against `tasks/schemas/task.schema.json`
2. Stages a clean copy of `fixture/` into a sandbox
3. Invokes the adapter (subprocess for agentic, API call for api_only, instrumented session for ide_interactive)
4. Captures metrics
5. Diffs the workdir → `result.diff`
6. Emits `result.json` validating against `tasks/schemas/result.schema.json`
7. Invokes the grader → `score.json`
8. Aggregates across `n_runs`

`runner_stub.py` in this folder sketches the interfaces. It is intentionally NOT a working implementation — it shows the shape so you (or a future implementer) can fill it in.

## Alternative: `promptfoo`

[promptfoo](https://github.com/promptfoo/promptfoo) is YAML-first and has a web UI. Better fit for non-code-heavy evals (prompts, rag, classification). Limited support for the agentic adapter — possible but you'd be writing custom providers anyway.

## The non-negotiable: the result.json contract

Whichever harness you pick, every system's output must validate against `tasks/schemas/result.schema.json`. That's what makes results comparable.
