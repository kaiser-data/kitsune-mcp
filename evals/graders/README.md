# graders/

Documents the three grading modes and how to choose between them. The actual grader scripts live alongside each task (`tasks/<category>/<id>/grader.py` or `rubric.md`).

| Mode | When | File |
|---|---|---|
| Programmatic | Anywhere a test suite, lint, or AST check can decide pass/fail | `programmatic.md` |
| LLM-judge | Style, naming, architectural fit — things programmatic can't capture | `llm_judge.md` |
| Human | Final tie-breaks, ambiguous tasks, calibration of auto-graders | `human.md` |

**Strong preference: programmatic where possible.** LLM-judges are noisy and biased. Use them only when you can't programmatically encode what "good" means, and even then, with cross-family ensembles and rubrics.

The grader is the most opinionated part of any eval. Document yours so others can replicate or argue with you.
