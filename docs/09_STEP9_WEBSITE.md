# Step 9 — The Product Website

Until now, JobHunter could only be operated by someone comfortable with
`curl`. After this step it is a website: sign in, upload a resume with a
consent checkbox, watch matching progress on a real progress bar, read
ranked matches with their explanations, talk to the coach, and read
tailored resumes with their honesty fields displayed — everything a
TikTok viewer needs, and nothing they must install.

This step also changes the backend in one important way: matching now
runs as a BACKGROUND JOB the browser polls, because a public website
must never hold a request open for a minute while twenty-five AI calls
finish.

Time needed: about three hours.

---

## 1. Definitions first, then plain words

Each concept below is stated twice: first rigorously, so the definition
can be relied on precisely; then in plain words, so it can be understood
the first time. Both say the same thing.

**Frontend / backend split.**
*Rigorous definition:* an architecture in which the user-interface
program (frontend) and the data-and-logic program (backend) are separate
processes, communicating exclusively through a documented HTTP API, such
that either side can be developed, tested, deployed, and replaced
independently while the API contract holds.
*In plain words:* two programs instead of one. The backend is everything
we built in Steps 0–8; the frontend is a second, smaller program whose
only job is showing screens and calling the backend. They talk through
the same endpoints you have been testing with `curl` — the frontend is
just a very polite, very fast `curl` user with good taste in buttons.

**HTTP origin.**
*Rigorous definition:* the triple (scheme, host, port) of a URL — for
example `http://localhost:3000`. Two URLs share an origin if and only if
all three components are equal. Browsers partition security state,
including cookies, by origin.
*In plain words:* the browser's idea of "which website am I on." Port
3000 and port 8000 on the same machine are DIFFERENT websites to a
browser, even though they are inches apart — and the browser will not
hand one website's cookies to another.

**CORS (Cross-Origin Resource Sharing).**
*Rigorous definition:* a browser-enforced protocol in which a server
declares, via response headers, which foreign origins may read its
responses from scripts; absent such headers, the browser blocks
cross-origin reads regardless of what the server actually returned.
*In plain words:* the browser's rule that website A's JavaScript may not
read website B's data unless B explicitly says "A is allowed." A
constant source of confusing errors — which is why this project's design
makes most of them impossible (next definition).

**Same-origin proxy.**
*Rigorous definition:* a frontend server configuration that forwards
requests matching a path prefix (here `/api/*`) to the backend and
relays the responses, so that from the browser's perspective every
request targets the frontend's own origin.
*In plain words:* the frontend acts as a mail-forwarding office. The
browser only ever talks to ONE website (the frontend); requests whose
address starts with `/api` are quietly passed to the backend and the
answers passed back. Because the browser sees one origin, cookies just
work and CORS mostly never comes up. One line in `next.config.ts` buys
this entire simplification, in development and in production alike.

**httpOnly cookie (revisited from Step 7, now with the proxy).**
*Rigorous definition:* a cookie attribute instructing the browser to
attach the cookie to matching HTTP requests while denying all access to
it from JavaScript; combined with the proxy, the session cookie is set
by, and returned to, the frontend origin.
*In plain words:* the sign-in cookie rides along automatically on every
`/api/...` call and no script — ours or an attacker's — can read it.
This is why `frontend/app/auth/verify/page.tsx` redeems the sign-in
token THROUGH the proxy path: the cookie must land on the website the
browser is actually visiting.

**Background job.**
*Rigorous definition:* a unit of work executed outside the
request-response cycle that initiated it; the initiating request returns
immediately with a job identifier, and the job's lifecycle is tracked as
persistent state (here: a `match_jobs` row with status, progress
counters, and error).
*In plain words:* "start it and give me a ticket." Matching takes up to
a minute in real mode; no browser, phone, or proxy should hold a
connection open that long. So POST /match now answers in milliseconds
with a ticket number, the work happens behind the counter, and the
ticket can be checked anytime.

**Polling.**
*Rigorous definition:* a client-side pattern in which the current state
of a resource is obtained by repeated GET requests at an interval, until
the resource reaches a terminal state.
*In plain words:* the page asks "is it done yet?" every second — like
checking an oven — and stops asking when the answer is "done" or
"failed." Unfashionable, and exactly right at this scale: no sockets, no
streams, nothing new to break, and each poll response carries the real
numbers ("scored 14 of 25") the progress bar draws.

**Terminal state.**
*Rigorous definition:* a state from which a state machine defines no
outgoing transitions. This project's match jobs have exactly four
states — `queued`, `running`, `done`, `failed` — of which `done` and
`failed` are terminal.
*In plain words:* the states where the story ends. The page keeps
polling while the job is `queued` or `running` and stops at the other
two. The startup sweep from the backend half of this step guarantees no
job can sit in `running` forever after a server restart — every ticket
eventually tells the truth.

**TypeScript strict mode, and union types.**
*Rigorous definition:* TypeScript is JavaScript plus a static type
system; `"strict": true` enables the compiler's full set of soundness
checks. A union type such as
`status: "queued" | "running" | "done" | "failed"` restricts a value to
an enumerated set, checked at compile time.
*In plain words:* the frontend's compiler refuses to build the site if
any code touches a field that does not exist or a status that can never
occur. During verification, my own smoke script waited for a status
called `succeeded` — a string the backend never sends. The SCRIPT was
plain Python and failed only at runtime; the FRONTEND could not have
made that mistake, because `"succeeded"` is not in the union and the
build would have refused. That incident, preserved here, is the whole
argument for typed clients.

**Client component (versus static prerender).**
*Rigorous definition:* in Next.js's App Router, a component marked
`"use client"` executes in the browser and may hold state and effects;
unmarked components render on the server, and pages composed of them can
be prerendered to static HTML at build time.
*In plain words:* our pages are interactive — they poll, hold form
state, react to clicks — so each page file starts with `"use client"`.
The build output listed all eight routes as static shells that hydrate
into living pages in the browser.

**Design tokens.**
*Rigorous definition:* named constants (CSS custom properties) for
color, spacing, radius, and typography, declared once and referenced
everywhere, so that visual identity is data rather than repetition.
*In plain words:* the site's whole look lives in one short block at the
top of `globals.css`. Change `--accent` there and every button, link,
and progress bar changes together. No CSS framework is installed — the
entire site's first load is about 107 kilobytes, which is why it will
feel instant in a TikTok viewer's in-app browser.

**Environment variable (the deployment seam).**
*Rigorous definition:* a named value provided by the process environment
at startup, read by the program, and varying by deployment without code
change. The proxy target is `BACKEND_URL`, defaulting to
`http://localhost:8000`.
*In plain words:* the one knob that moves between laptop and production.
On your Mac it points at your local backend; on Vercel it will point at
the Railway backend URL. Same code, one variable — this is the seam
Step 10 deploys along.

## 2. What was built (backend half)

Migration `0008` creates `match_jobs`. POST /candidates/{id}/match now
creates a row, schedules `execute_match_job` as a background task, and
returns `{match_job_id, status: "queued"}` immediately. The worker moves
the row through the state machine, writing progress (`scored`,
`total_to_score`) as each AI call completes — `run_matching` gained a
progress callback fed by `asyncio.as_completed`, so the numbers are
real, not animated. Every ending is recorded: success (`done`), any
exception (`failed` with the reason), including the Step 8 budget stop —
a refused run is a failed job whose error names the budget, never a
silent hang. A startup sweep marks any job left `queued`/`running` by a
server restart as `failed: interrupted by a server restart` — the
zombie-job test proves it. `/health` gained `jobs_indexed` so the
frontend can warn when the job table is empty. CORS middleware is
configured for the production case where the frontend and backend hosts
differ (harmless under the proxy, necessary without it).

The route inventory grew by exactly one route — reviewed, deliberate,
the Step 7 guard doing its job.

## 3. What was built (frontend)

Thirteen files; the ones to read first:

- `next.config.ts` — the whole proxy: `/api/:path*` →
  `${BACKEND_URL}/:path*`. One rewrite rule carries the architecture.
- `lib/api.ts` — the typed client. ONE `request()` function owns
  errors (an `ApiError` carrying status + detail, so pages can treat
  429/503 kindly), and every endpoint is a named, typed function.
  Pages never write `fetch` themselves.
- `app/globals.css` — the design system: tokens, dark palette, cards,
  buttons, progress bar. No framework.
- `app/page.tsx` — status, sign-in (with the development link button),
  consented upload, candidate picker.
- `app/matches/page.tsx` — enqueue, poll, the real progress bar
  ("Scoring match N of M"), ranked match cards with strengths and gaps,
  kind banners for 429 (allowance) and 503 (budget), tailor buttons.
- `app/coach/page.tsx` — the chat, showing each reply's `tools_used`
  and latency: the agent's homework, visible.
- `app/tailored/page.tsx` — tailored content with `gaps_not_claimed`
  as a highlighted banner and the change log — honesty as interface.
- `app/auth/verify/page.tsx` — redeems the emailed token through the
  proxy so the cookie lands on the frontend origin (see the httpOnly
  definition above).

## 4. Verified before delivery, and one honest boundary

In my environment: `npm run build` compiles cleanly under strict
TypeScript (eight routes, ~107 kB first load); backend and frontend ran
together and the ENTIRE user journey was driven through the proxy port —
sign-in link requested and redeemed, consented upload parsed, matching
enqueued, the job polled through `running` to `done` with real progress
numbers (scored 2 of 2), matches returned correctly ranked, the coach
answered using `list_matches`, and a tailored resume came back with its
honesty fields populated. The backend suite stands at 86 tests, passing
three consecutive runs, and the eval gate is clean at 8/8.

The boundary: I cannot open a browser here, so clicking, rendering, and
visual behavior are exactly what YOUR runbook verifies below — my
verification covered the build, the proxy, and every API sequence the
pages perform.

## 5. Apply and verify

Prerequisite once: install Node.js 20 or newer (`brew install node`),
then check `node --version`.

```bash
git checkout main && git pull && git checkout -b step/9-website
# copy files per CHANGES.md
alembic upgrade head && alembic current   # checkpoint: 0008 (head)
ruff check . && pytest -v                 # checkpoint: 86 passed
cd frontend && npm install && npm run build   # checkpoint: "Compiled successfully",
                                              # 8 routes listed
```

Run both halves (two terminals):

```bash
uvicorn app.main:app --reload              # terminal 1 — backend :8000
cd frontend && npm run dev                 # terminal 2 — frontend :3000
```

Open http://localhost:3000 and walk the journey:

1. **Sign in** — enter your email; in development a "open sign-in link"
   button appears (the `dev_link`). Checkpoint: after clicking it you
   land back on the site signed in, your email shown in the navigation.
2. **Upload** — choose a resume; the consent box must be ticked or the
   button stays disabled (and the backend would refuse anyway — belt
   and suspenders). Checkpoint: your name and extracted skills appear.
3. **Matches** — press "Find my matches". Checkpoint: the progress bar
   advances with real numbers ("Scoring match 3 of 8"), then ranked
   cards appear with strengths and gaps. Press it three more times:
   the fourth attempt shows the kind allowance banner (429) with the
   midnight reset — the Step 8 quota, now with a face.
4. **Coach** — ask "what are my top matches?". Checkpoint: the reply
   cites your actual stored matches, and under it the tools-used line
   shows `list_matches` with the latency.
5. **Tailored** — from a match card press "Tailor my resume", then open
   the Tailored page. Checkpoint: the gaps banner lists what was NOT
   claimed, and the change log lists every edit.
6. **Restart honesty** — start a matching run, kill the backend
   mid-progress (Ctrl-C), restart it, reload the page. Checkpoint: the
   job shows failed with "interrupted by a server restart" — no
   eternal spinner.

Ship: Pull Request on green → squash-merge → `git tag step-9 && git push --tags`.

## 6. Exercises

1. **Feel the union type.** In `matches/page.tsx`, change a status
   comparison to `"succeeded"` and run `npm run build`. Checkpoint: the
   compiler refuses, naming the line — the mistake my untyped smoke
   script made at runtime, caught before the code could exist.
2. **Feel the proxy.** Stop the backend but keep the frontend running.
   Checkpoint: the site loads (it is static), and the status banner
   reports the backend unreachable — the two halves fail independently,
   which is the point of the split.
3. **Move a token.** Change `--accent` in `globals.css` and watch every
   interactive element change together. Design as data.

## 7. Check your understanding

1. Why does the browser refuse to send the session cookie to
   `localhost:8000` when the page came from `localhost:3000`, and which
   single configuration line makes the problem disappear?
2. Why is polling the right choice here, when streaming updates
   (WebSockets, server-sent events) are strictly more capable?
3. The progress bar could have been a fake animation timed to feel
   right. Name two concrete things the real-numbers design gives you
   that the animation cannot.
4. Why does the sign-in verification page redeem the token through
   `/api/auth/verify` rather than calling the backend's address
   directly?

*Answers: (1) Different port means different origin, and the browser
partitions cookies by origin — the proxy rewrite in `next.config.ts`
makes every API call target the frontend's own origin, so the cookie
travels naturally. (2) Capability is not the criterion; operational
surface is. Polling adds zero infrastructure, works through every
proxy and phone network, degrades gracefully, and its worst case — a
few redundant GETs — is harmless at this scale. Streaming earns its
complexity when updates are frequent and latency-critical; a
once-per-second progress number is neither. (3) Honesty under failure
(the bar stops where the work stopped, and the failed state names why —
an animation would glide on) and operator truth (the same numbers are
in the database row, so a user report of "stuck at 14 of 25" is
directly investigable). (4) Because the cookie must be set on the
origin the browser is visiting — the frontend's. Redeemed directly
against the backend origin, the cookie would belong to the wrong
website and every subsequent `/api` call would arrive signed out.*
