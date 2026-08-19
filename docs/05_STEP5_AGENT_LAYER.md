# Step 5 — The Agent Layer

Until now, JobHunter's agents answered one question and stopped. This
step builds agents that ACT: a tailoring agent whose output format forces
it to confess what it did not claim; a coach that answers by using tools
— including invoking the tailoring agent as a tool, which is how
multi-agent systems compose; and above them a supervisor with no AI in it
at all, owning everything an agent should not be trusted to own about
itself.

Time needed: about two hours, plus the real-mode conversation in 3.5.

---

## 1. New words used in this step

- **Tool use** — the model, mid-conversation, requests a named function
  with arguments; our code executes it and feeds the result back; the
  model continues with real data. The loop repeats until the model
  answers in text — or hits its cap.
- **Bounded agency** — every loop has an iteration cap AND a wall-clock
  timeout. An agent loop without bounds is a bill without bounds.
- **Sub-agent as tool** — one agent exposed behind another agent's tool
  interface. The coach's `tailor_resume` tool IS the tailoring agent.
- **Supervisor / orchestrator** — deterministic code above the agent:
  validation, session identity, the timeout, persistence. The agent
  decides what to say; the supervisor decides whether the conversation
  may happen at all and what history is kept.
- **Errors are data** — a failing tool returns `{"error": ...}` INTO the
  conversation so the model can adapt, instead of the request crashing.

## 2. The three structural rules (the interview answers)

**Least privilege by shape.** Every tool receives the candidate identity
from the server-side session — the model's own output cannot name a
candidate. It chooses WHICH JOB to discuss; it is structurally unable to
reach another person's data. Security by code shape beats security by
prompt instruction, and the integration test proves it: a second
candidate presenting the first one's session number receives "404 not
found" — deliberately not "403 forbidden", which would confirm the
session exists.

**Honesty as schema, again, harder.** Tailoring is where the temptation
to fabricate is strongest — the easiest way to "improve" a resume is to
invent the missing qualifications. `TailoredContent` therefore REQUIRES
`gaps_not_claimed` (what the posting wants that we deliberately did not
claim) and `change_log` (every change, declared). Omitting the
confession is a validation error, not a style choice. These fields are
the evidence Step 6's automated judge will read against the stored raw
resume.

**The supervisor holds the clock and the pen.** The orchestrator
validates input (empty, oversized, unknown candidate), owns sessions,
wraps the whole turn in `asyncio.wait_for`, and persists the transcript
with per-turn metadata: which tools ran, how long, whether it timed out.
Memory rule worth quoting: the transcript keeps user/assistant TEXT
only; tool traffic lives and dies inside its turn — replaying stale tool
payloads bloats context and can contradict fresh data, so if the coach
needs data again next turn, it calls the tool again.

## 3. What is in this delivery

**New:** `app/agents/tailor.py` (the honesty-schema agent, a pure core
like `score_match` — production and future evals share it),
`app/agents/coach.py` (tool schemas whose descriptions state cost and
when-to-use — the model reads them to decide; the least-privilege
executor; the scripted fake plan; the bounded loop),
`app/agents/orchestrator.py`, migration
`0004` (`tailored_resumes`, `chat_sessions`, `chat_messages`),
`tests/test_step5_agents.py`, this document.

**Replaced:** `app/llm.py` (the third and last gateway door,
`generate_with_tools` — tool-using round trips, measured like everything
else; fake turns are scripted by the caller, because only the caller
knows its conversation state), `app/models.py`, `app/config.py`
(iteration cap 5, turn timeout 120s, input cap 4000 chars; version
0.6.0), `app/main.py` (four endpoints: tailor, tailored list, chat,
transcript), `tests/test_database.py` (bookmark `0004`; the agent-layer
integration test).

Fake mode note: the fake coach is a deterministic script driving the
REAL loop — real tool execution, real persistence, real caps. What is
canned is only the model's choices. Students watch an agent wield tools,
free.

## 4. Apply and verify

```bash
git checkout main && git pull && git checkout -b step/5-agents
# copy files per CHANGES.md
alembic upgrade head && alembic current   # checkpoint: 0004 (head)
alembic check                             # checkpoint: no drift
ruff check . && pytest -v                 # checkpoint: 53 passed
```

Live loop (fake mode, free — requires a candidate with matches from
Step 4):

```bash
curl -s -X POST localhost:8000/candidates/1/chat \
  -H 'Content-Type: application/json' -d '{"message":"What are my top matches?"}'
```

Checkpoint: `tools_used` contains `list_matches`; the reply names a real
company and title from YOUR stored matches; note the `session_id`.

```bash
curl -s -X POST localhost:8000/candidates/1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Please tailor my resume for the top match.","session_id":<SID>}'
```

Checkpoint: `tools_used` is `["list_matches","tailor_resume"]` — the
coach looked, then delegated to the sub-agent; a new row appears at
`/candidates/1/tailored`, whose `content` includes populated
`gaps_not_claimed` and `change_log`. Then read the transcript:

```bash
curl -s localhost:8000/candidates/1/sessions/<SID>/messages
```

Checkpoint: ordered messages; each assistant row carries
`meta.tools_used` and `meta.latency_ms`; `timed_out` false. And the
guardrails: an empty message returns 400; a second candidate using your
`session_id` returns 404.

**Real mode (3.5).** Set `FAKE_AI=false` with your keys, restart, and
hold the conversation for real (a few cents). Two probes matter most.
The grounding probe: ask about a company that is NOT in your matches —
the coach must say it is not among your stored matches, never invent a
score. The honesty audit, tailoring edition: open the tailored content
next to your real resume — every fact in every bullet must exist in the
original, and a requirement you genuinely lack must appear in
`gaps_not_claimed`, NOT in the resume body. Fabrication found = red-flag
failure: tighten `TAILOR_SYSTEM`, retest, and keep the audit note for
Step 6.

Ship: Pull Request on green → squash-merge → `git tag step-5 && git push --tags`.

## 5. Exercise — feel the cap (five minutes, free)

In `.env` set nothing — instead, in `app/config.py`, temporarily change
`coach_max_iterations` to `1`. Ask the tailoring question again.
Checkpoint: the coach looks (`list_matches`), runs out of budget before
it can delegate, and returns the honest "step budget" fallback — the cap
working as designed, visible from the outside. Restore to 5; `pytest`
proves the world is whole.

## 6. Check your understanding

1. Why do tools receive `candidate_id` from the session rather than from
   the model's own arguments — and why is that stronger than telling the
   model "never access other candidates"?
2. Why does the transcript keep only user/assistant text, discarding
   tool traffic between turns?
3. A tool crashes mid-conversation. Trace what the user experiences, and
   name each design rule involved.
4. The wrong-candidate session probe expects 404, not 403. Why?

*Answers: (1) A prompt rule is advice the model could ignore or be
tricked out of; a parameter the model cannot supply is a wall. The tool
executor's signature makes cross-candidate access structurally
impossible — code shape, not model virtue. (2) Stale tool payloads
bloat every future turn's cost and can contradict fresh data; re-calling
the tool when needed guarantees answers come from current reality — at
the acceptable price of an occasional repeated call, which agent_runs
makes visible. (3) The exception is caught at the tool boundary and
serialized as {"error": ...} into the conversation (errors are data);
the loop continues and the model replies, adapting to the failure; the
round trips were recorded either way (one gateway); worst case the cap
or timeout ends the turn with an honest fallback (bounded agency). The
user sees a reply — possibly an apologetic one — never a traceback. (4)
403 confirms the session EXISTS, which is itself a leak about another
person's data; 404 reveals nothing. Same rule the orchestrator applies:
wrong owner and nonexistent are indistinguishable from outside.*
