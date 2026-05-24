# tool_use/

Tasks where the agent must use tools well — not just complete the task, but use the *right* tools in the right order.

## Task shape
- Only runnable against the `agentic` adapter
- Grader inspects `result.tool_calls[]` for required behaviours:
  - Did the agent read before writing?
  - Did it test after editing?
  - Did it recover from a tool failure?
- Some tasks may inject deliberate tool failures (e.g., first `grep` returns nothing because the agent searched the wrong dir) to measure recovery

## Surfaces these should exercise
- Tool selection (right tool for the job)
- Tool failure recovery (retry vs. replan)
- Tool-call efficiency (count, parallelism where applicable)
- MCP server use (project-specific: kitsune-mcp dogfooding)

See ROADMAP.md → Phase 1 → tool_use for the initial set.
