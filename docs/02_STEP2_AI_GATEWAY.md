# Step 2 — The Instrumented AI Gateway

This step brings AI into the project — but not as a feature. It builds the
discipline around AI first: one single door through which every AI call
will pass, forever, with every call measured and recorded. The agents of
later steps (resume parser, match scorer, coach) will all be built on top
of this door. So will the spending protection of Step 8 and the quality
harness of Step 6.

The idea to hold onto: **in a production AI product, an unmeasured AI call
is a bug**, even if it works. You cannot control cost, speed, or quality
that you cannot see. This step makes unmeasured calls impossible.

Time needed: about two hours, including the exercises.

---

## 1. New words used in this step

- **Token** — the unit AI models read and write text in: a piece of a word,
  roughly four characters of English. Pricing is per token, so tokens are
  literally money. One thousand tokens is about 750 words.
- **API key** — a secret code that identifies your account to the AI
  service. Anyone holding your key can spend your money, which is why it
  lives only in `.env` (ignored by Git) and never in code.
- **Gateway** — a module every call must pass through; ours is
  `app/llm.py`. One door means one place to measure, and later, one place
  to control spending.
- **Schema** — a declared exact shape for data: which fields, which types.
  We already use one (the `Settings` class). In this step, AI answers get
  schemas too — enforced, not hoped for.
- **Fake mode** — the gateway's free mode: instead of calling the real AI
  service, it returns a realistic canned answer the caller declared.
  No key, no cost, works offline. **It is ON by default.**
- **Instrumentation** — recording what a system does as it runs: timings,
  sizes, successes, failures. The `agent_runs` table is our instrument.

---

## 2. What is in this delivery, file by file

`CHANGES.md` lists which files are new and which replace your Step 1
versions. In plain words:

**New files**

| File | What it is |
|------|------------|
| `app/llm.py` | The gateway itself. Two functions the whole project will use: `generate_text` (plain answer) and `generate_structured` (answer validated against a schema, one retry, then a loud failure). Every round trip — success or failure — is recorded. Read this file's opening comment first; it states the one rule of the project. |
| `migrations/versions/0002_create_agent_runs_table.py` | The migration creating `agent_runs`: one row per AI round trip — who called, which model, milliseconds, tokens in and out, dollars, success or error. Chained onto your `0001`. |
| `tests/test_llm.py` | Nine tests for the gateway's logic — fake mode, validation, the retry policy, failure recording, cost arithmetic — all instant, no database or network needed. Its opening comment explains the stand-in technique it shares with `test_health.py`. |
| `docs/02_STEP2_AI_GATEWAY.md` | This document. |

**Replaced files** (copy over your Step 1 versions)

| File | What changed |
|------|--------------|
| `app/config.py` | Adds the Step 2 settings: `fake_ai` (True by default), `anthropic_api_key` (empty by default — the key never lives in code), `ai_model`, and an output-length ceiling. Version becomes 0.3.0. |
| `app/models.py` | Adds the `AgentRun` model — the flight recorder's table definition. |
| `app/main.py` | Adds two endpoints. `/metrics`: one summary row per agent — calls, success rate, average speed, tokens, total dollars — computed by the database from `agent_runs`. `/demo/ai`: a clearly-labeled **temporary** endpoint so you can watch the gateway work before any real agent exists; it will be removed in Step 4 when the first real agent replaces it. |
| `requirements.txt` | Adds `anthropic`, the official client library for the AI service. |
| `.env.example` | Documents the two lines you will add to `.env` when you want real AI answers. |
| `tests/test_database.py` | Two small changes worth understanding. First: the migration-bookmark test now expects `"0002"` — this assertion names the latest migration and therefore changes in every step that adds one; your Step 1 version would fail the moment `0002` applied, and catching that *before* delivery is exactly why you uploaded your real files. Second: new end-to-end tests — the `agent_runs` table exists, and one call to `/demo/ai` produces exactly one real row in it, which `/metrics` then reports. |

---

## 3. Apply the step (the working ritual)

**3.1 — Branch.** In the terminal:

```bash
git checkout main && git pull
git checkout -b step/2-ai-gateway
```

**3.2 — Copy the files** from this delivery into your project, per
`CHANGES.md`: new files into place, replaced files over your old ones.

**3.3 — Install the new library.** In the terminal:

```bash
pip install -r requirements.txt
```

**3.4 — Apply the migration.** The database must be running
(`docker compose up -d` if it is not). Then:

```bash
alembic upgrade head
alembic current
```

Checkpoint: the second command prints exactly `0002 (head)`.

**3.5 — Drift check** (models and migrations must agree):

```bash
alembic check
```

Checkpoint: `No new upgrade operations detected.`

---

## 4. Verify everything

**4.1 — The checks:**

```bash
ruff check .
pytest -v
```

Checkpoint: `All checks passed!` and `24 passed`. Count matters: 11 from
Steps 0–1, 9 new gateway tests, 2 updated database tests, and 2 new
end-to-end tests. If anything shows `skipped`, the database is not
running.

**4.2 — The live proof.** Start the server (`uvicorn app.main:app
--reload`), then in a second terminal:

```bash
curl -s -X POST localhost:8000/demo/ai \
  -H 'Content-Type: application/json' \
  -d '{"text":"I love building production AI systems."}'
```

Checkpoint — this exact answer, instantly (it is fake mode):

```json
{"summary":"A short note about testing the AI gateway.","tone":"neutral","word_count":9}
```

Now the important part — the call was *recorded*:

```bash
curl -s localhost:8000/metrics
```

Checkpoint: one row for agent `"demo"`, with `"calls"` equal to how many
times you called it, `"success_rate": 1.0`, small token counts, and
`"total_cost_usd": 0.0` — fake mode is free, and the metrics prove it.

**4.3 — Ship it.** Commit, push, open a Pull Request. A description that
follows our template:

> Adds the AI gateway (app/llm.py): every AI call now passes through one
> instrumented door, recorded in the new agent_runs table (migration
> 0002). Adds /metrics and a temporary /demo/ai endpoint. Fake mode is on
> by default, so no key is needed and CI spends nothing. Verified locally:
> alembic at 0002, drift check clean, ruff clean, 24 tests passed, /demo/ai
> and /metrics answering as documented.

Checkpoint: the checks turn green, and merging is blocked until they do.
Your Step 1 Continuous Integration already starts a database and applies
migrations before testing, and fake mode needs no key, so no workflow
changes are required. Precondition to verify: in the Actions log, the
database tests must say **passed**, not skipped. If they say skipped, the
workflow's database service is missing — tell me and I will supply the
corrected workflow file.

After merging: `git checkout main && git pull`, and tag the moment:
`git tag step-2 && git push --tags`.

---

## 5. Exercise — watch a failure get recorded (free, two minutes)

The gateway's promise is that failures are as visible as successes. Prove
it. **Edit a file** — create or open `.env` in the project root and add
exactly one line:

```
FAKE_AI=false
```

No key is configured, so real mode must fail. Restart the server, call
`/demo/ai` again, and you get an error response — good. Now the point.
**Run this command:**

```bash
docker compose exec db psql -U jobhunter -c \
  "SELECT agent, model, success, error FROM agent_runs ORDER BY id DESC LIMIT 3"
```

Checkpoint: the newest rows show `success = f` (false) and an error
message naming an authentication problem — the failure was measured, with
its reason, exactly like a success. (You will also see two failed rows per
attempt: the retry policy tried twice before giving up — the policy,
visible in the data.)

**Now remove that line from `.env`** and restart the server. Fake mode is
the default again; nothing was spent; and `/metrics` now honestly shows a
success rate below 1.0 for the demo agent — history is not repainted.

Optional, costs a fraction of a cent: put both `FAKE_AI=false` and a real
`ANTHROPIC_API_KEY=...` in `.env`, restart, call `/demo/ai` with your own
sentence, and watch a real AI answer arrive — with its real token counts
and real dollar cost recorded in `/metrics`. Then set fake mode back on.

---

## 6. Why it is built this way (the interview answers)

**Why one gateway instead of letting each agent call the AI service
itself?** Because a rule that lives in one module cannot be forgotten by
the next agent someone writes. Measurement, the retry policy, and — in
Step 8 — the emergency spending stop each exist in exactly one place and
govern every agent automatically, including agents that do not exist yet.
This is the same principle as Step 1's database constraint: put the rule
where it cannot be bypassed.

**Why is fake mode the default, instead of the real AI?** A fresh checkout
must run for a student with no key and cost nothing — the same "works
instantly, spends nothing" principle as the database defaults. And it
keeps Continuous Integration free forever: the checks run on every Pull
Request without an API key existing anywhere in GitHub. You switch fake
mode off deliberately; money is only ever spent on purpose.

**Why does the caller declare the fake answer, instead of the gateway
inventing one?** The caller knows what a realistic answer looks like; the
gateway does not. And the habit pays forward: declaring "here is a correct
answer for this input" is exactly the thinking behind the golden test
cases of the evaluation harness in Step 6.

**Why record failures, and why re-raise them afterward?** A failure you
cannot see is a failure you cannot fix; a failure silently swallowed
becomes wrong data downstream. So: record, then raise — visible in the
metrics, loud in the code.

**Why estimate an unknown model's price at the most expensive known
rate?** Because the honest direction to be wrong in, about money, is
overestimating. A cost dashboard that underestimates teaches you to trust
numbers that will one day surprise you.

---

## 7. Check your understanding

1. Why must every AI call go through `app/llm.py` — what breaks, quietly,
   if one agent calls the service directly?
2. What happens, in order, when a model answers `generate_structured`
   with broken JSON twice?
3. Why does the fake-mode default make Continuous Integration permanently
   free, and what would change the day someone sets `FAKE_AI=false` there?
4. The recording function catches its own database errors instead of
   letting them crash the request. Why is that the right trade — and what
   already tells the operator the database is down?

---

*Answers: (1) Nothing breaks visibly — which is the problem: the call
works but is invisible: absent from /metrics, exempt from the future
spending stop, unmeasurable for cost and quality. An unmeasured call is a
bug even when it works. (2) First answer fails validation → one retry is
sent, including the error message so the model can correct itself → if the
second answer also fails, a RuntimeError is raised naming the agent —
valid data or a loud failure, never silent garbage. (3) The checks never
contact the AI service, so no key is stored in GitHub and no run can
spend money; turning fake mode off there would require adding a secret
key and would make every Pull Request cost real dollars — a deliberate
decision for Step 6, made with the Step 8 spending cap in place. (4)
Measurement must never break the product it measures; losing one metrics
row is a smaller harm than failing a user's request — and the health
endpoint already reports database trouble to the operator, so the failure
is not hidden, it is reported through the correct channel.*
