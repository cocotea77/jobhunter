# JobHunter — Architecture

One page: the shape of the system, the flow of a request, and where
every promise is enforced. Decision rationale lives in
[decisions/](decisions/); step-by-step construction in the numbered
documents.

## The shape

```
 Browser (phone / laptop)
     |            https, one origin
     v
 Next.js frontend (Vercel) ── /api/* rewrite ──► FastAPI backend (Railway)
   static shell + client pages                      |
   typed client (lib/api.ts)                        |  every AI call
                                                    v
                                     ┌─────────────────────────────┐
                                     │  THE GATEWAY  app/llm.py    │
                                     │  text | structured | tools  │
                                     │  + budget stop (Step 8)     │
                                     │  + agent_runs recording     │
                                     └──────┬──────────────┬───────┘
                                            │              │
                                    Anthropic API      (FAKE_AI=true:
                                    OpenAI embeddings   canned answers,
                                                        same code paths)
     Postgres 16 + pgvector (Railway managed)
     jobs · candidates · matches · match_jobs · tailored_resumes
     chat_sessions/messages · users · login_tokens · auth_sessions
     usage_counters · agent_runs · eval_runs/eval_case_results
```

## Layers, and the rule each enforces

- **Ingestion** (`app/ingestion/`): curated Greenhouse/Lever/Remotive
  fetchers → dedupe by (source, external_id) unique constraint →
  self-healing embedding backfill. Rule: duplicate-safe by the database,
  not by memory; one dead source degrades the report, never the run.
- **The gateway** (`app/llm.py`): the only door to any model. Rule:
  unmeasured AI calls do not exist; the budget stop and eval cost
  attribution are corollaries of the single door (ADR-0001).
- **Agents as pure cores** (`app/matching.py`, `app/agents/tailor.py`):
  same functions called by production endpoints and by the eval
  harness. Rule: what is measured is exactly what ships.
- **The coach + orchestrator** (`app/agents/coach.py`,
  `orchestrator.py`): tools receive identity from the server session,
  never from model output; loops are capped and wall-clocked; tool
  errors return INTO the conversation as data; the deterministic
  supervisor owns validation, sessions, timeout, persistence.
- **Auth & ownership** (`app/auth.py`): magic links (single-use, hashed
  at rest), database-row sessions (logout = real revocation), and ONE
  ownership function answering 404 for wrong-owner and nonexistent
  alike (ADR-0003). Enforced across the whole surface by the hostile
  suite + route inventory.
- **Safety** (`app/safety.py`): atomic quota increments; the daily
  budget stop at the gateway entrance; read-only degradation with
  browsing intact.
- **Evaluation** (`evals/`): golden cases (including adversarial
  injection cases) → deterministic checks every mode + AI judges in
  real mode → regression gate against a committed baseline → CI blocks
  merges. Incidents become golden cases; the suite is the product's
  memory.
- **Frontend** (`frontend/`): same-origin proxy; typed client with one
  request() owning errors; polled real-number progress (ADR-0005);
  honesty fields rendered as interface.
- **Operations**: migrate-then-serve deploys (ADR-0004), production
  tripwires (dev admin token → 503; missing email provider → 503),
  Sentry, uptime on /health, nightly ingestion, Dependabot, the
  backup-restore drill in CI, OPS_LOG.

## One request, end to end (matching)

POST /candidates/42/match → cookie → session row → user → ownership
(404 wall) → quota (atomic increment, 429 wall) → budget (503 wall) →
match_jobs row created, 200 `{match_job_id, status: queued}` in
milliseconds → background worker: pgvector top-25 → gateway fan-out
scoring top-8, progress written per completion → row reaches `done` |
`failed` (restart sweep guarantees termination) → the page's poll draws
real numbers → results readable even during a later budget pause.

Every step of that sentence has a test with its name on it.
