# adapters/ — driving each system class

An **adapter** is the glue that turns a `task.yaml` into a `result.json` for one class of system. The adapter is responsible for:

1. Loading the fixture into a working directory
2. Presenting the prompt to the system in its native form
3. Capturing edits as a unified diff
4. Collecting tokens / time / tool-call metrics
5. Writing `result.json` matching `tasks/schemas/result.schema.json`

## Three classes

| Class | Adapter contract | Typical systems |
|---|---|---|
| **API-only** | Model gets the task prompt + a zipped repo. Returns a single unified diff. No tools, no multi-turn. | Raw Claude API, OpenAI API, local Ollama models, Llama, Mistral |
| **Agentic** | Full tool harness: read/write files, run shell, multi-turn. Adapter spawns the agent, watches the trace. | Claude Code, Cursor (composer mode), Aider, Continue, Cline |
| **IDE interactive** | Human-in-the-loop. Adapter records the human's accept/reject decisions and final diff. | Cursor (inline edits), Copilot, Claude Cowork |

Files in this folder document **each adapter's contract** — what it accepts, what it produces, known caveats. The actual implementation lives in `harness/` (or in the user's external runner).

## Why this separation matters

The `result.json` schema makes the *output* uniform. The adapter docs make the *input* uniform-enough to compare fairly. Without this, "system X failed this task" might just mean "system X couldn't be told what the task was."

## Adding a new system

1. Identify which class it belongs to.
2. Read the matching `adapters/*.md` contract.
3. Write a thin runner that satisfies the contract for that system.
4. Test against `tasks/codegen/001-slugify/` first — if your runner can complete the worked example, the contract is satisfied.
5. Commit your runner under `harness/<system-name>/` or keep it private; the framework only cares about the result.json.
