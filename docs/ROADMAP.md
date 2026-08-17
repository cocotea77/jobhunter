# JobPilot — The Full Build Plan

This project is built in eleven steps. Each step is one delivery: complete
code, a plain-language document in `docs/`, and a verification checklist.
Each step's changes reach the main branch only through a Pull Request with
green automatic checks — the working rule taught in Step 0.

The goal, stated precisely: a **public website** where anyone can upload a
resume and receive honestly-explained matches against tens of thousands of
real job postings — deployed, monitored, protected against abuse and
runaway AI costs, and operated with real users.

| Step | Name | What exists at the end of it |
|------|------|------------------------------|
| 0 | The professional workspace | A running web server with a health endpoint; a test suite; a code style checker; a GitHub repository whose main branch automatically refuses broken changes. |
| 1 | The database, managed properly | Postgres running in Docker; the first tables; every schema change made through versioned migration scripts from the very first table — never by hand. |
| 2 | The instrumented AI gateway | One single module through which every AI call must pass, recording cost, speed, and success of every call; a free "fake mode" so development and classrooms cost nothing. |
| 3 | Real job data, legally | Tens of thousands of live postings fetched from public company-board interfaces and a licensed aggregator; duplicate-safe; refreshed on a schedule; failures recorded, not fatal. |
| 4 | Resume understanding and matching | Upload a resume, get a faithful structured profile (no invented skills) and ranked matches: fast vector search narrows thousands to dozens, then AI analysis explains the top few. |
| 5 | The agents | The resume-tailoring agent whose output schema forces honesty about gaps; the coaching agent that uses tools; the supervisor that keeps every agent bounded by iteration caps and timeouts. |
| 6 | The evaluation harness | Golden test cases and AI judges measuring agent quality; a regression gate wired into Continuous Integration so a prompt change that makes the agents worse cannot be merged. |
| 7 | User accounts and ownership | Sign-in by email link (no passwords anywhere); every record belongs to exactly one user; a test suite that proves no user can ever read another user's data. |
| 8 | Safety and cost protection | Daily usage limits per user; an emergency stop that switches the service to read-only when the daily AI budget is spent; defenses (and permanent test cases) against malicious job postings; consent, a privacy page, and a real "delete my account". |
| 9 | The product website | The public pages: upload, matches, coach, tailored resumes; long tasks run in the background with an honest live progress bar instead of a frozen page. |
| 10 | Launch and operations | Deployment; error alerts and uptime monitoring; a launch checklist; real users in widening circles (friends → university → public); a dated incident log where every incident ends in a new permanent test. |

Two design principles distinguish this build from a typical student
project, and both are established before any AI appears:

1. **Nothing is bolted on later.** Migrations, tests, cost tracking, and
   the one-gateway rule for AI calls all exist from their first possible
   moment, so the security and safety steps land on foundations that were
   shaped for them.
2. **Every claim is verifiable.** "The agents did not get worse" is a
   check that blocks a merge. "No user can see another's data" is a test
   file. "It cannot overspend" is a switch you can watch trip. In an
   interview, each claim comes with the artifact that proves it.
