# Step 11 — Capstone: Prove, Present, Endure

The last step builds no feature. It builds the three things that
outlive features: PROOF (claims a stranger can audit, a backup that
demonstrably restores), PRESENTATION (a README where every sentence
links to its evidence, decision records that preserve the *why*), and
ENDURANCE (dependency updates that flow through the gate, a smoke
script with honest numbers, and the retrospective that turns eleven
steps of work into the story you will tell in interviews).

Time needed: about two hours, then thirty minutes to read your own
project the way an interviewer will.

---

## 1. Definitions first, then plain words

**Retrospective.**
*Rigorous definition:* a structured review conducted at the end of a
body of work, examining what was intended, what occurred, what diverged,
and what practices should be kept, changed, or abandoned — with the
divergences treated as data rather than blame.
*In plain words:* sitting down with the finished thing and asking "what
actually happened here, and what did it teach?" — in writing, so the
answers survive. Section 6 of this document is the course's own
retrospective, and its honesty is the point: a retrospective that only
lists victories is marketing.

**Claim–evidence linking.**
*Rigorous definition:* a documentation discipline in which every
capability claim is paired with a resolvable reference to the artifact
that substantiates it (source file, test name, ledger entry), such that
the claim's truth can be checked mechanically.
*In plain words:* never say "secure" — say "no user can read another
user's data, and here is the hostile test that attacks every endpoint
to prove it," with a link. The README's claims table is built this way,
and a capstone test walks every link and fails if one points at
nothing. Prose that can fail like code stays true like code.

**Architecture Decision Record (ADR).**
*Rigorous definition:* a short, immutable document capturing one
architecturally significant decision: its context (the forces and live
alternatives at the time), the decision in active voice, and its honest
consequences — including the costs; superseded records are marked, not
deleted.
*In plain words:* the answer to "why is it built this way?", written
down while the reasons are still fresh. Code shows WHAT; tests show
THAT it works; ADRs preserve WHY — which is exactly what interviews
probe and exactly what evaporates first. Six founding decisions live in
`docs/decisions/`, each with a Consequences section that names what got
HARDER, because consequences without costs are advertisements.

**Backup; restore drill; RPO and RTO.**
*Rigorous definition:* a backup is a recoverable copy of persistent
state captured at a point in time. A restore drill is a rehearsed,
verified restoration of a backup into a working system. RPO (Recovery
Point Objective) is the maximum tolerable data loss measured in time;
RTO (Recovery Time Objective) is the maximum tolerable downtime during
recovery.
*In plain words:* a backup you have never restored is a hope, not a
backup — the only proof a backup works is restoring it, so we rehearse:
`scripts/backup_restore_drill.sh` dumps the database, restores it into
a scratch database, and compares the migration bookmark, table count,
row counts, and the pgvector extension, failing loudly on any mismatch.
It runs in CI on every Pull Request. RPO and RTO are the two honest
questions to ask of any backup plan: "how much can I lose?" (for us:
since Railway's last daily backup — up to a day, acceptable at this
scale and consciously registered) and "how long to come back?" (the
drill measures a bounded, rehearsed answer instead of a panicked
unknown).

**Disaster recovery.**
*Rigorous definition:* the documented capability to restore service
after loss of infrastructure, comprising backups, the rehearsed restore
procedure, and the recreation of configuration and secrets.
*In plain words:* if Railway vanished tonight, what happens tomorrow?
Answer, because of this course's shape: the code is on GitHub, the
database restores from a drilled backup, every secret is listed in the
Step 10 launch checklist, and the deploy is a Dockerfile any host can
build. The plan fits in one paragraph because the system was built to
be recreated — environment parity was the disaster-recovery plan all
along.

**Dependency updating; supply chain.**
*Rigorous definition:* the practice of tracking and applying new
versions of third-party packages; the supply chain is the full set of
external code a system executes, each element a potential source of
vulnerabilities and breakage.
*In plain words:* your application is mostly other people's code, and
other people's code changes. Dependabot (`.github/dependabot.yml`)
opens a Pull Request when a package updates — which means every bump
faces the SAME gate as your own changes: ruff, migrations, 103 tests,
the eval gate, and the restore drill must pass before it merges.
Updates stop being a thing you remember and become a thing that
happens, reviewed.

**Smoke test versus stress test; latency percentiles.**
*Rigorous definition:* a load smoke test applies a small, bounded
concurrent load to verify the service answers correctly with acceptable
latency; a stress test increases load until failure to locate capacity
limits. The p-th percentile latency is the value below which p percent
of requests completed; p50 is the median experience, p95 approximates
the slowest users' experience.
*In plain words:* `scripts/smoke_load.py` asks a modest question — 50
concurrent-ish requests: does anything fail, and how slow is slow? —
and prints three honest numbers. It is deliberately NOT a stress test:
finding the breaking point of a service whose surge answer is "the
budget stop pauses AI" would measure the wrong thing. Averages lie
(one slow request hides in them); percentiles don't: p50 is the typical
user, p95 is the user about to complain. Verified live here: p50 88 ms,
p95 473 ms, zero failures — real numbers from the real `/health`, which
does a database round trip and the budget sum.

**Semantic versioning (and why 1.0.0 stands).**
*Rigorous definition:* a version scheme MAJOR.MINOR.PATCH in which
MAJOR increments on incompatible interface changes, MINOR on
backward-compatible capability additions, and PATCH on
backward-compatible fixes; the version describes the software's
interface and behavior.
*In plain words:* version numbers describe the product, not the
paperwork. Step 11 changes no endpoint, no schema, no behavior — so the
product stays 1.0.0, and a test pins that decision so the reasoning is
enforced, not just stated. (The course, on the other hand, gained its
final step — documents version themselves by their step numbers.)

**Technical debt (registered, not hidden).**
*Rigorous definition:* known engineering shortcuts whose costs are
deferred; managed debt is recorded with its trigger condition — the
observable signal that the deferred cost is coming due.
*In plain words:* the honest list of what this system does NOT do,
each with the signal that would justify doing it. Ours: background
jobs run in-process via FastAPI's task mechanism, not a separate worker
queue (trigger: match jobs lost at deploy time, or CPU contention
visible in latency); polling, not streaming (trigger: token-streaming
features); single region, daily-backup RPO (trigger: users who would
be materially harmed by a day's loss); no per-IP rate limit on the
auth endpoints beyond token single-use (trigger: abuse in the Sentry
log); expand-migrate-contract deploys (trigger: a migration long
enough to block a deploy). Debt named with triggers is a plan; debt
unnamed is a surprise.

## 2. What is in this delivery

**New:** `README.md` — rewritten as the portfolio front page: the
claims-with-evidence table, the five-minute free local run, the honest
ledger (a capstone test walks every relative link and fails on dead
ones); `docs/ARCHITECTURE.md` — the system on one page, including one
fully-traced request; `docs/00_COURSE_INDEX.md` — the twelve steps and
the incident ledger, kept on purpose; `docs/decisions/` — the template
and six founding ADRs (one gateway; fake-mode parity; 404-not-403;
migrate-then-serve; polling; curated sources), each with costs named;
`scripts/backup_restore_drill.sh` — the drill, run live here twice
(the first run exposed a vacuous check in my own comparison logic —
a check that cannot fail is not a check — fixed and rerun);
`scripts/smoke_load.py` — the bounded latency probe;
`.github/dependabot.yml` — weekly pip, npm, and Actions updates;
`tests/test_step11_capstone.py` — the paperwork held to code's
standard, including running the actual drill inside the suite.

**Replaced:** `.github/workflows/ci.yml` — one added step: the drill
runs on every Pull Request; restorability is a gate, not a hope.

**Verified here:** 103 tests, three consecutive green runs — including
the live drill (bookmark `0008`, 15 tables, row counts, and the vector
extension all matching after restore), the README link walk, the ADR
field audit, and the version pin. The smoke script ran against the live
server with the numbers above. All workflow and Dependabot YAML
validates. The honest boundary: Dependabot's first real Pull Request
and the CI drill's first cloud run happen on GitHub — both are
one-glance checkpoints in your runbook.

## 3. Apply and verify

```bash
git checkout main && git pull && git checkout -b step/11-capstone
# copy files per CHANGES.md (README.md replaces yours — read the diff!)
ruff check . && pytest -v          # checkpoint: 103 passed, including
                                   # test_backup_restore_drill_passes...
sh scripts/backup_restore_drill.sh # checkpoint: DRILL PASSED, matches listed
python scripts/smoke_load.py       # (backend running) checkpoint: p50/p95, no failures
```

Then on GitHub, after the Pull Request merges:

1. CI shows the new drill step green. Checkpoint: "DRILL PASSED" in the
   step's log — your backups now prove themselves on every change.
2. Insights → Dependency graph → Dependabot shows the three ecosystems.
   Checkpoint: within a week, the first automated Pull Request appears
   — and must pass the full gate like anyone else.
3. Read your own README as a stranger: click every link in the claims
   table. The capstone test did this mechanically; do it once with
   human eyes.

Ship: Pull Request on green → squash-merge → `git tag step-11 && git push --tags`.

## 4. The retrospective (the course's own)

**What was intended:** a production AI product and a course, built in
tandem, each step verified before delivery.

**What occurred:** twelve steps, 103 tests, an eval harness with 8
golden cases and a gate that has exited non-zero in anger exactly once
(on purpose), a hostile security suite, four safety mechanisms, a
deployed architecture, and seven preserved incidents.

**What diverged, and what it taught:** every incident in the course
index's ledger was a divergence — and the three worth repeating at the
end: (1) the ingestion endpoints shipped deleted for three deliveries
because functions were tested and routes were not — *pin the surface
you promise*; (2) graceful degradation swallowed budget refusals —
*degradation is for surprises mid-run; known conditions refuse up
front*; (3) the loop-poisoned pool bit four tests before the conftest
root fix — *the third occurrence of a bug is the mechanism asking to be
fixed*. None of these were planned; all of them are now tests; that
loop — incident, pin, forever — is the single most transferable thing
this course teaches.

**What to keep:** verification before delivery; honest boundaries
stated every time; incidents preserved, not buried; definitions
rigorous-then-plain; the database enforcing what code would have to
remember.

**What to change next time:** the route-inventory test should exist
from Step 2, not Step 7 — surfaces should be pinned the day they are
promised.

## 5. Where the project goes from here

The four-phase production roadmap already sketched (richer
instrumentation dashboards, a larger judged eval set, labeled real-mode
eval runs in CI under the spending cap, and wider legitimate data
sources) — plus the standing rhythm: circles widen, OPS_LOG fills,
incidents become golden cases, Dependabot knocks weekly, and the drill
proves the backups on every merge. The repository is now something rare:
a project that can answer, with links, every question it invites.

## 6. Check your understanding

1. Why does the restore drill belong in CI rather than in a quarterly
   calendar reminder?
2. An ADR's Consequences section must name what became HARDER. Why is
   that requirement, specifically, what makes ADRs trustworthy?
3. Why report p95 latency instead of the average?
4. The capstone deliberately does not bump the version. State the rule
   that decision teaches, in one sentence.

*Answers: (1) A calendar reminder tests the backup at the rhythm of
human memory; CI tests it at the rhythm of change — and it is change
(a new table, a new extension, a migration) that silently breaks
restores. The drill in CI means the first Pull Request that breaks
restorability is the one that cannot merge. (2) Because a decision
record with only benefits is indistinguishable from marketing, and a
reader can't weigh a trade-off that hides one side; naming the costs is
what lets a future engineer — or the same one, older — re-decide
honestly when the context shifts. (3) The average hides the suffering:
ninety-five fast requests and five ten-second ones can average
"acceptable" while every twentieth user is about to leave. p95 is the
experience of the users you are closest to losing. (4) Version numbers
describe the behavior a consumer of the software can observe — when
behavior is unchanged, the number is too, no matter how much work was
done.*
