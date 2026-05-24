# results/

Run artifacts land here. **Gitignored except this README and `.gitignore`** — results are local and can be large.

## Layout

```
results/
├── 2026-05-24_claude-code-sonnet/      # one batch
│   ├── codegen_001-slugify/
│   │   ├── run_1/
│   │   │   ├── result.json
│   │   │   ├── score.json
│   │   │   ├── diff.patch
│   │   │   └── transcript.jsonl
│   │   ├── run_2/...
│   │   └── summary.json                # n_runs aggregate
│   ├── bugfix_001-off-by-one/
│   │   └── ...
│   └── batch_summary.json              # all tasks for this system, this batch
└── 2026-05-24_aider-sonnet/...
```

## Naming convention

`YYYY-MM-DD_<system-shortname>` for batch dirs. The date is the batch start date; long-running batches keep the start date.

## What lives here vs. analysis/

- `results/` — **raw** per-run JSON. The truth, but not human-friendly.
- `analysis/` — **derived** reports, tables, plots. Aggregates `results/` across batches.

## Retention

Keep at least the most recent batch per (system, model). Older batches can be archived (tarred + S3'd, etc.) since `summary.json` retains the headline numbers.

For reproducibility, never delete raw `transcript.jsonl` without first archiving the summary.
