"""Tests for ingestion — no real network, using recorded response shapes.

The technique, one more time: replace the part that touches the outside
world with a stand-in. Here the stand-in is a pretend web server holding
RECORDED real answers — each sample below is the documented shape the
real source returns, written down once so the parsing logic can be tested
forever, offline, in milliseconds.

Honest scope note: these tests prove our parsing of the RECORDED shapes.
If a source changes its shape someday, these tests will still pass while
live fetching fails — which is why the runbook's live checkpoints and
scripts/check_boards.py exist. Recorded tests and live checks together
cover what neither covers alone.

(The database half — real inserts, real idempotency — is in
tests/test_database.py against real Postgres.)
"""

import asyncio

import httpx
import pytest

from app.ingestion import pipeline
from app.ingestion.pipeline import IngestRequest, deduplicate, ingest
from app.ingestion.sources import (
    RawPosting,
    fetch_greenhouse,
    fetch_lever,
    fetch_remotive,
    html_to_text,
)

# --- recorded response shapes (what each source really returns) ------------

GREENHOUSE_SAMPLE = {
    "jobs": [
        {
            "id": 4011001,
            "title": "Software Engineer, Platform",
            "location": {"name": "San Francisco, CA"},
            "content": "&lt;p&gt;Build &lt;b&gt;great&lt;/b&gt; systems.&lt;/p&gt;",
            "absolute_url": "https://boards.greenhouse.io/example/jobs/4011001",
            "updated_at": "2026-07-01T12:00:00-04:00",
        },
        {
            "id": 4011002,
            "title": "Data Engineer",
            "location": None,
            "content": "<p>Pipelines.</p>",
            "absolute_url": "https://boards.greenhouse.io/example/jobs/4011002",
        },
    ]
}

LEVER_SAMPLE = [
    {
        "id": "a1b2c3d4-0000-1111-2222-333344445555",
        "text": "Machine Learning Engineer",
        "categories": {"location": "Remote — US"},
        "description": "<div>Train and ship models.</div>",
        "hostedUrl": "https://jobs.lever.co/example/a1b2c3d4",
        "createdAt": 1750000000000,
    }
]

REMOTIVE_SAMPLE = {
    "jobs": [
        {
            "id": 990001,
            "title": "AI Engineer",
            "company_name": "ExampleCo",
            "candidate_required_location": "Worldwide",
            "description": "<p>Agents, agents, agents.</p>",
            "url": "https://remotive.com/remote-jobs/software-dev/ai-engineer-990001",
            "publication_date": "2026-07-15T08:00:00",
        }
    ]
}


def client_answering(payload) -> httpx.AsyncClient:
    """A pretend web server: whatever address is asked, answer with payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def client_failing(status: int) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- parsing each source's shape -------------------------------------------


def test_greenhouse_parsing():
    postings = asyncio.run(fetch_greenhouse(client_answering(GREENHOUSE_SAMPLE), "example"))
    assert len(postings) == 2
    first = postings[0]
    assert first.source == "greenhouse"
    assert first.external_id == "4011001"  # numbers become strings, one shape
    assert first.company == "example"
    assert first.location == "San Francisco, CA"
    assert first.description == "Build great systems."  # unescaped, stripped, collapsed
    assert "<" not in first.description  # HTML is gone
    assert first.posted_at is not None
    # Missing optional fields must not crash — the second job has no
    # location and no date, which is normal on real boards.
    assert postings[1].location is None
    assert postings[1].posted_at is None


def test_lever_parsing_converts_millisecond_timestamps():
    postings = asyncio.run(fetch_lever(client_answering(LEVER_SAMPLE), "example"))
    assert len(postings) == 1
    posting = postings[0]
    assert posting.source == "lever"
    assert posting.title == "Machine Learning Engineer"
    assert posting.location == "Remote — US"
    assert posting.posted_at is not None
    assert posting.posted_at.year == 2025  # 1750000000000 ms ≈ June 2025


def test_remotive_parsing():
    postings = asyncio.run(fetch_remotive(client_answering(REMOTIVE_SAMPLE), "ai"))
    assert len(postings) == 1
    assert postings[0].company == "ExampleCo"
    assert postings[0].source == "remotive"


def test_a_bad_answer_raises_instead_of_returning_bad_data():
    """404 (board does not exist) must become a loud error the pipeline
    catches — never an empty 'success'."""
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(fetch_greenhouse(client_failing(404), "this-board-is-dead"))


def test_html_to_text_strips_markup():
    assert html_to_text("<p>Hello <b>world</b></p>") == "Hello world"
    assert html_to_text("<div><p>a</p><p>b</p></div>") == "a b"


# --- pipeline logic ---------------------------------------------------------


def make_posting(external_id: str, source: str = "test") -> RawPosting:
    return RawPosting(
        source=source,
        external_id=external_id,
        company="TestCo",
        title="Engineer",
        location=None,
        description="x",
        url="http://example.com",
        posted_at=None,
    )


def test_within_batch_duplicates_are_removed_keeping_the_first():
    batch = [make_posting("1"), make_posting("2"), make_posting("1")]
    unique = deduplicate(batch)
    assert [p.external_id for p in unique] == ["1", "2"]


def test_same_id_from_different_sources_is_not_a_duplicate():
    batch = [make_posting("1", source="greenhouse"), make_posting("1", source="lever")]
    assert len(deduplicate(batch)) == 2


def test_one_dead_source_is_captured_and_the_run_continues(monkeypatch):
    """Promise #1 in executable form: a failing source becomes an entry in
    source_errors; the healthy source's postings still arrive."""

    async def healthy(client, token):
        return [make_posting("ok-1", source="greenhouse")]

    async def dead(client, company):
        raise httpx.ConnectError("connection refused")

    captured_batches = []

    async def capture_store(postings):
        captured_batches.append(postings)
        return len(postings)

    async def no_embedding():
        return 0

    monkeypatch.setattr(pipeline, "fetch_greenhouse", healthy)
    monkeypatch.setattr(pipeline, "fetch_lever", dead)
    monkeypatch.setattr(pipeline, "store", capture_store)
    monkeypatch.setattr(pipeline, "embed_missing_jobs", no_embedding)

    report = asyncio.run(
        ingest(IngestRequest(greenhouse=["good-board"], lever=["dead-board"]))
    )

    assert report.fetched == 1
    assert len(report.source_errors) == 1
    assert "lever:dead-board" in report.source_errors[0]
    assert "ConnectError" in report.source_errors[0]
