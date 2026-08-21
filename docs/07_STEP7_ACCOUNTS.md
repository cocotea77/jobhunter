# Step 7 — Accounts and Ownership

This is the step that turns "my demo" into "a service": strangers from
TikTok will be able to sign in, and each will see exactly one thing —
their own data. It is also the step where the classic catastrophic bug
of multi-user systems lives: one endpoint that forgets to check
ownership, and one user reads another's resume. The whole design below
exists to make that bug structurally hard to write and impossible to
ship silently.

Time needed: about two hours.

---

## 1. New words used in this step

- **Magic link** — sign-in by clicking a one-time link sent to your
  email. No passwords exist anywhere in the system, so none can be
  stolen, reused, or demand a "forgot password" flow.
- **Session** — the signed-in state. Ours is a DATABASE ROW: the browser
  holds a random token in a cookie; the database holds that token's
  hash. Signing out deletes the row — revocation is real, not a client
  promise.
- **httpOnly cookie** — a cookie the page's JavaScript cannot read, so a
  script injected into the page cannot steal the session.
- **Hashing at rest** — storing `sha256(token)` instead of the token.
  A stolen database dump then contains nothing a browser can replay.
- **Multi-tenant** — one application, many users, each seeing only their
  own records. Enforced here by one function every candidate endpoint
  must pass through.
- **404, never 403** — the ownership answer. "Forbidden" confirms that
  someone else's data EXISTS, which is itself a leak; wrong-owner and
  nonexistent are deliberately indistinguishable from outside.

## 2. The design, in five decisions (the interview answers)

**Email links, not passwords.** No password storage liability, no reset
flows, and the sign-in demo is delightful on camera. Links are
single-use (redeeming marks them used, atomically), 15-minute, and
hashed at rest. All three failure reasons — unknown, expired, used —
return ONE identical error, so a probing attacker learns nothing about
which way a guess was wrong.

**Database sessions, not signed cookies.** A signed cookie cannot be
revoked before it expires; a row can be deleted. Logout deletes the row,
and the live checkpoint proves the very same cookie stops working.

**One ownership function.** `get_owned_candidate` in `app/auth.py` is
THE check: wrong owner or nonexistent, same 404. Every candidate-scoped
endpoint calls it; an endpoint that does not is a bug by definition —
and the hostile suite makes it a LOUD bug (below).

**Ownerless rows are invisible, not shared.** `candidates.user_id` is
nullable because rows created before accounts existed have no owner and
the migration must not guess one. The code treats NULL-owned rows as
visible to NOBODY (a test plants an orphan and proves it). Your backfill
choice, documented in the migration itself: claim old development rows
for your new account with one UPDATE, or wipe development data.

**Operator endpoints behind a shared admin token** (`x-admin-token` on
`/ingest` and `/ingest/curated`) — with a launch tripwire: if the
environment says production while the token still has its development
default, the endpoints refuse with 503. Fail early, loudly, before the
first stranger arrives.

## 3. The two guard tests (the step's crown)

**The hostile ownership suite.** User A creates a candidate and a chat
session. User B — a real, fully signed-in user — then attacks EVERY
candidate-scoped route with A's identifiers. The only acceptable answer,
every time, is 404. One parametrized test covers the entire attack
surface.

**The guard that guards the guard.** What if someone adds a new
candidate endpoint next month and forgets to add it to the attack list?
A second test compares the attack list against the application's LIVE
route table: any candidate route not under attack fails the test by
name. And a third — the route inventory — pins the WHOLE API surface,
born from a real incident disclosed below. Security that must be
remembered eventually is not; security that fails loudly when forgotten
survives.

## 4. Honest disclosure: a shipped regression, found and fixed here

While building this step, the new admin-token test refused to pass — and
the investigation found that the `/ingest` and `/ingest/curated`
endpoints HAD NOT EXISTED since the Step 4 delivery. Root cause: the
Step 4 cleanup that removed the temporary demo endpoint truncated
everything after its marker in `main.py`, which by file ordering
included the ingestion endpoints. No test called those routes over HTTP
(the integration tests exercised the underlying pipeline functions
directly), so three deliveries shipped with the defect, silently.

If you applied Steps 4–6: your Step 4 runbook checkpoint 3.3
(`curl .../ingest`) would have returned 404. This delivery's `main.py`
restores the endpoints (now admin-protected), and the new route
inventory test makes any silently vanished — or quietly added —
endpoint a named test failure forever. The lesson, stated as a rule:
**functions being tested is not the same as routes being tested; pin
the surface you promise.** This incident goes into the course exactly
as it happened, because "the new test caught a three-delivery-old
regression on its first run" is the entire argument for this way of
working.

## 5. What is in this delivery

**New:** `app/auth.py` (links, sessions, cookies, THE ownership check,
admin guard — read its opening comment), migration `0006` (`users`,
`login_tokens`, `auth_sessions`, `candidates.user_id`),
`tests/test_step7_auth.py` (lifecycle, single-use links, the hostile
suite, both guard tests, the orphan-row proof), this document.

**Replaced:** `app/models.py`, `app/config.py` (token/session lifetimes,
cookie name, admin token with its production tripwire, optional Resend
key for real email — console mode otherwise; version 0.8.0),
`app/main.py` (auth endpoints; EVERY candidate endpoint now
owner-checked; ingestion endpoints restored and admin-protected),
`conftest.py` (a root fix worth reading: the loop-poisoned connection
pool that bit four separate tests is now cured in one place — when the
same bug appears a third time in different clothes, stop patching
occurrences and fix the mechanism), `tests/test_database.py` (bookmark
`0006`; the existing product flows now sign in like real users).

## 6. Apply and verify

```bash
git checkout main && git pull && git checkout -b step/7-accounts
# copy files per CHANGES.md
alembic upgrade head && alembic current   # checkpoint: 0006 (head)
alembic check                             # checkpoint: no drift
ruff check . && pytest -v                 # checkpoint: 74 passed
```

Live (fake mode, free) — the whole lifecycle from a second terminal:

```bash
curl -s localhost:8000/candidates                      # -> 401 sign in required
curl -s -X POST localhost:8000/auth/request-link \
  -H 'Content-Type: application/json' -d '{"email":"you@example.com"}'
```

Checkpoints: the response contains `dev_link` (development only) and the
server log prints the same link. Open the link's address with curl,
saving the cookie, then replay it:

```bash
curl -s -c jar.txt "<the dev_link>"        # -> {"signed_in": true, ...}
curl -s "<the same dev_link>"              # -> 400 invalid or expired  (single-use!)
curl -s -b jar.txt localhost:8000/me       # -> your email
curl -s -b jar.txt -X POST localhost:8000/auth/logout
curl -s -b jar.txt localhost:8000/me       # -> 401  (revocation is real)
```

And the operator boundary:

```bash
curl -s -X POST localhost:8000/ingest -d '{"greenhouse":[]}' \
  -H 'Content-Type: application/json'                       # -> 401
curl -s -X POST localhost:8000/ingest -d '{"greenhouse":[]}' \
  -H 'Content-Type: application/json' -H 'x-admin-token: dev-admin-token'  # -> 200
```

Existing data note: your previously uploaded candidates now have no
owner and are invisible. Either wipe development data, or claim them
after your first sign-in:

```bash
docker compose exec db psql -U jobhunter -c \
  "UPDATE candidates SET user_id = (SELECT id FROM users LIMIT 1) WHERE user_id IS NULL"
```

Ship: Pull Request on green → squash-merge → `git tag step-7 && git push --tags`.

## 7. Check your understanding

1. Why are sessions database rows instead of signed cookies, given that
   signed cookies need no database lookup per request?
2. Why do all three sign-in-link failures (unknown, expired, already
   used) return the same error message?
3. The hostile suite has three layers: the attack test, the
   attack-list-versus-live-routes test, and the route inventory. What
   distinct failure does each one catch?
4. In your own words: why did the ingestion-endpoint regression survive
   three deliveries, and which single sentence of testing philosophy
   prevents its whole class?

*Answers: (1) The lookup buys revocation: a deleted row ends the session
now, while a signed cookie stays valid until it expires no matter what —
and "logout that does not log out" is a real harm the first time a user
signs in on a shared computer. One indexed lookup per request is the
cheapest security purchase in the project. (2) Distinct errors would let
an attacker distinguish "no such token" from "valid but expired" from
"valid and already used" — a probing oracle. One message starves the
probe. (3) The attack test catches an endpoint that skips the ownership
check; the list-versus-routes test catches a NEW candidate endpoint
nobody added to the attack; the inventory catches endpoints vanishing or
appearing anywhere in the API. Together: wrong answers, missing
coverage, and a shifting surface. (4) The tests exercised the pipeline
FUNCTIONS, which stayed healthy, while the ROUTES over HTTP were never
called by any test — so deleting them broke nothing that was measured.
The sentence: functions being tested is not the same as routes being
tested; pin the surface you promise.*
