# STANDARDS_2026 — how this framework maps to current public benchmarks

A snapshot of the coding-agent benchmark landscape as of mid-2026, and how this
repo's task categories relate to each. Use this to decide when to run a public
benchmark instead of (or alongside) the local suite.

## The headline shift: saturation → contamination-resistant + multi-file

The big-three of public coding evals are now **SWE-bench (+ Pro)**,
**Terminal-Bench**, and **LiveCodeBench**.

The defining story of 2025–26 is **benchmark saturation**. SWE-bench Verified
(500 human-verified bug-fix tasks) is now largely solved at the top — frontier
models report **80–94%** — but a chunk of that is **contamination**: the public
GitHub issues leaked into training data. The same models score **~46%** on
**SWE-bench Pro**, which draws from *recent* and *proprietary/copyleft* repos and
requires **multi-file changes (avg ~107 lines across ~4.1 files)**. The 81%→46%
gap *is* the contamination signal.

**Takeaway for this repo:** raw pass rates on easy, public-shaped tasks are
nearly meaningless now. Discriminating power comes from (a) multi-file
coordination, (b) contamination resistance (private/novel tasks), and (c)
non-functional axes — instruction adherence, injection resistance, minimal-diff
discipline. The new medium tasks here target exactly those.

## Mapping table

| Public benchmark | What it measures | Local analogue here | Notes |
|---|---|---|---|
| **SWE-bench Verified** | Single/few-file bug fixes on real PRs | `bugfix/` | Saturated + contaminated; treat top scores skeptically |
| **SWE-bench Pro** | Multi-file, recent/private bug fixes | `bugfix/` + `multi_step/` (multi-file) | The current discriminator; ~46% ceiling |
| **Terminal-Bench** | Autonomous terminal/shell task completion | `tool_use/` + `multi_step/` | Best fit for the `agentic` adapter w/ shell_exec |
| **LiveCodeBench** | Competitive problems dated after training cutoff | `codegen/` | Contamination-resistant by construction; refresh monthly |
| **τ-bench / τ²-bench** | Tool use w/ a simulated user, multi-turn | `tool_use/`, `ambiguous/` | Needs a user-simulator harness (not built here) |
| **Aider polyglot** | Editing existing code across languages | `refactor/`, `bugfix/` | Publishes its own leaderboard; good cross-check |
| **MultiPL-E** | Codegen across ~18 languages | `codegen/` (add TS/Go) | Breadth, not depth |
| **SWE-EVO** (Dec 2025) | Agents on *evolving* codebases over time | `multi_step/` | New; long-horizon consistency |

## What the local suite adds that public benchmarks don't

1. **Apples-to-apples adapter modes.** Public leaderboards mix model + harness.
   Here you hold two axes constant and vary one (see `METHODOLOGY.md`).
2. **Your codebase, your conventions.** `instruction_following/` checks adherence
   to *your* CLAUDE.md / forbidden-library rules — not generic correctness.
3. **Injection resistance as a graded axis.** `reliability/001-prompt-injection`
   treats "ignored the malicious embedded instruction" as a pass condition. This
   is increasingly standard in 2026 agentic-safety evals and absent from
   classic functional benchmarks.
4. **Cost-per-correct + worst-decile.** Public boards report mean pass@1 only.

## Practical guidance

- **For broad model capability:** run SWE-bench Pro + LiveCodeBench. Don't
  reinvent them here.
- **For workflow fit / your-codebase concerns:** run this suite. Keep tasks
  private and rotate them — a public task is a contaminated task within a release
  cycle.
- **Difficulty hygiene:** an all-`easy` suite that scores 100% tells you nothing.
  Maintain a ≥50% share of `medium`/`hard` tasks so the mean stays off the ceiling.

## Sources

- SWE-bench Pro leaderboard & "why 46% beats 81%" (morphllm.com, Scale Labs)
- SWE-bench April-2026 benchmark-hygiene analysis (whocodesbest.com)
- Coding benchmarks leaderboard — SWE-bench / Terminal-Bench / LiveCodeBench (awesomeagents.ai, benchlm.ai, codesota.com)
- SWE-EVO: Benchmarking Coding Agents in Evolving Codebases (arXiv 2512.18470)
