# ADR-0004: Deploys migrate first, then serve, or fail whole

- **Status:** accepted
- **Date:** Step 10
- **Context:** New code meeting an old schema is a classic deploy
  failure: rare, confusing, entirely preventable. Alternatives: migrate
  concurrently (racy), migrate after (backwards), migrate manually
  (forgotten).
- **Decision:** We will run `alembic upgrade head` as the first line of
  the container's start script under `set -e`: a failed migration
  aborts the deploy and the previous version keeps serving. The
  ordering is pinned by a named test on the script's text.
- **Consequences:** Easier: code and schema cannot disagree in
  production. Harder: long migrations block deploys (acceptable at this
  scale; large systems graduate to expand-migrate-contract patterns —
  registered as future debt, not a present problem).
