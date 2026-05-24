# METHODOLOGY — how to grade fairly

The hard part isn't running tasks. It's interpreting the numbers without fooling yourself.

## Apples-to-apples discipline

Three axes typically vary. **State explicitly which two are held constant in any comparison.**

| You vary | You hold constant | What you measure |
|---|---|---|
| Model | Harness, task | Model capability |
| Harness | Model, task | Agent quality |
| Task difficulty | Model, harness | Capability profile (where does this system break?) |

Bad comparison: "Claude Code (Sonnet) vs raw Haiku API." You're varying both model AND harness. The number tells you nothing about either in isolation.

Good comparison: "Claude Code with Sonnet vs Claude Code with Haiku" (varies model only). Or: "Claude Code vs Aider, both with Sonnet" (varies harness only).

## Sample size

- **Default `n_runs = 5` per (system, task) pair.** Cheaper systems can go higher (10–20). Below 5, variance dominates signal.
- **Report pass@1 and pass@5 separately.** pass@1 = first attempt, pass@5 = best of 5. The gap between them tells you about exploration value.
- **Always report σ** (standard deviation) or 95% CI alongside means. A system at 80%±2 is materially different from 80%±15.
- **For paired comparisons** (same task, two systems), use McNemar's exact test rather than independent-samples tests. Each task is one paired trial.
- **For multiple-system comparisons**, apply Bonferroni or Holm-Bonferroni correction to p-values, or use a single ANOVA + Tukey HSD post-hoc.

## Grading modes

### Programmatic (preferred)

Used for any task with a deterministic correct answer.

- **Test suite passes** — `pytest` exit code 0 against a sealed test file the system never sees.
- **Diff applies cleanly** — `git apply --check` succeeds against the pinned base commit.
- **Lint passes** — `ruff check`, `mypy --strict`, language-equivalent.
- **No side-effect violations** — only files declared in `task.yaml`'s `allowed_paths` were modified.
- **Implementation budget** — line count / complexity caps (only where specified).

Pros: cheap, deterministic, no judge bias. Cons: can't grade style, naming, or architectural fit.

### LLM judge (use sparingly)

Used only where programmatic grading can't capture the dimension (readability, comment quality, architectural fit).

**Required anti-bias controls:**

- **Cross-family judging.** Don't use Claude to judge Claude. Use a different vendor's model (GPT-4o, Gemini) — or, better, an ensemble across vendors.
- **Blinded inputs.** Strip the system identity from the submission before showing it to the judge. The judge sees `solution_A.py`, not `claude-code-sonnet.py`.
- **Order randomisation.** When comparing pairs, randomise which is shown first. Position bias is real.
- **Explicit rubric.** Pre-commit to a numbered rubric (e.g., "1. Names use snake_case [Y/N]. 2. No function exceeds 40 lines [Y/N]. ..."). Free-form "rate this 1–10" produces vibes, not data.
- **Self-consistency check.** Run each judgement 3× with different judges or seeds. Disagreement >1 point → kick to human review.

**Known biases to watch:**
- Verbosity (judges prefer longer answers)
- Self-preference (Claude prefers Claude, GPT prefers GPT)
- Position (first or last item preferred depending on judge)
- Style match (judges prefer answers matching their own training distribution)

### Human

The gold standard, expensive, slow. Reserve for:
- Ambiguous tasks where intent matters
- Final tier-break between top-2 systems
- Calibration: every quarter, human-score 20 random tasks already auto-scored; if correlation < 0.85, recalibrate the auto grader.

## Cost accounting

Cost-per-correct-solution is the metric users actually care about.

```
cost_per_correct = total_dollars / (n_correct_tasks)
```

- **Token counts** — input/output, broken down by model where the harness uses multiple. Some agents (Claude Code) use prompt caching; report cached vs uncached separately.
- **Wall-clock** — p50, p95. Tail latency matters for interactive use.
- **Tool calls** — count, cumulative latency, error rate.
- **Dollar conversion** — use `pricing.yaml` (manually updated, dated). Don't bake prices into individual scripts.

Caveat: agentic tools often retry silently. Always measure billed tokens, not "intended" tokens.

## Reproducibility

Every `result.json` must record:
- Exact model version string (e.g., `claude-sonnet-4-6-20251101`, not "Sonnet")
- Harness version (e.g., `claude-code v2.1.4`)
- Task fixture SHA
- Prompt template version
- Timestamp
- Sandbox image SHA (Docker digest)
- Random seed (where supported)

A run that can't be reproduced 90 days later is data you can't audit.

## Contamination

Public benchmarks leak into training data. Detection:

- **Hold out new tasks for ≥30 days before adding.** A model that scored 70% before publication and 90% after probably memorised.
- **Variant tasks.** For each public task, write a "twin" with the same shape and different surface — if scores diverge wildly, contamination is likely.
- **Live benchmarks (LiveCodeBench-style).** Tasks dated after the model's training cutoff. Effort-intensive to maintain.

For your private codebase, contamination risk is lower but **API privacy matters**: if you evaluate on proprietary code, that code may be visible to the vendor. Document and consider local-only runs (Ollama, vLLM) for sensitive material.

## Reporting

Every published comparison should answer:

1. **What did you vary?** (one of the three axes above)
2. **N runs per cell?**
3. **Programmatic or judged?** If judged: by whom, with what rubric, what cross-validation?
4. **Confidence intervals or σ on every number?**
5. **Worst-decile alongside mean?** (the catastrophic-failure tail)
6. **Cost?**
7. **Reproduction commands?**

If any of those is missing, the comparison is anecdote, not evidence.

## Recommended reading

- "Holistic Evaluation of Language Models" (HELM, Stanford CRFM) — taxonomy and methodology
- "Sample Size in Software Engineering Experiments" — practical n_runs guidance
- "Judging LLM-as-a-Judge" (Zheng et al. 2023) — quantifies the biases above
- METR's task-specification format — battle-tested task.yaml shape
- Anthropic's "Building effective agents" — adapter design intuitions
