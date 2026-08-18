# Step 3 — Real Job Data, Legally

This step fills the `jobs` table you designed in Step 1 with real, live
postings from real companies — thousands of them. When it is done, your
project stops being an application *about* jobs and starts being an
application *containing* jobs.

The professional theme of this step is **trusting nothing you have not
verified**: sources die, answers arrive malformed, the same posting shows
up twice — and none of that may ever crash the service or corrupt the
data. Every one of those promises is enforced somewhere you can point at,
and tested.

Time needed: about two hours, including watching your first real
ingestion run.

---

## 1. New words used in this step

- **Ingestion** — the process of fetching data from outside sources and
  storing it in your own database, safely and repeatably.
- **Board token** — a company's name inside a hiring system's public web
  address. Greenhouse example: `https://boards-api.greenhouse.io/v1/boards/stripe/jobs`
  — the token is `stripe`. One token = one company's live job board.
- **Idempotent** — safe to run repeatedly: running an ingestion twice
  stores each posting once. Our idempotency is enforced by the database
  rule you built in Step 1 — this step is where that early decision pays.
- **Concurrency** — doing several fetches at the same time instead of one
  after another. We fetch politely: at most five sources at once.
- **Recorded-shape test** — a test that runs against a saved copy of a
  source's real answer, so parsing logic is tested offline, instantly,
  forever. The honest limit: it proves we parse the *recorded* shape; the
  live checkpoints below prove the sources still speak that shape today.

---

## 2. Why these sources — the answer you give in an interview

Greenhouse and Lever are hiring systems used by thousands of real
companies, and both publish every company's public job board as machine-
readable JSON at documented addresses — *intended* for programs to read.
Remotive is a remote-jobs aggregator with a public interface. A curated
list of board tokens is therefore a curated list of companies, and tens
of thousands of live postings, refreshed daily, fully legally.

Why not collect from Indeed or LinkedIn? Three reasons, in ascending
order of importance. Legally: their terms of service forbid automated
collection. Technically: they detect and block it within days. And
professionally: a hiring manager who sees scraping in a portfolio reads
poor judgment, not initiative. Real companies build on licensed feeds and
machine-intended interfaces — saying that sentence, and having built
accordingly, is the signal.

---

## 3. What is in this delivery, file by file

**New files**

| File | What it is |
|------|------------|
| `app/ingestion/sources.py` | One fetcher per source (Greenhouse, Lever, Remotive), each translating its source's answer into one neutral shape, `RawPosting`, whose fields deliberately mirror the Step 1 table. Adding a fourth source someday = one function here, nothing else. |
| `app/ingestion/pipeline.py` | The pipeline: fetch everything concurrently, capture each source's failure separately, remove within-batch repeats, store with "on conflict, do nothing". Its opening comment states the three promises; each is tested. |
| `app/ingestion/boards.py` | The starter curated list: 20 Greenhouse boards and 5 Lever companies, all well-known technology employers. Growing it is Exercise 2 — and a good first Pull Request for a student. |
| `scripts/check_boards.py` | The list verifier: tests every entry against the live interface and reports ALIVE (with posting counts) or DEAD (with reasons). A curated list you have not checked is a guess; this script is how the list stays a fact. |
| `tests/test_ingestion.py` | Eight offline tests: parsing of each source's recorded real shape, HTML stripping, within-batch dedupe, and the one-dead-source-never-kills-the-run promise. |
| `docs/03_STEP3_REAL_JOB_DATA.md` | This document. |

**Replaced files**

| File | What changed |
|------|--------------|
| `app/main.py` | Two new endpoints. `POST /ingest`: fetch exactly the sources you name. `POST /ingest/curated`: fetch the whole curated list — the button the nightly refresh will press in Step 10, built now so it is tested by hand long before it is scheduled. |
| `app/config.py` | Adds the ingestion settings: a 20-second per-source timeout (a slow board must never hang the run) and the politeness limit of five concurrent fetches. Version 0.4.0. |
| `requirements.txt` | Adds `httpx` (talks to the boards) and `beautifulsoup4` (turns HTML descriptions into clean text — markup is noise to the AI agents that will read them, noise we would be paying for by the token). |
| `tests/test_database.py` | Adds the idempotency proof against the real database: storing the same batch twice adds rows the first time and exactly zero the second. |

No new migration: the `jobs` table has been waiting for this data since
Step 1 — the drift check still passes untouched, which is itself worth a
moment of appreciation: the table designed before any fetching code
existed fits the real data without a single change.

---

## 4. Apply and verify

**4.1 — Branch, copy, install.** In the terminal:

```bash
git checkout main && git pull
git checkout -b step/3-real-job-data
# copy the files per CHANGES.md, then:
pip install -r requirements.txt
```

**4.2 — The offline checks first:**

```bash
ruff check .
pytest -v
```

Checkpoint: `All checks passed!` and `33 passed` (24 from Steps 0–2, 8
new ingestion tests, 1 new idempotency test). The database must be
running or the database tests will say `skipped`.

**4.3 — Your first real ingestion.** Start the server
(`uvicorn app.main:app --reload`). In a second terminal, fetch three real
sources (this touches the real internet — expect ten to thirty seconds):

```bash
curl -s -X POST localhost:8000/ingest -H 'Content-Type: application/json' \
  -d '{"greenhouse":["anthropic","stripe"],"lever":["plaid"],"remotive_search":"ai engineer"}'
```

Checkpoint: a report shaped like
`{"fetched": <several hundred>, "new": <several hundred>, "skipped_existing": 0, "source_errors": []}`.
The exact numbers vary day to day — these are live companies hiring.

**4.4 — The idempotency proof, live.** Run the exact same command again.

Checkpoint: `"new": 0`, and `skipped_existing` approximately equal to the
previous `fetched`. Nothing was duplicated, and nothing crashed — the
Step 1 constraint at work. Look at the actual rows:

```bash
docker compose exec db psql -U jobhunter -c \
  "SELECT source, count(*) FROM jobs GROUP BY source"
```

**4.5 — The failure path, live.** A dead board must degrade, not kill:

```bash
curl -s -X POST localhost:8000/ingest -H 'Content-Type: application/json' \
  -d '{"greenhouse":["this-board-does-not-exist-xyz"]}'
```

Checkpoint: HTTP 200 (not a server error), `"fetched": 0`, and one entry
in `source_errors` naming the board and the reason. This exact behavior
is what lets a nightly run over hundreds of boards survive the handful
that die each month.

**4.6 — Verify the curated list, then run it.** First the checker
(a development tool, run from the project root):

```bash
python -m scripts.check_boards
```

Checkpoint: a line per board, most saying `ALIVE` with posting counts.
If any say `DEAD`, delete those lines from `app/ingestion/boards.py` —
companies change hiring systems; pruning is maintenance, not failure.
Then press the big button:

```bash
curl -s -X POST localhost:8000/ingest/curated
```

Expect a few minutes and thousands of postings. Checkpoint: the psql
count from 4.4 now reports thousands of rows.

**4.7 — Ship it.** Commit, push, Pull Request. Description template:

> Adds ingestion: Greenhouse/Lever/Remotive fetchers translating to one
> neutral shape, a concurrent pipeline where one dead source lands in
> source_errors instead of killing the run, within-batch dedupe, and
> duplicate-safe storage via the Step 1 constraint. Adds /ingest,
> /ingest/curated, a verified starter board list, and the check_boards
> script. Verified locally: 33 tests passed, drift check clean, live
> ingestion of 3 sources then re-run showed new: 0 (idempotency), dead
> board returned 200 with source_errors, curated run stored thousands.

Checkpoint: checks green, merging blocked until they are, squash-merge,
`git tag step-3 && git push --tags`.

---

## 5. Exercises

**Exercise 1 — break a promise, watch a test catch it (five minutes).**
In `app/ingestion/pipeline.py`, find the `gather(...)` call and change
`return_exceptions=True` to `False` — this is the difference between "a
failing source is captured" and "a failing source cancels everything".
Run `pytest tests/test_ingestion.py -v`. Checkpoint: the test named
`test_one_dead_source_is_captured_and_the_run_continues` fails, telling
you which promise you just broke. Change it back. (This is the same
lesson as Step 0's unused-import exercise, one level deeper: the tests
are not decoration — they are the promises, in executable form.)

**Exercise 2 — grow the curated list (a good student Pull Request).**
Find a technology company you admire; check whether it hires through
Greenhouse or Lever (its careers page's web address usually says —
`boards.greenhouse.io/<token>` or `jobs.lever.co/<company>`). Add the
token to `app/ingestion/boards.py`, run `python -m scripts.check_boards`
to prove it is alive, and submit it as a one-line Pull Request whose
description includes the checker's output. Curated, and verified.

---

## 6. Check your understanding

1. Ingestion's duplicate-safety is enforced in two places — one in Python,
   one in Postgres. Which handles what, and why are both needed?
2. Why does a dead board return HTTP 200 with a `source_errors` entry,
   rather than an error status?
3. The recorded-shape tests all pass, but today's live fetch from one
   source fails. What are the two most likely explanations, and which
   tool in this delivery helps you tell them apart?
4. Why was it worth designing the `jobs` table in Step 1, weeks before
   any data existed to put in it?

---

*Answers: (1) Python's `deduplicate` removes repeats WITHIN one batch,
because Postgres rejects a batch that conflicts with itself rather than
quietly keeping one copy; the database's unique rule handles repeats
ACROSS runs and across any future code path — the unforgettable layer.
Both, because they solve different halves. (2) Because the run as a whole
did its job: partial success with an honest report is the designed
outcome, and the nightly refresh over hundreds of boards depends on it;
an error status would make one dead board indistinguishable from total
failure. (3) Either the source changed its answer's shape (our parsing is
now wrong for live data while still right for the recording), or that
specific board died; `scripts/check_boards.py` distinguishes them — one
dead board among living ones means pruning, everything dead for one
source means the shape changed and the fetcher plus its recording need
updating. (4) Designing the table first forced the data questions —
what identifies a posting, what is optional, what must be unique — to be
answered deliberately, and the proof it was done right is in this step:
real data from three different sources fit the table without a single
schema change.*
