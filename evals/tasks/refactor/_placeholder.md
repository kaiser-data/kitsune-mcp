# refactor/

Tasks where the system must produce a behaviour-preserving change. The existing test suite must remain green; structural metrics improve.

## Task shape
- `fixture/` includes working code WITH a passing test suite
- Sealed extension to the test suite covering corner cases the original tests miss — must also pass post-refactor
- Grader checks:
  - All original tests pass
  - All sealed tests pass
  - At least one structural metric improves (cyclomatic complexity ↓, duplication ↓, public API surface stable)
- Common pitfall: aggressive refactors that change behaviour. Sealed tests are the defence.

See ROADMAP.md → Phase 1 → refactor for the initial set.
