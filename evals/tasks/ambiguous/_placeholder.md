# ambiguous/

Tasks where the "correct" answer depends on the system's behaviour under uncertainty.

## Task shape
- Task description is deliberately underspecified, contradictory, or contains stale information
- Grader accepts MULTIPLE valid responses:
  - System asks a clarifying question → score full credit on "clarifying"
  - System makes the most likely interpretation AND flags uncertainty → score full credit on "graceful"
  - System silently picks one interpretation → partial credit (depends on whether it was the most-likely one)
  - System hallucinates a constraint not in the spec → no credit
- Each task records WHICH behaviour each system chose; the comparison is descriptive, not pass/fail

## Surfaces these should exercise
- Clarifying-question rate
- Detection of contradictions (README says X, code does Y)
- Trust calibration when context is stale or wrong

This is the hardest category to grade. Lean on `llm_judge` graders with detailed rubrics here; consider human spot-checks every quarter.

See ROADMAP.md → Phase 1 → ambiguous for the initial set.
