# codegen/

Net-new implementation from a specification. The fixture provides a stub or empty file; the system fills it in.

## Worked example

`001-slugify/` is fully specified — copy it as a template.

## What good tasks here look like

- Specification is **complete and unambiguous** (ambiguity goes in `tasks/ambiguous/`)
- Output is **a single function or small module** (multi-file changes go in `tasks/multi_step/`)
- Behaviour is **deterministically gradeable** via a sealed test file
- Specification is **adversarial about side effects**: forbid touching other files, forbid global state
- A competent human implementation fits in ≤60 lines

## Anti-patterns

- "Build me a Flask app" — too open-ended; impossible to grade fairly
- "Implement quicksort" — tested to death; almost certainly contaminated training data
- Copying a problem verbatim from LeetCode/HackerRank — likely contaminated

## Coverage to aim for

- A range of difficulty (easy / medium / hard)
- A range of domains (string, numeric, parsing, async, data structures)
- At least one task per language you care about (TypeScript next)
