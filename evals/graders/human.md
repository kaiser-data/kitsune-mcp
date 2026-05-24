# Human grading

Expensive, slow, gold standard. Reserve for:

- Ambiguous tasks where intent matters more than output
- Final tie-breaks between top systems
- Quarterly calibration: human-grade 20 random already-auto-graded tasks; if correlation < 0.85, your auto-grader is drifting

## SOP (suggested)

### Per-task setup
1. Print the task description (or open in a separate pane).
2. Show the submission anonymised — same blinding rules as LLM judging.
3. Show the rubric.
4. Stopwatch starts.

### Per-submission
- Score each rubric item individually.
- Note 1–2 sentences per item explaining the score.
- Note any "above and beyond" or "below expected" observations not in the rubric.
- Total score per rubric.
- Stopwatch ends.

### Per-batch
- Limit batches to ≤2 hours. Judgement fatigue is real.
- Randomise submission order across the batch — don't grade all of system A then all of system B.
- Schedule a calibration pass: re-grade 2 submissions from earlier in the batch; if your scores moved, factor that into reporting.

## Multi-grader workflow

If using >1 human grader for the same submission:
- Each scores independently before discussion (no anchoring).
- Compute inter-rater agreement (Cohen's κ or weighted κ for ordinal scales).
- κ < 0.6 → your rubric is ambiguous; revise before more grading.
- Discuss disagreements; consensus or median is the recorded score.

## What to record

In `results/human/<batch-id>/scores.json`:

```json
{
  "task_id": "...",
  "submission_hash": "...",      // identifies the submission across runs
  "grader_id": "anon-1",         // not personal name; just an ID
  "rubric_version": "1.0.0",
  "scores_per_item": [...],
  "total": 0.85,
  "wall_minutes": 12,
  "notes": "..."
}
```

## When NOT to use

- Anything programmatic can grade. The cost-per-data-point is 100–1000× higher.
- Quick iteration. By the time you've graded 50 submissions, the model under test has shipped two new versions.
- Anything where rubric criteria are concrete enough that "well-instructed LLM judge with cross-validation" would do as well.
