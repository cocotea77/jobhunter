"""The ingestion pipeline: fetch → capture failures → dedupe → store.

The promises this module makes, each enforced somewhere you can point at:

1. ONE DEAD SOURCE NEVER KILLS THE RUN. Every source is fetched inside
   its own try/except; a failure becomes an entry in `source_errors` in
   the report, and the run continues. (A nightly refresh over hundreds of
   boards WILL meet dead boards — that is normal weather, not a crash.)
2. DUPLICATES ARE IMPOSSIBLE, NOT MERELY AVOIDED. The final guarantee is
   the database's unique rule on (source, external_id) from Step 1: the
   insert says "on conflict, do nothing", so re-fetching the same posting
   can never create a second row — enforced by Postgres, not by our code
   remembering to check.
3. THE RUN REPORTS HONESTLY. fetched / new / skipped_existing /
   source_errors — numbers you can verify with your own SQL, and the
   idempotency proof (run twice → new: 0) falls straight out of them.
"""

import asyncio

import httpx
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.config import settings
from app.db import session_factory
from app.embeddings import embed_texts
from app.ingestion.sources import (
    RawPosting,
    fetch_greenhouse,
    fetch_lever,
    fetch_remotive,
)
from app.models import Job


class IngestRequest(BaseModel):
    """What to fetch. All fields optional — fetch as much or little as asked."""

    greenhouse: list[str] = []  # board tokens, e.g. ["stripe", "anthropic"]
    lever: list[str] = []  # company names, e.g. ["plaid"]
    remotive_search: str | None = None  # e.g. "machine learning engineer"


class IngestReport(BaseModel):
    """The honest summary of one run."""

    fetched: int  # postings received from all sources together
    new: int  # rows actually added to the database
    skipped_existing: int  # postings we already had (the constraint at work)
    source_errors: list[str]  # one entry per failed source — captured, not fatal
    embedded: int = 0  # postings given meaning vectors this run (Step 4)


def deduplicate(postings: list[RawPosting]) -> list[RawPosting]:
    """Remove repeats WITHIN this batch, keeping the first of each.

    Why this exists when the database already refuses duplicates: Postgres
    rejects a batch that conflicts with ITSELF ("cannot affect row a second
    time") rather than quietly keeping one copy. Cross-run duplicates are
    the database's job; within-batch duplicates are ours.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[RawPosting] = []
    for posting in postings:
        key = (posting.source, posting.external_id)
        if key not in seen:
            seen.add(key)
            unique.append(posting)
    return unique


async def store(postings: list[RawPosting]) -> int:
    """Store a batch, letting the Step 1 constraint do its work.

    The insert says "on conflict with our unique rule, do nothing":
    re-fetching the same posting can never create a second row — enforced
    by Postgres itself. The return value is how many rows were actually
    added; the caller derives skipped_existing from the difference.
    """
    if not postings:
        return 0
    statement = (
        pg_insert(Job)
        .values([posting.model_dump() for posting in postings])
        .on_conflict_do_nothing(constraint="uq_jobs_source_external_id")
    )
    async with session_factory() as session:
        result = await session.execute(statement)
        await session.commit()
        return result.rowcount or 0


async def embed_missing_jobs(batch_size: int = 100) -> int:
    """Embed every job that has no meaning vector yet, in polite batches.

    What gets embedded is the title plus the start of the description —
    the part of a posting that says what the job IS. (Embedding models
    read a limited window; the opening of a posting earns its place.)
    """
    from app.models import Job  # local import avoids a circular import

    total = 0
    while True:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    select(Job.id, Job.title, Job.description)
                    .where(Job.embedding.is_(None))
                    .limit(batch_size)
                )
            ).all()
            if not rows:
                return total
            texts = [f"{row.title}\n{row.description[:4000]}" for row in rows]
            vectors = await embed_texts(texts)
            for row, vector in zip(rows, vectors):
                await session.execute(
                    update(Job).where(Job.id == row.id).values(embedding=vector)
                )
            await session.commit()
            total += len(rows)


async def ingest(request: IngestRequest) -> IngestReport:
    """Run one complete ingestion: every requested source, one report."""

    # Build the list of jobs-to-do: (label for error messages, fetch call).
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = []
        labels = []
        for token in request.greenhouse:
            labels.append(f"greenhouse:{token}")
            tasks.append(fetch_greenhouse(client, token))
        for company in request.lever:
            labels.append(f"lever:{company}")
            tasks.append(fetch_lever(client, company))
        if request.remotive_search:
            labels.append(f"remotive:{request.remotive_search}")
            tasks.append(fetch_remotive(client, request.remotive_search))

        # A politeness valve: at most N sources in flight at once.
        gate = asyncio.Semaphore(settings.ingestion_concurrency)

        async def guarded(task):
            async with gate:
                return await task

        # gather(..., return_exceptions=True) is promise #1 in code form:
        # instead of the first failure cancelling everything, each task
        # returns either its postings or its exception, and we sort them.
        results = await asyncio.gather(
            *(guarded(task) for task in tasks), return_exceptions=True
        )

    postings: list[RawPosting] = []
    source_errors: list[str] = []
    for label, result in zip(labels, results):
        if isinstance(result, BaseException):
            source_errors.append(f"{label}: {type(result).__name__}: {result}")
        else:
            postings.extend(result)

    fetched = len(postings)
    postings = deduplicate(postings)
    new = await store(postings)

    # Step 4: give meaning vectors to every posting that lacks one. This
    # covers the rows just stored AND any older rows that were never
    # embedded (self-healing by construction: the question is "who is
    # missing a vector?", not "what did this run add?").
    embedded = await embed_missing_jobs()

    return IngestReport(
        fetched=fetched,
        new=new,
        skipped_existing=len(postings) - new,
        source_errors=source_errors,
        embedded=embedded,
    )
