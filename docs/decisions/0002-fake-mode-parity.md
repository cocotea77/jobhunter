# ADR-0002: Fake mode is a first-class, behavior-identical mode

- **Status:** accepted
- **Date:** Step 2, extended every step after
- **Context:** Students and CI cannot pay per test run; demos must work
  offline; but a "mock mode" that short-circuits real code paths tests
  nothing. Alternatives: recorded cassettes (brittle), a mock server
  (drifts), or paying (excludes the classroom).
- **Decision:** We will make `FAKE_AI=true` a mode in which every real
  code path executes — the loop, the persistence, the caps, the budget
  stop, the eval plumbing — and only the model's answers are canned
  (caller-declared, deterministic, derived from inputs where it matters,
  e.g. word-overlap scores).
- **Consequences:** Easier: free CI including the eval gate; classroom
  use; the mode-robust relative ranking check. Harder: every canned
  answer is a design decision (the Marketing-over-Python incident), and
  quality claims require clearly-labeled real-mode runs — the harness
  labels every run's mode for exactly this reason.
