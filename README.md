# JobHunter

A production AI job-matching product, and the 12-step course that builds
it from an empty folder: multi-agent system, evaluation harness with a
CI regression gate, multi-tenant security, cost safety, a Next.js
frontend, and a deployed, monitored service.

**Live:** the deployed site and API are linked from the repository
description. **Course:** start at [docs/00_COURSE_INDEX.md](docs/00_COURSE_INDEX.md).

---

## What it does

Sign in by email link. Upload a resume (with consent). An agent parses
it into a structured profile; matching runs as a background job —
pgvector narrows thousands of postings to a shortlist, an AI scorer
explains the top matches with strengths AND gaps; a tailoring agent
rewrites the resume toward any match under a schema that FORCES honesty
(`gaps_not_claimed`, `change_log`); a coaching agent answers questions
by using tools — including invoking the tailoring agent — inside a
bounded, supervised loop. Every AI call is measured; every day is
budget-capped; every user sees only their own data.

## Claims, with evidence

Every claim below links to the code and the test that prove it — the
repository is written so that this table can be audited.

| Claim | Code | Proof |
|---|---|---|
| Every AI call measured (agent, latency, tokens, cost) | `app/llm.py` | `tests/test_step2_gateway.py`; `GET /metrics` |
| Honesty enforced by schema, not vibes | `app/agents/tailor.py` | schema test + `evals/` faithfulness checks |
| Agents evaluated; regressions BLOCK merges | `evals/run.py` | CI "evaluation gate" step; sabotage run preserved in the eval ledger |
| Adversarial inputs (prompt injection) tested | `evals/golden/*.json` | the two adversarial cases + injection-hardened prompts |
| No user can read another user's data | `app/auth.py::get_owned_candidate` | the hostile suite in `tests/test_step7_auth.py` |
| The API surface cannot change silently | route inventory | `test_the_api_surface_is_exactly_what_we_promised` |
| One user cannot drain the service | `app/safety.py::enforce_quota` (atomic) | quota tests incl. per-user isolation |
| The service cannot outspend its cap | `app/safety.py::ensure_budget_available` | budget-stop test: AI paused, browsing alive |
| "Delete my account" deletes everything | `DELETE /me` + cascades | the counted-deletion test |
| Deploys cannot desync code and schema | `start.sh` (migrate-then-serve) | `test_start_script_migrates_before_serving` |
| Backups actually restore | `scripts/backup_restore_drill.sh` | the drill runs in CI; DRILL PASSED or the build fails |

## Architecture in one paragraph

FastAPI + Postgres/pgvector behind a single instrumented AI gateway;
agents as pure-core functions shared verbatim by production and the
evaluation harness; a deterministic orchestrator above the tool-using
coach; Next.js 15 (strict TypeScript, no CSS framework, ~107 kB) behind
a same-origin proxy so cookies and CORS stay simple; background jobs
with polled, real-number progress; Railway (Docker, migrate-then-serve)
+ Vercel, with Sentry, uptime monitoring, nightly ingestion, Dependabot,
and an operations log. The six decisions that shaped it are recorded in
[docs/decisions/](docs/decisions/). Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Run it locally in five minutes, free

Requires Docker, Python 3.12, Node 20+.

```bash
docker compose up -d                     # pgvector Postgres 16
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head
pytest                                   # 95+ tests, no API key needed
python -m evals.run --suite all          # the eval gate, free in fake mode
uvicorn app.main:app --reload            # backend :8000
cd frontend && npm install && npm run dev  # frontend :3000
```

Fake mode (`FAKE_AI=true`, the default) exercises every real code path
with deterministic canned model answers — free, offline, and what CI
runs. Set `FAKE_AI=false` with API keys for real models
([ADR-0002](docs/decisions/0002-fake-mode-parity.md)).

## The honest ledger

This repository preserves its own incidents as teaching material — the
shipped ingestion-endpoint regression that survived three deliveries
until a route-inventory test caught it, the design collision where
graceful degradation swallowed budget refusals, the eval-gate sabotage
run frozen at 3/4 in the ledger, and the status-string mismatch a typed
frontend made impossible. Where they live: the step documents in
[docs/](docs/), the operations log ([docs/OPS_LOG.md](docs/OPS_LOG.md)),
and the course index's incident table.

## License and data

Job data comes only from sources that publish for programmatic use
(Greenhouse/Lever public boards, Remotive) —
[ADR-0006](docs/decisions/0006-curated-sources-not-scraping.md).
Resumes are processed with explicit consent, never logged, and deletable
in one request (`/privacy`).
