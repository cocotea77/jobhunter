# Step 12 — The RAG Pipeline: "Ask JobHunter"

The product gains a question-answering feature: a candidate asks
anything about their matched jobs — "which of these allow remote work?",
"what do my top matches want that I lack?" — and the answer is built
from the actual posting text, with citations the user can open. One
feature; underneath it, every essential Retrieval-Augmented Generation
skill a beginner-to-mid AI agent engineer is expected to hold, each as a
named, tested stage of one pipeline:

  question → query rewriting → hybrid search (vector + keyword, fused)
  → reranking → retrieval grading (one bounded retry) → context
  budgeting → cited answer → deterministic citation validation

Time needed: about three hours.

---

## 1. Definitions first, then plain words

**Retrieval-Augmented Generation (RAG).**
*Rigorous definition:* an architecture in which, at answer time,
relevant documents are retrieved from an external corpus and inserted
into the model's context, so that the model's output is conditioned on
retrieved evidence rather than solely on its training-time knowledge.
*In plain words:* instead of asking the model to remember, hand it the
right pages and ask it to read. The model's job shrinks from "know
everything" to "read this and answer" — which it is far better at.
JobHunter's matching was already RAG-shaped (retrieve 25 by similarity,
reason over the top 8); this step builds the full, explicit pipeline.

**Chunking, and overlap.**
*Rigorous definition:* partitioning a document into retrieval units of
bounded size, where consecutive units share a fixed-length suffix/prefix
(the overlap), so that any span shorter than the overlap is contained
whole in at least one unit.
*In plain words:* you cannot retrieve half a fact. Whole documents are
too big to embed usefully (one vector averaging many topics matches
nothing well), and sentences are too small (no context), so we cut
postings into paragraph-aware pieces of about 900 characters — and each
piece carries the tail of the previous one, so a sentence sitting on a
boundary is never split across both and lost to search. Chunking
quality silently bounds everything downstream: retrieval cannot find
what chunking destroyed.

**Lexical (keyword) search; BM25; Postgres full-text search.**
*Rigorous definition:* retrieval by term matching over an inverted
index, scored by functions such as BM25, which weight a term by its
rarity in the corpus and its frequency in the document, normalized by
document length. PostgreSQL's built-in full-text search (`tsvector`,
`ts_rank_cd`) is the same family: token-based indexing with
frequency-and-rarity ranking.
*In plain words:* old-fashioned exact-word search, and still
irreplaceable — embeddings are good at *meaning* but blur *exact
strings*. A query for "kubernetes" or "SQLAlchemy 2.0" must match those
literal tokens, and a keyword index guarantees it. We use Postgres's
native full-text search — the classic BM25 engine is Elasticsearch, but
our ranking lives in the database we already operate, as a GENERATED
column the database maintains itself, with a GIN index. Knowing when
the built-in tool suffices is itself the skill.

**Hybrid search.**
*Rigorous definition:* executing semantic (vector) retrieval and
lexical retrieval in parallel over the same corpus and combining their
ranked results, so the result set inherits vector search's recall on
paraphrase and keyword search's precision on exact terms.
*In plain words:* run both searches and merge, because each covers the
other's blind spot. "Jobs where I'd work from home" finds "fully remote
position" through meaning (vectors); "jobs requiring kubernetes" finds
the literal word (keywords). One without the other misses real answers
— which is why job postings for this skill say "hybrid," not "vector."

**Reciprocal Rank Fusion (RRF).**
*Rigorous definition:* a rank-aggregation method assigning each
document the score Σ 1/(k + rᵢ) over its ranks rᵢ in each result list
(k typically 60), and ordering by total score; it requires only ranks,
never the incomparable raw scores of different systems.
*In plain words:* the merge rule for hybrid search. You cannot average
a cosine distance with a keyword score — different units, different
scales — but you CAN combine *positions*: each appearance earns points
that shrink with rank, and appearing in several lists adds up.
Agreement is evidence: a chunk both methods rank moderately beats a
chunk one method ranks first. Our test suite proves that exact property
— and my own first version of that test asserted the opposite and
failed, which is preserved in the test's comment: 1/63 + 1/64 > 1/61.
Doing the arithmetic beats trusting intuition.

**Reranking; cross-encoder versus LLM-as-reranker.**
*Rigorous definition:* a second-stage scoring of retrieved candidates
in which the query and each document are evaluated JOINTLY (full
attention across both texts), as opposed to first-stage retrieval,
which compares independently precomputed representations. A
cross-encoder is a compact model purpose-trained for this joint
scoring; an LLM prompted to score relevance performs the same function
with more capability and more cost.
*In plain words:* first-stage retrieval is a fast, slightly blurry
filter — the query and each chunk were embedded separately, so neither
"looked at" the other. The reranker reads them *together* and asks
"does this chunk actually help answer this question?", fixing
near-miss rankings. The classic tool is a cross-encoder (fast, cheap,
but a separate model to serve); we use the LLM through our existing
gateway — measured, budget-capped, fake-able like everything else.
Knowing the trade-off is the interview answer: cross-encoders win at
high volume; LLM reranking wins when you already operate an
instrumented gateway and your volumes are modest.

**Retrieval grading; corrective RAG.**
*Rigorous definition:* an explicit judgment step assessing whether the
retrieved set is sufficient to answer the query, with an unsatisfactory
grade triggering a bounded corrective action (query reformulation,
alternative retrieval) before answering.
*In plain words:* before answering, the pipeline asks itself "did I
actually find it?" — and if not, it gets ONE retry with the raw
question as a literal query (the classic recovery when rewriting
over-split the question), then answers or honestly declines. Bounded is
the operative word: the same rule as the coach's iteration cap. A
pipeline that can notice its own empty hands is the difference between
RAG and confident hallucination with citations.

**Context window; token budget.**
*Rigorous definition:* the model's context window is the maximum token
sequence it can attend to; a context budget is an application-imposed
ceiling on retrieved-context tokens, with inclusion decided by rank
until the budget is exhausted.
*In plain words:* you cannot ship every chunk to the model, and past a
point you should not — more context is more cost, more latency, and
more places for the model's attention to wander. We spend an explicit
budget (2,000 tokens, approximated as characters ÷ 4 and *stated* as an
approximation), best chunks first, and the response reports what was
spent — cost discipline as a feature, same philosophy as `agent_runs`.

**Groundedness; citation; and who verifies.**
*Rigorous definition:* an answer is grounded if every claim is
supported by the provided context; a citation is a machine-checkable
reference from the answer to a specific retrieved unit. Citation
validity — every cited unit was actually provided — is verifiable
deterministically, while claim-level groundedness requires reading
comprehension (a judge).
*In plain words:* the answer must show its sources, and the pipeline
must not take the model's word for it. Our answering schema requires
chunk-id citations; then a for-loop — not the model — verifies every
cited id was truly in the context, and a fabricated citation causes the
pipeline to REFUSE the answer rather than present invention as sourced
fact. The model claims; deterministic code verifies: the same division
of labor as the tailoring agent's faithfulness checks.

**Retrieval metrics: hit rate.**
*Rigorous definition:* hit rate (recall@k) is the fraction of
evaluation queries for which a known-relevant document appears among
the top k retrieved; it isolates retrieval quality from answer quality.
*In plain words:* "did the right chunk even reach the model?" — because
if retrieval dropped the answer, no prompt can save you. Our golden
cases encode it as the `gold_chunk_was_sent` check: each answerable
case names its gold chunk, and the suite verifies the pipeline
delivered it. Debugging RAG starts here: first ask WHERE it failed
(retrieval? reranking? answering?), and the per-stage checks answer
that by name.

**Pipeline RAG versus agentic RAG.**
*Rigorous definition:* pipeline RAG executes a fixed retrieval-then-
generate sequence per query; agentic RAG places retrieval behind tools
that a model invokes, choosing when and what to retrieve across a
multi-step interaction.
*In plain words:* "Ask JobHunter" is a pipeline — same stages, every
question, predictable and testable. The coach from Step 5 is agentic —
it *decides* to call `list_matches`. Both are real RAG; the pipeline is
where the retrieval engineering lives, and the coach could later use
this pipeline as one more tool. Knowing which shape a problem needs is
the architecture skill.

## 2. What is in this delivery

**New:** migration `0009` (`job_chunks`: content, embedding, and a
database-GENERATED `tsvector` column with a GIN index — the two hybrid
representations in one row, the word index maintained by Postgres
itself so code can never forget to update it); `app/rag.py` — every
stage above as a named function, orchestrated by `ask()`, with fake
mode throughout (deterministic word-overlap scoring, scripted rewrites
— free, offline, CI-ready); `POST /candidates/{id}/ask` behind the same
walls as every AI action (ownership, a new 20-per-day question quota,
the budget stop inside the gateway); three RAG golden cases —
answerable, honestly-unanswerable, and an ADVERSARIAL case whose chunk
contains instructions to the AI, caught by the same data-never-
instructions rule as Step 8; the `rag` eval suite wired into the
runner, the gate, and CI (baseline moved 8 → 11 in a reviewed diff);
`tests/test_step12_rag.py` — chunker coverage and determinism, the RRF
agreement property, budget ceiling and rank order, fabricated-citation
detection, and the full pipeline against the real database.

**Replaced:** `app/models.py`, `app/config.py` (chunking, retrieval,
budget, and quota settings; version **1.1.0** — a MINOR bump, because
this step ships a backward-compatible capability; the capstone's
version-pin test was updated with that rule stated), `app/main.py`,
`evals/cases.py`, `evals/checks.py`, `evals/run.py`,
`evals/baseline.json`, `tests/test_step7_auth.py` (the ask route joined
the attack list and the route inventory, consciously),
`tests/test_database.py` (bookmark `0009`),
`tests/test_step11_capstone.py`.

**Verified here:** migration applies, reverses, re-applies, drift-clean
(the drift check earned its keep once more: it caught the GIN index
existing in the migration but not the model, and refused until they
agreed). 112 tests, three consecutive green runs. Eval gate clean at
11/11. Live smoke through the real endpoint: the remote-work question
cited the remote posting's chunk; the kubernetes question cited the
posting that requires it; the salary question — which the corpus cannot
answer — was honestly refused with zero citations after its one bounded
retry. Two build incidents preserved as teaching material: my own RRF
test asserted intuition over arithmetic and lost (the corrected test
carries the calculation), and the first integration fixture used
phrasing ("fully remote position") that fake mode's word-overlap
honestly graded insufficient against "remote work" — the machinery was
right, the fixture was unnatural, and the distinction is the lesson.

**The honest boundary:** real-mode quality — the rewriter's phrasing,
the reranker's judgment, the adversarial chunk resisted by a real model
— is your runbook 4 checkpoint, a few cents.

## 3. Apply and verify

```bash
git checkout main && git pull && git checkout -b step/12-rag
# copy files per CHANGES.md
alembic upgrade head && alembic current   # checkpoint: 0009 (head)
alembic check                             # checkpoint: no drift
ruff check . && pytest -v                 # checkpoint: 112 passed
python -m evals.run --suite rag           # checkpoint: 3/3, gate clean
```

Live (fake mode, free; signed in, with matches from Step 9's runbook):

```bash
curl -s -b jar.txt -X POST localhost:8000/candidates/1/ask \
  -H 'Content-Type: application/json' \
  -d '{"question": "Which of my matches allow remote work?"}' | python3 -m json.tool
```

Checkpoints: `answer` quotes real posting text; `citations` contains
the chunk(s) with their `job_id`s; `meta.sub_queries` shows the
rewrite; `meta.context_tokens` shows the budget spent. Then ask
something the postings cannot answer (salary is usually absent):
checkpoint — an honest "the postings do not say," `citations: []`.
Then the walls: an empty question → 400; the 21st question of the day
→ 429 with the midnight reset.

**Real mode (a few cents):** set `FAKE_AI=false`, restart, ask both
questions again, and run `python -m evals.run --suite rag` — review
that the adversarial case's answer ignored the embedded instruction and
`--update-baseline` through a Pull Request.

Ship: Pull Request on green → squash-merge → `git tag step-12 && git push --tags`.

## 4. Exercises

1. **Break retrieval, watch the named check catch it.** In
   `hybrid_search`, change `LIMIT :lim` to `LIMIT 1` and run the eval
   suite. Checkpoint: `gold_chunk_was_sent` fails by name — the
   pipeline dropped the answer before the model ever saw it, and the
   harness tells you WHICH stage. Restore.
2. **Feel the budget.** Set `rag_context_token_budget` to 50 and ask a
   question. Checkpoint: `meta.chunks_sent` drops to 1 and
   `context_tokens` obeys the ceiling — cost control you can see.
3. **Feel the fusion.** Ask "which job requires kubernetes?" and read
   `meta.sub_queries`, then check which retrieval method could have
   found the literal word. This is why hybrid exists.

## 5. Registered extensions (not built, on purpose)

GraphRAG (entity-relationship traversal) — powerful for relationship-
heavy corpora; job postings are flat documents, so building it here
would be skill-collecting, not engineering. Trigger: a corpus with real
entity structure. OCR for scanned documents — a heavy dependency for
marginal teaching value; our extraction already fails honestly on
scans. Trigger: real users uploading scanned resumes. A served
cross-encoder reranker — trigger: reranking volume where LLM cost
dominates. Each is one honest sentence in an interview: "I know what it
is, why I did not need it, and what would change my mind."

## 6. Check your understanding

1. Why does hybrid search need BOTH methods — give one query each
   method would miss alone.
2. Why does RRF fuse ranks instead of scores?
3. Citation validity is checked by a for-loop, but groundedness needs a
   judge. Why the split?
4. The unanswerable golden case is as important as the answerable one.
   What failure mode does it pin?

*Answers: (1) "Jobs where I'd work from home" — keyword search misses
it (no shared words with "fully remote position") while vectors catch
the meaning; "jobs requiring SQLAlchemy 2.0" — vectors blur the exact
token while the keyword index matches it literally. Each method's
blind spot is the other's strength. (2) A cosine distance and a
ts_rank_cd score have different units and scales — averaging them is
meaningless — but positions are comparable across any two ranked
lists, so fusing ranks needs no calibration and rewards cross-method
agreement, which is exactly the evidence hybrid search exists to
collect. (3) "Was cited chunk 302 in the context?" is set membership —
deterministic code answers it perfectly and cheaply, so a model must
never be trusted with it. "Does the answer's claim actually follow
from chunk 302?" requires reading comprehension, which only a judge
can do — the rule, as everywhere in this project: never spend a model
on what a for-loop can verify, never trust self-report for what it
can't. (4) That the pipeline would rather answer than admit ignorance
— the RAG-specific failure where fluent hallucination arrives dressed
in citations. Pinning "cites nothing, says the postings do not say"
makes honest refusal a tested behavior, not a hope.*
