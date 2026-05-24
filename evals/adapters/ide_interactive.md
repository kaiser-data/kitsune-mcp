# adapter: ide_interactive

Human-in-the-loop assistants — Cursor inline edits, Copilot suggestions, Claude Cowork. The human accepts/rejects suggestions; the *combined* output is what matters.

## What this measures (and what it doesn't)

This adapter measures **assist quality**, not raw model capability. The metric of interest is:

- **Tokens of acceptable suggestion produced per unit of human effort**
- **Edit distance from final accepted state to first-suggested state** (low = system "got it" first try)
- **Time-to-task-complete** including human review

It does NOT measure agent autonomy. If you want autonomy comparisons, use the `agentic` adapter against the same systems' agent modes (Cursor's composer, Cowork's autonomous mode).

## Contract

**The runner provides:**
- A timed session where the human attempts the task using the assistant
- A recording mechanism (screen + keystroke timeline, or instrumented IDE)

**The human records:**
- Each suggestion received (raw, before acceptance)
- Each acceptance / rejection / partial-accept
- Subjective notes ("suggestion was wrong direction", "missed a corner case")

**The final result.json captures:**
- The final diff (same as other adapters)
- A `transcript[]` of suggestion events
- Wall-time in `metrics.wall_seconds` = human's stopwatch
- `metrics.tokens_in/out` if the IDE/extension exposes them

## Systems this adapter targets

| System | Capture mechanism |
|---|---|
| Cursor (inline tab-complete + cmd-K) | Cursor exposes logs at `~/Library/Application Support/Cursor/User/globalStorage/` |
| GitHub Copilot | Copilot completion API logs available with `gh copilot` flag |
| Claude Cowork | Cowork session export (per their docs) |
| Codeium / Windsurf / Codium | Each has its own log format; document per-system |
| JetBrains AI Assistant | IDE event log |

## Methodology caveats — read carefully

- **Human variance dominates everything.** One human's "obvious accept" is another's "let me think." If you want to compare IDE assistants, **same human, all systems, random order** is the minimum bar. Better: 3+ humans rotating systems with full randomisation.
- **Order effects are huge.** Doing a task three times in different IDEs, the 3rd attempt is faster than the 1st regardless of IDE. Counterbalance the order.
- **Practice effect** — a fresh task per (human, system) cell. Don't re-use a task you've already solved manually.
- **Self-report bias** — humans rate familiar tools higher. Use behaviour (acceptance rates, time) more than opinion.

## Quantitative metrics

- `acceptance_rate`: accepted_suggestions / suggested
- `time_to_first_accept_s`: when did the first suggestion land
- `time_to_completion_s`: end of session
- `edit_distance_final_vs_first_suggestion`: how much did human have to fix what was suggested first

## Capabilities supported

This adapter is task-permissive — humans can compensate for missing capabilities. But the *purpose* of the test is to measure assist quality, so tasks should be ones a human alone could plausibly do in 30 minutes or less.

## When to skip this adapter

- You want raw model comparison → use `api_only`
- You want autonomous-agent comparison → use `agentic`
- You don't have time to recruit & rotate humans → skip; this is the most expensive adapter

## Minimum implementation checklist

- [ ] Define a session protocol document (what humans do, in what order, with what stopwatch)
- [ ] Pick a screen-record + keystroke-log tool (e.g., `asciinema`, OBS, IDE-native)
- [ ] Build a result.json template the human fills in
- [ ] Pilot with 1 human on 1 task before scaling
- [ ] Rotation/randomisation matrix for multi-system multi-human runs
