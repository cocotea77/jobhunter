# The JobHunter Course — Index

Twelve steps (0–11), each shipped as a verified delivery with code,
migration, tests, and a teaching document. From Step 9 onward (and
retrofitted in spirit throughout), every document defines each concept
rigorously first, then in plain words.

| Step | Delivery | The lesson it carries |
|---|---|---|
| 0 | Workspace, Git, CI skeleton | A project you can trust starts with checks a stranger's computer runs |
| 1 | Postgres + pgvector, migrations, drift check | The database enforces rules so code doesn't have to remember them |
| 2 | The instrumented AI gateway + fake mode | Unmeasured AI calls do not exist; free mode = same code, canned answers |
| 3 | Ingestion from curated sources | Legitimate data, duplicate-safe by constraint, honest per-source failures |
| 4 | Resume parsing + two-stage matching | Cheap similarity narrows; expensive judgment explains; pure cores for evals |
| 5 | The agent layer: tailor, coach, orchestrator | Honesty as schema; least privilege by code shape; bounded agency |
| 6 | The evaluation harness + regression gate | "A change that makes my agents worse cannot reach main" |
| 7 | Accounts and ownership | 404-not-403; the hostile suite; the guard that guards the guard |
| 8 | Safety: quotas, budget stop, injection, privacy | Survivable in public: capped, un-drainable, injection-tested, deletable |
| 9 | The product website | Same-origin proxy; background jobs; polled honest progress; typed client |
| 10 | Launch: Railway + Vercel + monitoring | Migrate-then-serve; production tripwires; the operating ritual |
| 11 | Capstone: prove, present, endure | Claims linked to evidence; ADRs; the restore drill; the retrospective |

## The incident ledger (kept on purpose)

| Where | What happened | What now prevents it |
|---|---|---|
| Step 3→7 | Demo cleanup silently deleted the ingestion endpoints; shipped 3 times | The route-inventory test pins the whole API surface |
| Step 4 | Fake scorer ranked Marketing above Python for a Python resume | Word-overlap fake scores + the mode-robust ranking check |
| Step 6 | (Deliberate) sabotaged scorer | The gate exited 1 naming evidence; the 3/4 run is in the ledger forever |
| Step 8 | Graceful degradation swallowed budget refusals into silent 200s | Up-front budget check in run_matching; principle documented at the fix |
| Step 8 | New endpoints refused by the inventory until consciously added | The guard catching its own author — working as designed |
| Step 9 | Untyped smoke script waited for a status that never comes | The TypeScript status union makes it a compile error; Exercise 1 |
| Steps 2–7 | "Attached to a different loop" bit four separate tests | The conftest root fix; "third occurrence = fix the mechanism" |

An incident that is preserved teaches forever; one that is buried
returns. That is the course's closing argument, and the reason this
table is on the front page of the index.
