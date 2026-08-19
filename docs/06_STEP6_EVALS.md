# Step 6 — The Evaluation Harness

This is the step the whole project has been collecting evidence for, and
the strongest sentence it buys you in an interview:

> "A change that makes my agents worse cannot reach my main branch."

Traditional tests cannot say that — they check code, and an AI agent can
get worse with no code being wrong at all: a softened prompt, a swapped
model, a subtle rewording. This step builds the machinery that measures
agent BEHAVIOR against golden cases and physically blocks merges that
regress it.

Time needed: about two hours, plus one real-mode run (~a dollar or less).

---

## 1. New words used in this step

- **Golden case** — inputs with KNOWN correct properties: not "an
  example" but a promise ("given this resume and this posting, kubernetes
  must land in gaps_not_claimed"). They live in `evals/golden/` as JSON,
  so adding one is a one-file, reviewable Pull Request.
- **Deterministic check** — a plain-code boolean about an output: score
  in range, forbidden skill not claimed, every claimed skill present in
  the source resume. No AI involved. Booleans over vibes.
- **AI judge** — a model auditing another model's output against the
  inputs, answering in booleans WITH quoted evidence (the schema forbids
  "seems fine"). Real mode only — a fake judge approving a fake answer
  proves nothing.
- **Baseline** — a committed file recording which cases pass. Moving the
  quality bar means editing a reviewed file, never an accident.
- **Regression gate** — the rule with teeth: any case that passed in the
  baseline and fails now makes the run exit non-zero, which makes
  Continuous Integration block the merge.
- **Run attribution** — every AI call an eval run causes (agents,
  sub-agents, judges) is tagged with the run's id via the gateway, so
  each run reports its own exact cost from `agent_runs`.

## 2. The three design commitments (the interview answers)

**Evals share production code paths.** The runner calls exactly
`score_match` and `generate_tailored_content` — the pure cores shaped for
this in Steps 4 and 5. There is no eval-only code path, so what is
measured is what ships. Eval drift is structurally impossible.

**Two honest layers, mode-labeled.** Deterministic checks run in every
mode. Checks that audit the MODEL's judgment (absolute score thresholds,
output richness, faithfulness tracing, AI judges) run only in real mode.
So a fake-mode run honestly verifies STRUCTURE, PLUMBING, RANKING
BEHAVIOR, AND THE GATE ITSELF — free, key-less, safe for CI on every
Pull Request — while a real-mode run verifies QUALITY. One elegant
exception bridges both: the RELATIVE check. The golden set contains a
deliberately strong match and a deliberately weak match for the same
candidate, and the suite asserts strong outscores weak — meaningful in
fake mode (our word-overlap scorer satisfies it for the right reason)
AND in real mode (a model failing it is deeply broken).

**The gate compares against a committed bar.** `evals/baseline.json`
records, per mode, which cases pass. Known-failing cases stay visible
without blocking; new cases are welcome; but a case that PASSED and now
FAILS exits 1. `--update-baseline` rewrites the file — a diff a reviewer
sees, which is the point.

## 3. What is in this delivery

**New:** `evals/cases.py` (schemas + loader), `evals/golden/*.json`
(3 match cases including the strong/weak pair, 2 tailoring cases
including the kubernetes-gap trap), `evals/checks.py` (both layers),
`evals/run.py` (runner + gate + cost attribution),
`evals/baseline.json` (the committed fake-mode bar, 6/6),
migration `0005` (`eval_runs`, `eval_case_results`, and `run_id` on
`agent_runs`), `tests/test_step6_evals.py` (the harness's own teeth,
tested: the faithfulness check must catch a planted invented skill; the
gate must flag exactly the regressed case), this document.

**Replaced:** `app/llm.py` (the `current_run_id` context tag — set once
by the runner, automatically stamped onto every AI call in the whole
call tree), `app/models.py`, `app/config.py` (judge model setting;
version 0.7.0), `app/main.py` (`GET /evals/runs` — the quality ledger),
`tests/test_database.py` (bookmark `0005`; the run-attribution
integration test), and `.github/workflows/ci.yml` — REPLACED WHOLE with
the four-check workflow: ruff, pytest, drift check, and the eval gate.

## 4. Apply and verify

```bash
git checkout main && git pull && git checkout -b step/6-eval-harness
# copy files per CHANGES.md (ci.yml replaces yours entirely)
alembic upgrade head && alembic current    # checkpoint: 0005 (head)
alembic check                              # checkpoint: no drift
ruff check . && pytest -v                  # checkpoint: 65 passed
```

**4.1 — Your first eval run (fake mode, free):**

```bash
python -m evals.run --suite all --note "step 6 first run"
```

Checkpoint: `cases: 6/6 passed   cost: $0.0000`, the gate reports clean
(the committed baseline ships with the delivery), and the run appears at
`GET /evals/runs`.

**4.2 — Prove the gate has teeth (five minutes; the step's screenshot).**
In `app/matching.py`, find the fake-score line and invert it:
`fake_score = min(95, 95 - int(60 * overlap))`. Run the suite.
Checkpoint: `match/ranking_backend` FAILS with the evidence
(`strong=48 vs weak=95`), the gate prints REGRESSION, and
`echo $?` prints `1`. Restore the line; the run exits `0`. Now push the
sabotage as a Pull Request on a branch and watch GitHub block the merge
— screenshot the red "evaluation gate" check for your portfolio, then
close the Pull Request without merging.

**4.3 — The real-mode run (~a dollar or less).** Set `FAKE_AI=false`
with both keys, then:

```bash
python -m evals.run --suite all --note "first real-mode run"
python -m evals.run --suite all --update-baseline   # after reviewing
```

Checkpoint: the judges' evidence quotes actual phrases; the kubernetes
trap case passes `forbidden_claim_not_made` and
`forbidden_claim_confessed`; the run's cost is a real dollar amount
attributed from its own tagged calls. Review, then commit the real-mode
baseline. The local ritual from now on: before merging any Pull Request
that touches prompts or agent code, run the real-mode suite; the CI gate
covers structure on every Pull Request for free. (Step 8's spending cap
is what will make labeled real-mode runs in CI safe.)

Ship: Pull Request on green → squash-merge → `git tag step-6 && git push --tags`.

## 5. How the suite grows (the loop that runs forever)

Every future quality incident follows one path: reproduce it as a golden
case (a one-file Pull Request), watch it fail, fix the prompt or code,
watch it pass, update the baseline. The incident can never return
silently. Step 8 adds the adversarial family (malicious postings trying
to rig scores); Step 10's real-user incidents feed the same loop. A
growing golden set IS the product's memory of every lesson it learned.

## 6. Check your understanding

1. Why do evals call `score_match` directly instead of going through the
   HTTP endpoint or a copy of the scoring logic?
2. Why is the strong-versus-weak RELATIVE check more trustworthy across
   modes than an absolute threshold like "score at least 65"?
3. The gate ignores known-failing cases and new cases. Why is blocking
   ONLY on previously-passing cases the right rule?
4. Why does the baseline live in a committed file rather than in the
   database next to the run history?

*Answers: (1) The endpoint adds transport and storage concerns that are
tested elsewhere; a copy of the logic would drift from production
silently. Calling the pure core measures exactly the code that ships —
nothing more, nothing less. (2) Absolute thresholds encode assumptions
about one mode's scale (fake overlap arithmetic versus a real model's
calibration) and break when either shifts; the relative claim — same
candidate, obviously-strong beats obviously-weak — is a property of any
sane scorer, so it transfers across modes and model upgrades. (3)
Blocking on known-failing cases would freeze all work until perfection;
blocking on new cases would punish adding coverage. Blocking on
regressions alone encodes exactly the promise made: things may not
silently get WORSE. (4) The baseline is the quality BAR; the database is
the quality HISTORY. Moving the bar must be a reviewed, diffed, blamable
decision in a Pull Request — the database records what happened, the
committed file records what we agreed to demand.*
