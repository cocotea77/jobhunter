"""Step 12 tests: every RAG stage held to its promise.

Unit layer: the pure stages (chunker, fusion, budget, citation
validation) with cases designed to FAIL if the logic drifts. Integration
layer: the whole pipeline against the real database — seeded jobs with a
known answer, retrieval must find it, the answer must cite it.
"""

import asyncio
from types import SimpleNamespace

import asyncpg
import pytest

from app.config import settings
from app.rag import (
    chunk_text,
    reciprocal_rank_fusion,
    trim_to_budget,
    validate_citations,
)

DATABASE_URL = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def _database_is_running() -> bool:
    async def probe() -> None:
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        await connection.close()

    try:
        asyncio.run(probe())
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _database_is_running(),
    reason="database is not running — start it with: docker compose up -d",
)


# --- the chunker's three promises -------------------------------------------


def test_chunker_covers_all_content_within_size_and_overlaps():
    paragraphs = [f"Paragraph {n}: " + ("fact " * 40) for n in range(12)]
    document = "\n\n".join(paragraphs)
    chunks = chunk_text(document)

    assert len(chunks) > 1, "a long document must split"
    for chunk in chunks:
        assert len(chunk) <= settings.rag_chunk_chars + settings.rag_chunk_overlap_chars
        assert chunk.strip(), "no empty chunks"
    # Coverage: every paragraph's identifying sentence appears somewhere.
    joined = "\n".join(chunks)
    for n in range(12):
        assert f"Paragraph {n}:" in joined, f"paragraph {n} was lost in chunking"


def test_chunker_is_deterministic():
    text = "alpha\n\n" + ("beta " * 300) + "\n\ngamma"
    assert chunk_text(text) == chunk_text(text)


# --- fusion: agreement is evidence ------------------------------------------


def test_rrf_ranks_agreement_above_single_method_wins():
    """Chunk 7 is rank 2 in BOTH lists; chunk 1 is rank 1 in one list
    only. Fusion must put the agreed-upon chunk first — that property IS
    the reason hybrid search exists."""
    vector_and_keyword = [
        [(1, [1]), (7, [2])],   # sub-query A: 1 first, 7 second
        [(9, [1]), (7, [2])],   # sub-query B: 9 first, 7 second
    ]
    fused = reciprocal_rank_fusion(vector_and_keyword)
    assert fused[0] == 7, f"agreement should win: {fused}"


def test_rrf_two_method_agreement_outweighs_one_first_place():
    """Chunk 5 appears at rank 3 (vector) AND rank 4 (keyword); chunk 2
    is #1 by one method only. With k=60, 1/63 + 1/64 > 1/61 — two-method
    agreement legitimately beats a single first place. (This test's
    first version asserted the opposite and failed: the failure was the
    lesson, so it is preserved here as the correct expectation.)"""
    fused = reciprocal_rank_fusion([[(5, [3, 4]), (2, [1])]])
    assert set(fused) == {5, 2} and fused[0] == 5


# --- the budget: rank order, hard ceiling ------------------------------------


def test_budget_trim_respects_the_ceiling_and_rank_order(monkeypatch):
    monkeypatch.setattr(settings, "rag_context_token_budget", 100)
    chunks = [
        SimpleNamespace(id=n, content="x" * 240)  # 60 tokens each
        for n in range(5)
    ]
    kept, used = trim_to_budget(chunks)
    assert [c.id for c in kept] == [0], "only the top-ranked chunk fits"
    assert used <= 100


def test_budget_always_keeps_at_least_the_top_chunk(monkeypatch):
    monkeypatch.setattr(settings, "rag_context_token_budget", 10)
    kept, _ = trim_to_budget([SimpleNamespace(id=1, content="y" * 400)])
    assert len(kept) == 1, "an oversized top chunk is kept, not starved"


# --- citations: the model claims, the for-loop verifies ----------------------


def test_fabricated_citation_is_detected():
    sent = [SimpleNamespace(id=101), SimpleNamespace(id=102)]
    assert validate_citations([101, 999], sent) == [999]
    assert validate_citations([101, 102], sent) == []


# --- the pipeline end to end, real database ---------------------------------


@needs_db
def test_ask_retrieves_answers_and_cites_from_the_real_database(monkeypatch):
    """Seed two jobs with one distinguishing fact, match a candidate to
    both, ask the question, and demand: the answer cites a chunk from
    the RIGHT job, the citation is among sent chunks (deterministically
    re-verified), and the metadata tells the retrieval story."""
    from fastapi.testclient import TestClient

    from app.ingestion.pipeline import embed_missing_jobs, store
    from app.ingestion.sources import RawPosting
    from app.main import app
    from tests.test_step7_auth import cleanup_users, sign_in

    jobs = [
        RawPosting(
            source="itest12", external_id=f"r-{n}", company=c, title=t,
            location=None, url="http://example.com", posted_at=None,
            description=d,
        )
        for n, (c, t, d) in enumerate([
            ("OfficeCo", "Python Engineer",
             "python sql docker services. This is an on-site position in the "
             "Toronto office, five days per week."),
            ("RemoteCo", "Python Engineer",
             "python sql docker services. This is a fully remote work position; "
             "the team works distributed across time zones."),
        ])
    ]

    async def seed():
        from app.db import engine

        await engine.dispose(close=False)
        await store(jobs)
        await embed_missing_jobs()

    asyncio.run(seed())
    asyncio.run(__import__("app.db", fromlist=["engine"]).engine.dispose(close=False))

    try:
        with TestClient(app) as client:
            sign_in(client, "rag@test.example")
            cid = client.post(
                "/candidates",
                files={"file": ("r.txt", b"python sql docker engineer", "text/plain")},
                data={"consent": "true"},
            ).json()["id"]
            job = client.post(f"/candidates/{cid}/match").json()
            for _ in range(40):
                state = client.get(
                    f"/candidates/{cid}/match-jobs/{job['match_job_id']}"
                ).json()
                if state["status"] in ("done", "failed"):
                    break
            assert state["status"] == "done"

            response = client.post(
                f"/candidates/{cid}/ask",
                json={"question": "Which job allows remote work?"},
            )
            assert response.status_code == 200
            body = response.json()

            assert body["citations"], f"no citations: {body}"
            cited_jobs = {
                citation["text"] for citation in body["citations"]
            }
            assert any("remote" in text.lower() for text in cited_jobs), (
                f"citations do not include the remote posting: {body}"
            )
            assert body["meta"]["sub_queries"], "rewriting must have produced queries"
            assert body["meta"]["chunks_sent"] >= 1

            # Validation guards over HTTP: empty and oversized questions.
            assert client.post(
                f"/candidates/{cid}/ask", json={"question": ""}
            ).status_code == 400
            assert client.post(
                f"/candidates/{cid}/ask", json={"question": "x" * 1001}
            ).status_code == 400
    finally:
        cleanup_users("rag@test.example")

        async def cleanup():
            connection = await asyncpg.connect(DATABASE_URL, timeout=2)
            try:
                await connection.execute(
                    "DELETE FROM jobs WHERE source = 'itest12'"
                )  # chunks follow via CASCADE
            finally:
                await connection.close()

        asyncio.run(cleanup())


@needs_db
def test_chunks_table_exists():
    async def check():
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            return await connection.fetchval(
                "SELECT to_regclass('public.job_chunks')"
            )
        finally:
            await connection.close()

    assert asyncio.run(check()) == "job_chunks"
