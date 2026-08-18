# Step 1 — The Database, Managed Properly

In Step 0 you built the workspace. Step 1 gives the application its memory:
a real Postgres database, running in Docker, whose structure is changed
only through versioned, reviewable migration scripts — from the very first
table. You will also upgrade Continuous Integration so that every proposed
change is tested against a real database on GitHub's computers.

Still no AI in this step. The order is deliberate: the AI features of
later steps will *store* things — job postings, resumes, match scores, the
cost of every AI call. The place they are stored, and the discipline for
changing that place safely, must exist first.

Time needed: about two to four hours, including installing Docker.

---

## 1. New words used in this step

- **Database** — a program whose whole job is storing data safely and
  answering questions about it. Ours is **Postgres** (also written
  PostgreSQL), the most widely used open-source database in the industry.
- **Schema** — the *structure* of a database: which tables exist, which
  columns they have, and which rules they enforce. (Not the data itself —
  the shape the data must fit.)
- **Table / row / column** — a table is like one spreadsheet sheet: columns
  define what is stored (title, company, ...), each row is one record (one
  job posting).
- **Migration** — a small, numbered script that changes the schema (for
  example "create the jobs table"). Migrations are applied in order, each
  exactly once, and can be reversed. The tool that manages them for us is
  called **Alembic**.
- **Docker** — a program that runs other programs in **containers**:
  isolated boxes with everything they need inside. We run Postgres in a
  container: no installation into your Mac itself, identical for every
  student, deletable without a trace.
- **Image** — the frozen template a container is started from. Ours is
  `pgvector/pgvector:pg16`: Postgres version 16 with the pgvector
  extension included (needed in Step 4 for AI embeddings — chosen now so
  we never have to switch databases mid-project).
- **Volume** — named storage that lives outside the container, so your
  data survives when the container is recreated.
- **SQLAlchemy** — the Python library our code uses to talk to the
  database. We describe tables as Python classes (called **models**), and
  it translates between Python and the database's language, **SQL**.
- **Integration test** — a test that exercises real components working
  together (here: real Postgres), as opposed to the instant, isolated
  tests from Step 0.

---

## 2. Why each big choice was made (read before building)

**Why Docker instead of installing Postgres directly on your Mac?**
Four reasons. Identical: every student, and GitHub's checking computer,
runs the exact same database image — "works on my machine" disappears.
Clean: nothing is installed into your operating system; delete the
container and your Mac is as before. Realistic: the live server will run
from a container too, so development matches production. Necessary anyway:
later steps deploy with Docker, so the tool earns its place twice.

**Why migrations from the very first table, instead of letting the code
create tables automatically?** Automatic creation ("just make whatever the
models say") works until the day you must *change* a table that already
holds real users' data — then it cannot help you, and you have to learn
migrations in an emergency. Learning them on table number one, when the
stakes are zero, is the professional order. There is a second gift:
migrations are ordinary files in Git, so every schema change goes through
a Pull Request, reviewed and tested like any other code.

**Why does the health endpoint now return 503 when the database is down?**
Monitoring tools and hosting platforms read status codes, not sentences.
"503 Service Unavailable" is the standard signal for "alive, but a
dependency is broken." A health endpoint that answers 200 while its
database is down would silence every alarm designed to protect us.

**Why does the database itself enforce the no-duplicates rule?** The
`jobs` table declares the pair (source, external_id) unique. Postgres will
refuse a duplicate posting no matter which future code path tries to
insert it. Rules enforced by the database cannot be forgotten by a
programmer having a bad day — rules enforced only by code can.

---

## 3. What is in this delivery

**New files**

| File | What it is |
|------|------------|
| `docker-compose.yml` | Describes the Postgres container: image, credentials, port, storage, health check. Heavily commented — read it. |
| `app/db.py` | The database connection layer: the engine (connection manager), the session factory, and `database_status()` for the health endpoint. |
| `app/models.py` | The first model: the `Job` class describing the `jobs` table, including the uniqueness rule. This file is the single source of truth for the schema. |
| `alembic.ini` | Alembic's configuration. Note what is *absent*: no database address — it is read from `app/config.py`, so there is exactly one place the address lives. |
| `migrations/env.py` | Tells Alembic where the database is and what the schema should look like. |
| `migrations/script.py.mako` | The template new migration files are generated from. |
| `migrations/versions/0001_create_jobs_table.py` | The first migration. Its opening comment explains how it was made: generated by Alembic, then reviewed and adjusted by hand — the workflow every future change follows. |
| `tests/test_database.py` | Five integration tests against the real database, including one that proves Postgres itself rejects duplicate postings. Skipped with a helpful message when the database is off; always executed in Continuous Integration. |
| `docs/01_STEP1_DATABASE.md` | This document. |

**Changed files**

| File | What changed |
|------|--------------|
| `app/config.py` | Adds `database_url`, whose default matches docker-compose exactly — plus an automatic repair for the "postgres://" address spelling that hosting companies use (the most common cause of a failed first deployment, removed at the source). |
| `app/main.py` | The health endpoint now checks the database and answers 200 (healthy) or 503 (degraded), with the reason in the body. |
| `tests/test_health.py` | Rewritten to test BOTH outcomes instantly, by replacing the real database check with stand-ins — the standard technique for testing failure paths without breaking real things. Its opening comment explains the idea. |
| `tests/test_config.py` | Three new tests for the address repair. |
| `.github/workflows/ci.yml` | The big upgrade: Continuous Integration now starts a real Postgres (same image as yours) and runs five checks — style, migrations apply, no drift, migrations reverse, full test suite. A broken migration is now caught on the Pull Request, never during a deployment. |
| `requirements.txt` | Adds sqlalchemy, asyncpg, alembic (each with a comment). |
| `README.md`, `.env.example` | Updated for Step 1. |

Everything above was executed and verified against a real Postgres 16 with
pgvector before this delivery was packaged: migrations applied, drift
check clean, downgrade-and-reapply cycle green, all 13 tests passing, and
the live server observed answering 200 with the database up and 503 with
the database stopped.

---

## 4. Part A — Install Docker (one time only)

1. In your browser: docker.com → **Download Docker Desktop** → choose
   **Mac — Apple Silicon** (your MacBook Pro is Apple Silicon).
2. Open the downloaded `Docker.dmg`, drag **Docker** into **Applications**.
3. Open Docker Desktop from Applications. Accept the service agreement.
   It may ask for your Mac password once (it needs permission to manage
   networking). You do NOT need to create a Docker account — if it shows a
   sign-in screen, look for "Skip".
4. Wait until the whale icon in your Mac's top menu bar stops animating
   and Docker Desktop says **"Docker Desktop is running"**.
5. Verify in the PyCharm terminal — run these two commands:

```bash
docker --version
docker compose version
```

Both must print version numbers. If the terminal says "command not found",
Docker Desktop is not running yet — open it and wait for the whale.

Note for the future: Docker Desktop must be running (whale in the menu
bar) whenever you work on this project. It starts the containers; without
it, `docker compose` commands fail with "Cannot connect to the Docker
daemon".

---

## 5. Part B — Apply this step to your repository

Following the working rule from Step 0 — run these commands:

```bash
git checkout main
git pull
git checkout -b step/1-database
```

Now copy this delivery's files into your project (new files added, changed
files replaced), using the two tables in section 3 as your checklist. Then
install the new libraries — run:

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

---

## 6. Part C — The verification runbook (run every check, in order)

**Check 1 — the database starts and reports healthy.** Run:

```bash
docker compose up -d
docker compose ps
```

Expected: a container named like `jobhunter-db-1`, STATUS containing
**"(healthy)"** — wait a few seconds and re-run `docker compose ps` if it
says "(health: starting)". The first run also downloads the image
(~200 MB, one time).

**Check 2 — migrations apply.** Run:

```bash
alembic upgrade head
```

Expected output includes: `Running upgrade  -> 0001, create jobs table`.

**Check 3 — the schema is really there.** Run:

```bash
docker compose exec db psql -U jobhunter -d jobhunter -c "\dt"
```

Expected: two tables — `jobs` and `alembic_version` (Alembic's bookkeeping
table recording which migrations have been applied). Look inside the jobs
table too:

```bash
docker compose exec db psql -U jobhunter -d jobhunter -c "\d jobs"
```

Expected: all ten columns, plus the unique constraint
`uq_jobs_source_external_id` listed under Indexes.

**Check 4 — no drift.** Run:

```bash
alembic check
```

Expected: `No new upgrade operations detected.` — meaning the models in
Python and the real database agree exactly.

**Check 5 — migrations are reversible.** Run:

```bash
alembic downgrade base
alembic upgrade head
```

Expected: the downgrade removes the table, the upgrade recreates it, no
errors. Being able to walk backwards is what makes migrations safe.

**Check 6 — the whole test suite is green.** Run:

```bash
ruff check .
pytest -v
```

Expected: `All checks passed!` and **13 passed** — including the five
integration tests in `tests/test_database.py`, which only run because your
database is up.

**Check 7 — the server reports a healthy database.** Run:

```bash
uvicorn app.main:app --reload
```

Open http://localhost:8000/health. Expected:

```json
{"status": "ok", "app": "JobHunter", "version": "0.2.0",
 "environment": "development", "database": "ok"}
```

Leave the server running for the first exercise.

---

## 7. Two exercises (do both — they are the heart of this step)

### Exercise 1 — watch the service degrade honestly

With the server still running, stop the database:

```bash
docker compose stop db
```

Reload http://localhost:8000/health. Expected: the page STILL ANSWERS —
the application did not crash — but now says `"status": "degraded"`,
`"database": "unreachable (...)"`, and if you check with
`curl -i localhost:8000/health` you will see `HTTP/1.1 503`. This is
graceful degradation: a dependency died, and the service's answer got
worse instead of disappearing.

Also run `pytest -v` right now, with the database stopped. Expected:
**8 passed, 5 skipped** — and pytest tells you *why* it skipped and how to
fix it. Then restore everything:

```bash
docker compose start db
```

Reload the health page (ok again) and re-run `pytest -v` (13 passed).

### Exercise 2 — watch drift detection catch an unmigrated change

The trap this exercise teaches: changing the models and forgetting to
write the migration. In PyCharm, open `app/models.py` and add one line to
the Job class (anywhere among the columns):

```python
    salary: Mapped[str | None]
```

Now run:

```bash
alembic check
```

Expected: it FAILS with `New upgrade operations detected` and names the
missing column. This is check number 3 in Continuous Integration — meaning
a Pull Request with this forgotten migration would be blocked
automatically. Now delete the line you added, save, and run
`alembic check` again — clean. (In a real future change, the fix would be
the other direction: keep the line and generate the migration with
`alembic revision --autogenerate -m "add salary to jobs"`, then review the
generated file — the workflow described at the top of
`migrations/versions/0001_create_jobs_table.py`.)

---

## 8. Part D — Ship it through a Pull Request

```bash
git add .
git commit -m "Step 1: Postgres in Docker, jobs table via Alembic, CI against a real database"
git push -u origin step/1-database
```

Open the Pull Request on GitHub. In its description, paste three things
from your terminal: the `docker compose ps` line showing "(healthy)", the
`alembic check` output, and the `13 passed` line — that is the
"what / why / how verified" habit from Step 0.

Then watch the checks. This Pull Request is the first to run against a
real database on GitHub's computers — open the **Actions** tab and read
the five green steps: style, migrations apply, no drift, reversible, tests.
When green: **Squash and merge**, delete the branch, then:

```bash
git checkout main
git pull
git tag step-1
git push origin step-1
```

---

## 9. Check your understanding (answers at the bottom)

1. Your teammate edits the database by hand ("just one quick ALTER in
   psql"). Which of our five Continuous Integration checks would expose
   the problem, and how?
2. Why does `alembic.ini` contain no database address?
3. The health endpoint could simply crash with an error when the database
   is down. Why is answering 503 with a reason better?
4. Why is the no-duplicates rule declared in the database instead of
   checked in Python code before inserting?
5. `pytest` said "5 skipped" on your laptop. Why is that acceptable there
   but never acceptable in Continuous Integration?

---

*Answers: (1) `alembic check` — the real database no longer matches what
models + migrations describe, so drift is detected; the hand edit either
becomes a proper migration or is reverted. (2) So the address lives in
exactly one place, `app/config.py` — the migration tool can never point at
a different database than the application. (3) Monitoring tools need an
answer they can read: 503 tells the truth ("alive, dependency broken")
while still identifying the cause; a crash tells them nothing and a 200
would be a lie. (4) Code paths multiply — Step 3's ingestion, an admin
tool, a bulk import — and each new path could forget the check; the
database is the single gate every insert must pass. (5) On your laptop the
database may legitimately be off, and a skip with a clear reason beats a
misleading failure; Continuous Integration always provides the database,
so there the tests always execute — nothing important is skipped where it
counts.*
