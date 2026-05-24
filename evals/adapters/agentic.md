# adapter: agentic

Full tool-using agent. The runner gives the agent a working directory and a prompt; the agent navigates, edits, and ideally runs tests on its own.

## Contract

**The runner:**
1. Extracts the fixture into a sandboxed working dir
2. Starts the agent there (CLI invocation, daemon, MCP connection, etc.)
3. Sends the task instruction (and addendum) as the user message
4. Waits for the agent to declare "done" (heuristics per-system; document yours)
5. Diffs the working dir against the fixture → `result.diff`
6. Collects token/time/tool-call metrics from the agent's logs

**The agent is allowed to:**
- Read any file in the working dir
- Write to `allowed_paths` (graded violation if it writes outside)
- Run shell commands within the sandbox
- Multi-turn reason

**The agent is NOT allowed to:**
- Read `forbidden_paths` (typically the sealed grader test file)
- Reach the network unless `web_access` is in `required_capabilities`
- Escape the sandbox

## Systems this adapter targets

| System | Invocation | Trace source |
|---|---|---|
| **Claude Code** | `claude-code --no-interactive --print < prompt.txt` (or SDK) | stdout/stderr + `.claude/logs/` if enabled |
| **Cursor (composer)** | Programmatic via Cursor's CLI / extension API | Editor logs |
| **Aider** | `aider --yes --message "$prompt" $files` | stdout + `.aider.chat.history.md` |
| **Continue** | Extension protocol | `~/.continue/dev_data/*.json` |
| **Cline** | VS Code extension API | Extension state |
| **Cognition Devin** | API | Run API endpoints |

## Capabilities supported

All. This is the most capable adapter class; most tasks should be runnable here.

## Sandboxing

**Strongly recommended: Docker.** A misbehaving agent can rm -rf, exfiltrate credentials, or burn through API quota.

Minimal sandbox Dockerfile (template — adapt per system):

```dockerfile
FROM python:3.12-slim
RUN useradd -m -s /bin/bash runner
WORKDIR /work
# install language toolchains, pinned versions
USER runner
# agent's CLI installed here
```

Run with `--network=none` unless `web_access` is required. Mount only the workdir.

## Metrics collection

Agentic systems vary in how they expose token counts:
- **Claude Code** emits structured JSON logs when `--log-level json` or similar; parse those
- **Aider** reports tokens at the end of each turn — sum them
- **Cursor** is harder; you may need to scrape the in-app counter or trust the underlying API's response

If you can't get token counts, record `tokens_in: -1` and document why in `errors[]`. Don't fabricate.

## "Done" detection

This is the trickiest part. Heuristics:
- Agent exits cleanly (most CLI tools)
- Agent emits a specific token in its trace (Aider's "Done.", Claude Code's task-complete marker)
- Time limit hit (`limits.wall_seconds`)
- Tool-call limit hit (`limits.tool_calls`)

Record which condition fired in `result.errors[]` if not natural completion.

## Caveats

- **Auto-retry behaviour varies.** Some agents (Aider, Claude Code) will silently retry on tool failures; this inflates apparent token use. Always report billed tokens.
- **MCP-server-using agents are testable here.** A task can require the agent to use a specific MCP server; the adapter must provision that server in the sandbox. Good fit for kitsune-mcp dogfooding.
- **Interactive prompts.** If the agent ever waits for human input, the run hangs. Either pass flags to disable interactivity (`--yes`, `--non-interactive`) or kill at the wall-time limit.
- **Worktree-based isolation is lighter than Docker** but only safe for agents that respect the workdir. Not recommended for unknown systems.

## Minimum implementation checklist

- [ ] Sandbox image with the agent installed (one Dockerfile per system)
- [ ] Fixture-to-workdir extractor
- [ ] Prompt-injection mechanism (stdin, flag, API call — per system)
- [ ] Done-detection heuristic + wall-time killer
- [ ] Diff capture: `git -C $WORKDIR diff > result.diff`
- [ ] Trace + metric extraction (per system, varies wildly)
- [ ] Validate paths-touched against `allowed_paths` / `forbidden_paths`
- [ ] Emit `result.json`
