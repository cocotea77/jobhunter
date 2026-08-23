# ADR-0001: Every AI call goes through one instrumented gateway

- **Status:** accepted
- **Date:** Step 2
- **Context:** AI products die of two invisible things: unexplained cost
  and unexplained latency. Calls scattered across the codebase can't be
  measured, capped, or faked uniformly. Alternatives: per-agent clients
  (flexible, unmeasurable) or a vendor SDK wrapper per call site.
- **Decision:** We will route every model call — text, structured, tool
  loops, and embeddings — through `app/llm.py`, which records agent,
  model, latency, tokens, cost, success, and (later) eval-run identity
  to `agent_runs` on every round trip.
- **Consequences:** Easier: the Step 8 budget stop was ONE check at one
  door; eval cost attribution was one ContextVar; `/metrics` is one
  query. Harder: new call patterns must extend the gateway rather than
  bypass it — a discipline the code review must hold, since nothing
  technically prevents a rogue direct SDK call.
