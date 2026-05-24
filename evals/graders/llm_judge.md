# LLM-judge grading

Use only when programmatic grading can't capture the dimension. Bias is real and large; the controls below are not optional.

## Required controls

### Cross-family judging
Use a different vendor's model from the system under test. Better: ensemble across vendors and take the median.

| Subject | Acceptable judges |
|---|---|
| Anything Anthropic | GPT-4o, Gemini 1.5 Pro, Llama 3.3 70B |
| Anything OpenAI | Claude Sonnet, Gemini 1.5 Pro |
| Anything Google | Claude Sonnet, GPT-4o |

Never use the same family as the subject.

### Blinding
Strip system identifiers from the submission before judging. Filename should be `submission.py`, not `claude-code-sonnet.py`. Code comments may contain identifying language patterns — leave them, since they're part of the artifact, but the judge prompt must not say "this was produced by X."

### Order randomisation
For pairwise comparisons, randomise which submission is shown as "A" vs "B". Re-judge with order flipped; require agreement to count the result.

### Explicit rubric
Pre-commit to a numbered checklist in `rubric.md`. Example:

```
1. Function signature matches `def slugify(text: str, max_length: int = 50) -> str`. [Y/N, +1 if Y]
2. Implementation contains no comments. [Y/N, +1 if Y]
3. Implementation contains no docstrings. [Y/N, +1 if Y]
4. Variable names are snake_case. [Y/N, +1 if Y]
5. Implementation is ≤30 lines. [Y/N, +1 if Y]
Score: sum of Y answers, 0–5.
```

Free-form "rate this 1–10" produces vibes. Numbered binary or low-cardinality items produce data.

### Self-consistency
Run each judgement N=3 times with different seeds OR different judges. If σ > 1 point on a 5-point scale, escalate to human review.

## Known biases (the price of using LLM judges)

| Bias | Effect | Mitigation |
|---|---|---|
| Verbosity | Judges prefer longer answers | Penalise length in rubric ("≤N lines: +1") |
| Self-preference | Models prefer their own family's output | Cross-family judging |
| Position | First or last shown answer preferred | Order randomisation + counter-balance |
| Style match | Judge prefers code matching its training style | Use multiple judges, take median |
| Sycophancy | Judge agrees with framing in the prompt | Neutral rubric language, no "is this good?" |

## Prompt template

A starting point — adapt per task:

```
You are evaluating a code submission against a rubric. You do not know who or what produced it.

Submission:
<paste code here, no identifying info>

Rubric:
<numbered binary checklist from rubric.md>

For each rubric item, answer Y or N with one sentence of justification.
Then provide a total score (sum of Y answers).
Do not provide opinions or improvements. Score the items as listed.
```

## When NOT to use

- Anything programmatically gradeable. The added noise isn't worth it.
- Tasks where you can't write a rubric. If you can't define "good," the judge can't either.
- Quick first-look results. LLM judging is slow ($/token, latency) — not suited for tight iteration loops.
