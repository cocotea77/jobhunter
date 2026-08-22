# Step 10 — Launch

The final step. Everything the course built — the gateway, the agents,
the evaluation gate, the ownership walls, the safety stops, the website
— goes to a public URL, gains monitoring, and meets its first strangers.
This document has three parts: the concepts (defined rigorously first,
then in plain words), the runbooks (Railway, Vercel, and the launch
checklist), and the operating ritual for your first weeks live.

Time needed: about three hours for the deploys, then twenty minutes a
day while the widening circles roll out.

---

## 1. Definitions first, then plain words

**Deployment.**
*Rigorous definition:* the process of installing a specific, identified
version of software onto infrastructure where it serves real traffic,
such that the running version is known, reproducible, and replaceable.
*In plain words:* putting one exact version of your code on a computer
that strangers can reach — in a way that lets you say precisely WHICH
version is running and swap it for another on purpose. "It works on my
laptop" becomes "commit `a1b2c3d` is serving traffic."

**Container, image, and Dockerfile.**
*Rigorous definition:* an image is an immutable, layered filesystem
snapshot bundling an application with its complete runtime environment;
a container is a running instance of an image with isolated process and
filesystem namespaces; a Dockerfile is the declarative recipe from which
an image is built deterministically.
*In plain words:* the Dockerfile is a recipe ("start from Python 3.12,
install these packages, copy this code, start this way"); the image is
the sealed meal-kit the recipe produces; a container is that meal being
served. Because the kit contains EVERYTHING, it runs identically on your
Mac and on Railway's computers — "works on my machine" stops being a
sentence anyone needs to say.

**Managed database.**
*Rigorous definition:* a database instance whose provisioning, storage,
backups, and availability are operated by the hosting provider, exposed
to the application solely through a connection URL.
*In plain words:* Railway runs Postgres for you — the same pgvector
Postgres your docker-compose has been running locally — and hands you
one secret address. Your `DATABASE_URL` setting has been waiting for
exactly this since Step 1: change one variable, and the whole
application is talking to the production database.

**Release phase (migrate-then-serve).**
*Rigorous definition:* a deployment ordering in which schema migrations
are applied, and must succeed, strictly before the new application
version begins serving; a migration failure aborts the release, leaving
the previous version serving.
*In plain words:* our `start.sh` runs `alembic upgrade head` and only
then starts the server, with `set -e` so any failure stops everything.
New code that needs a new column can never run against a database that
lacks it: the deploy either fully happens or cleanly does not. A test
pins this ordering as text, so a careless edit reversing the two lines
fails a named test instead of a deploy.

**Environment parity.**
*Rigorous definition:* the property that development, testing, and
production differ only in configuration values, not in code paths,
architecture, or dependency versions.
*In plain words:* production is not a different program — it is the same
program with different knobs. The whole course built toward this:
`FAKE_AI` flips the models, `DATABASE_URL` flips the database,
`ENVIRONMENT` flips the safety tripwires. Launch day is mostly setting
knobs, which is exactly how it should feel.

**Secret.**
*Rigorous definition:* a configuration value whose disclosure grants
access or capability (API keys, tokens, connection URLs), stored outside
version control and injected into the process environment at runtime.
*In plain words:* the values that must never appear in your code or your
Git history: the Anthropic key, the admin token, the database address.
Railway and Vercel each have a "Variables" screen — that screen is where
secrets live, and nowhere else. The `.env` file on your laptop plays the
same role locally and is ignored by Git for the same reason.

**Error tracking (Sentry, DSN).**
*Rigorous definition:* a service that captures unhandled exceptions from
a running application — stack trace, request context, frequency — and
aggregates them for triage; a DSN (Data Source Name) is the write-only
URL identifying where events are sent.
*In plain words:* when the server crashes at 2 a.m., Sentry catches the
crash with its full stack trace and emails you. Without it, your error
reporting system is "a stranger leaves a TikTok comment." Our
`init_monitoring()` turns it on when `SENTRY_DSN` is set and is a no-op
otherwise — development stays quiet.

**Uptime monitoring.**
*Rigorous definition:* an external service that requests a designated
health endpoint at a fixed interval and alerts when the response is
missing, slow, or reports failure.
*In plain words:* a robot that visits `/health` every five minutes from
outside — because a monitoring system running on the same server as the
application dies with it. Our `/health` was built for this robot: it
answers 503 when the database is unreachable and includes the budget
state, so the alert email often names the cause.

**Scheduled workflow (cron).**
*Rigorous definition:* a job triggered by a time schedule rather than an
event; cron syntax (`17 3 * * *`) expresses the schedule as
minute-hour-day-month-weekday fields.
*In plain words:* a nightly alarm clock. The `refresh-jobs.yml` workflow
presses, every night at 03:17 UTC, the same admin-protected ingestion
button that has existed since Step 3 — fresh postings arrive while you
sleep. It is also hand-pressable (`workflow_dispatch`) for the runbook.

**Rollback.**
*Rigorous definition:* restoring service by redeploying the previously
known-good version, as a first response that precedes diagnosis.
*In plain words:* the undo button. Railway keeps prior deploys; one
click reinstates the last working one. The operating rule: restore
service FIRST, understand the failure second — users need the site up
more than you need to feel finished debugging. (Schema changes make
rollback subtler; that is one reason our migrations are written to be
reversible and tested both directions since Step 1.)

**DNS and HTTPS (in one breath).**
*Rigorous definition:* DNS maps a human-readable domain to server
addresses; HTTPS wraps HTTP in TLS encryption, authenticated by
certificates, which both platforms provision automatically.
*In plain words:* Railway and Vercel give you working `https://` URLs
out of the box — encryption included, certificates auto-renewed. A
custom domain is a later nicety, not a launch requirement. HTTPS also
makes the Step 7 cookie's `Secure` flag active — a test asserts the flag
is present outside development.

**Operations log; incident.**
*Rigorous definition:* an append-only record of production events; an
incident is any unplanned event degrading service, correctness, cost, or
security, recorded with impact, timeline, root cause, and prevention.
*In plain words:* a diary of surprises. Every surprise gets a short
entry (`docs/OPS_LOG.md` has the template) ending with the test or
golden case that now pins it — the Step 6 loop, fed by reality. Four
weeks of this file is worth more in an interview than any feature: it is
the difference between "I deployed a project" and "I operated a
service."

## 2. What is in this delivery

**New:** `Dockerfile` (the recipe, with layer-caching explained in its
comments), `start.sh` (migrate-then-serve, pinned by test),
`.dockerignore` (tests and secrets stay out of the image),
`.github/workflows/refresh-jobs.yml` (the nightly refresh),
`docs/OPS_LOG.md` (the incident template), `tests/test_step10_production.py`
(the tripwires proven, monitoring initialization both ways, the deploy
recipe's promises pinned), this document.

**Replaced:** `app/config.py` (`sentry_dsn`; version **1.0.0**),
`app/auth.py` (the production email tripwire: sign-in REFUSES with 503
in production when no email provider is configured, because console
mode would print credential links into production logs),
`app/main.py` (`init_monitoring()`), `requirements.txt` (sentry-sdk).

**Verified here:** 95 tests, three consecutive green runs, including:
production refuses sign-in without an email provider; production refuses
the development admin token; `dev_link` is absent from production
responses; the session cookie carries `Secure` and `HttpOnly` outside
development (asserted on the real Set-Cookie header); monitoring
initializes with and without a DSN; `start.sh` migrates before serving
and stops on first error; the Dockerfile ships migrations; the nightly
workflow is scheduled, admin-authenticated, and hand-pressable. Both
workflow files validate as YAML; `start.sh` passes a shell syntax check.

**The honest boundary, stated plainly:** no Docker daemon, no Railway,
no Vercel, and no browser exist in my environment. The image build, the
two platform deploys, HTTPS behavior, email delivery, and the scheduled
run can only be verified by your runbook below — which is written with
exact expected screens for that reason.

## 3. Runbook A — the backend on Railway

Preconditions: the repository is on GitHub, **public**, with the branch
ruleset enabled (branch protection is not enforced on free private
repositories — this is the moment that matters); Steps 0–9 merged and
tagged; your Anthropic and OpenAI keys at hand.

1. Sign in at railway.app with GitHub. **New Project → Deploy from
   GitHub repo** → choose the JobHunter repository. Railway detects the
   Dockerfile. Expected screen: a build log ending in "Deploy complete"
   — but the app will crash-loop until the database exists; that is
   expected and next.
2. In the project: **+ New → Database → Add PostgreSQL.** Then open the
   Postgres service → **Variables** → copy `DATABASE_URL`. One
   pgvector note: open the database's **Data** tab → Query, and run
   `CREATE EXTENSION IF NOT EXISTS vector;` (our migration also
   attempts this; running it once by hand rules out permission
   surprises). Expected: `CREATE EXTENSION` or "already exists".
3. Open the backend service → **Variables** → add, exactly:
   - `DATABASE_URL` — paste from the Postgres service
   - `ENVIRONMENT` = `production`
   - `FAKE_AI` = `false`
   - `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — your real keys
   - `ADMIN_TOKEN` — a long random string (`openssl rand -hex 24`),
     never the development default: the tripwire will refuse it
   - `RESEND_API_KEY`, `EMAIL_FROM` — from resend.com (free tier;
     verify your sender). Without it, sign-in refuses by design.
   - `PUBLIC_BASE_URL` — the FRONTEND URL (fill after Runbook B, then
     redeploy; sign-in link emails point here)
   - `MAX_DAILY_SPEND_USD` = `5.0` (or your comfort)
   - `SENTRY_DSN` — from sentry.io (free tier) after creating a Python
     project; optional but strongly recommended
4. Redeploy. Read the deploy log top to bottom — you will recognize it:
   `[start] applying database migrations...` then the Alembic lines
   `0001` through `0008`, then `[start] starting the server...`.
   Checkpoint: open `https://<your-backend>.up.railway.app/health` —
   status `ok`, version `1.0.0`, environment `production`, database
   `ok`, the budget block present.
5. Seed jobs: from your laptop,
   `curl -X POST https://<backend>/ingest/curated -H "x-admin-token: <your token>"`.
   Checkpoint: a report with `fetched` and `embedded` counts; `/health`
   now shows `jobs_indexed` in the hundreds. (This call spends real
   embedding money — expect cents, visible in `/metrics`.)

## 4. Runbook B — the frontend on Vercel

1. Sign in at vercel.com with GitHub → **Add New → Project** → import
   the repository. Set **Root Directory** to `frontend` (the one
   setting people miss). Framework auto-detects as Next.js.
2. **Environment Variables** → add `BACKEND_URL` =
   `https://<your-backend>.up.railway.app`. This is the deployment seam
   from Step 9's definitions: the same rewrite rule now runs on
   Vercel's servers, so the browser still sees one origin and the
   cookie architecture carries over unchanged.
3. Deploy. Checkpoint: the build log shows the same eight routes your
   laptop build showed, and the site is live at
   `https://<project>.vercel.app`.
4. Return to Railway: set `PUBLIC_BASE_URL` to the Vercel URL and add
   it to `CORS_ORIGINS`; redeploy the backend.
5. **The full production journey, on your phone this time:** open the
   site → sign in (a REAL email arrives — the tripwire proved console
   mode cannot leak here) → tick consent, upload → watch the real
   progress bar → matches → coach → tailor. This is the Step 9 runbook
   against production, and it is also your launch video footage.

## 5. The launch checklist

Run top to bottom the day before the first circle:

- [ ] Repository public; branch ruleset active (verify: a direct push
      to main is rejected)
- [ ] CI green on main: ruff, migrations, drift, 95 tests, eval gate
- [ ] REAL-MODE eval baseline committed (`python -m evals.run --suite
      all` with `FAKE_AI=false`, review the judges' evidence, then
      `--update-baseline`, commit through a Pull Request) — the
      adversarial cases hold against the real model
- [ ] `/health` in production: `ok`, `1.0.0`, `production`, jobs
      indexed, budget not exhausted
- [ ] Sign-in works end to end with a real email; the link works once
      and is dead on replay
- [ ] `DELETE /me` exercised once against production with a throwaway
      account (the privacy page's promise, kept where it counts)
- [ ] Quota banner and budget stop verified once in production (set
      `MAX_DAILY_SPEND_USD=0.01`, watch the kind 503, restore)
- [ ] Sentry receives a test event (Settings → "send test event")
- [ ] UptimeRobot (free) monitoring `https://<backend>/health` every 5
      minutes, alerting your email
- [ ] Nightly refresh: press **Run workflow** on `refresh-jobs.yml`
      once by hand; confirm 200 and fresh `jobs_indexed`
- [ ] `docs/OPS_LOG.md` exists with its first entry: "YYYY-MM-DD —
      launched"

## 6. Widening circles, and the ritual

Launch is a dial, not a switch:

- **Circle 1 (days 1–3): five friends.** Ask each to sign up, run
  matching, and tell you the moment anything confuses them. Expected
  finding: small copy and UX issues. Fix, log, move on.
- **Circle 2 (week 1): your students and colleagues.** Tens of users.
  Watch `/metrics` for cost per user per day; watch Sentry; expect the
  first quota banners to be seen in the wild.
- **Circle 3 (week 2+): TikTok.** Post the build story. Before posting,
  decide your surge answer: the budget stop IS the answer — worst case,
  the site politely pauses AI at your cap, which is itself content
  ("my app refused to bankrupt me today").

Daily, twenty minutes: read Sentry (new issues?), `/health` (budget
trend?), `/metrics` (cost per agent — is the coach getting expensive?),
and the eval ledger. Weekly: one OPS_LOG review; every user-visible
wrongness becomes a golden case through the Step 6 loop — reproduce,
watch it fail, fix, watch it pass, baseline through a Pull Request.

## 7. The portfolio paragraph (write it now, while it is true)

Your README's opening, in the language the JD asked for: JobHunter is a
production AI product — a multi-agent system (matching, tailoring with
schema-enforced honesty, a tool-using coach under a deterministic
supervisor) with an instrumented gateway recording latency and cost per
call; an evaluation harness with golden datasets, AI judges, and a
regression gate wired into CI; multi-tenant ownership proven by a
hostile test suite; daily quotas and a spending cap proven by tests;
deployed on Railway and Vercel with error tracking, uptime monitoring,
nightly ingestion, and an operations log. Then link three artifacts: the
red-gate screenshot from Step 6, the eval ledger, and OPS_LOG.md.

## 8. Check your understanding

1. Why must migrations run before the server starts, rather than after
   or concurrently — and what does `set -e` contribute?
2. The production tripwires (admin token, email provider) REFUSE service
   rather than warn. Defend that choice.
3. Why does uptime monitoring have to come from outside your own
   server?
4. A user reports "my matching is stuck at 14 of 25" in production.
   Using only what this course built, name the trail you would follow.

*Answers: (1) The new code may depend on schema that only the migration
creates; serving first (or racing) opens a window where requests hit a
missing column — the exact class of failure that is rare, confusing, and
entirely preventable by ordering. `set -e` makes the ordering binding: a
failed migration aborts the script, so the server never starts against
the wrong schema and the previous deploy keeps serving. (2) A warning in
a log nobody reads yet is consent; a refusal converts a dangerous
configuration into an impossible one at the cheapest possible moment —
before the first stranger arrives. The cost of refusing is minutes of
operator time; the cost of warning is a leaked credential link or an
open operator endpoint. (3) Because the failure modes overlap: if the
server, its network, or its host dies, any monitor living there dies
with it and reports nothing. Detection must not share fate with the
thing it detects. (4) The match_jobs row for that run holds status,
scored, total, and error (restart sweep would have marked an
interruption); agent_runs holds every call the run made with latency,
success, and error, attributable by time and agent; /health shows
whether the budget stop engaged mid-run; Sentry holds any unhandled
exception. The answer is written down before the user finishes typing
the complaint — that is what "instrumented" meant all along.*
