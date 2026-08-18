"""Integration tests: talk to the REAL database.

The other test files avoid the database on purpose, so they run anywhere
in milliseconds. This file is the opposite: it proves the real machinery
works end to end — the connection, the applied migrations, and the rules
the database itself enforces.

If the database is not running, these tests are SKIPPED with a message
telling you how to start it (they neither pass nor fail — pytest reports
them as "skipped" and says why). In Continuous Integration the database is
always running, so there they always execute. Nothing important is ever
skipped where it counts.
"""

import asyncio

import asyncpg
import pytest

from app.config import settings

# asyncpg (used directly here for simplicity) wants the address without
# the "+asyncpg" marker that SQLAlchemy uses.
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


# Applies to every test in this file.
pytestmark = pytest.mark.skipif(
    not _database_is_running(),
    reason="database is not running — start it with: docker compose up -d",
)


def _fetch_one(query: str):
    async def go():
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            return await connection.fetchval(query)
        finally:
            await connection.close()

    return asyncio.run(go())


def test_can_reach_the_database():
    """The most basic promise: we can connect and get an answer."""
    assert _fetch_one("SELECT 1") == 1


def test_migrations_have_been_applied():
    """Alembic records the current migration in a table of its own.

    If this fails, the database exists but `alembic upgrade head` has not
    been run against it — the exact mistake this test exists to catch.
    (This assertion changes in every step that adds a migration: it always
    names the latest one. Step 2's migration is "0002".)
    """
    assert _fetch_one("SELECT version_num FROM alembic_version") == "0002"


def test_jobs_table_exists():
    assert _fetch_one("SELECT to_regclass('public.jobs')") == "jobs"


def test_pgvector_extension_is_active():
    """Proves our infrastructure choice (a pgvector-capable Postgres)
    was honored — long before Step 4 actually needs it."""
    assert _fetch_one("SELECT count(*) FROM pg_extension WHERE extname = 'vector'") == 1


def test_database_refuses_duplicate_postings():
    """The unique rule on (source, external_id) is enforced BY POSTGRES.

    We insert the same posting twice inside a transaction that is always
    rolled back (so the test leaves no trace), and require the second
    insert to be rejected by the database itself. This is the guarantee
    Step 3's ingestion will rely on: duplicates are impossible, not merely
    avoided.
    """

    async def go() -> None:
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            transaction = connection.transaction()
            await transaction.start()
            try:
                insert = (
                    "INSERT INTO jobs (source, external_id, company, title, "
                    "description, url) "
                    "VALUES ('test', 'dup-1', 'TestCo', 'Engineer', 'x', 'http://x')"
                )
                await connection.execute(insert)
                with pytest.raises(asyncpg.UniqueViolationError):
                    await connection.execute(insert)
            finally:
                await transaction.rollback()
        finally:
            await connection.close()

    asyncio.run(go())


def test_agent_runs_table_exists():
    """Step 2's flight-recorder table was created by migration 0002."""
    assert _fetch_one("SELECT to_regclass('public.agent_runs')") == "agent_runs"


def test_gateway_writes_a_real_row_and_metrics_reports_it():
    """End to end through the real machinery: a fake-mode gateway call must
    produce a real row in agent_runs, and /metrics must aggregate it.

    (The unit tests in test_llm.py replace the database write; this test is
    the other half of the promise — the write itself works.)
    """
    from fastapi.testclient import TestClient

    from app.main import app

    before = _fetch_one("SELECT count(*) FROM agent_runs WHERE agent = 'demo'")

    # The "with" matters: it keeps ONE event loop alive for both requests.
    # Without it, each request gets its own loop, and the application's
    # pooled database connections — created in the first request's loop —
    # explode with "Event loop is closed" in the second. A real bug this
    # test originally had, caught by running it. Remember the shape of
    # that error message; you will meet it again in async Python.
    with TestClient(app) as client:
        response = client.post("/demo/ai", json={"text": "Hello gateway."})
        assert response.status_code == 200
        assert set(response.json()) == {"summary", "tone", "word_count"}

        metrics = client.get("/metrics").json()

    after = _fetch_one("SELECT count(*) FROM agent_runs WHERE agent = 'demo'")
    assert after == before + 1

    demo_rows = [row for row in metrics if row["agent"] == "demo"]
    assert len(demo_rows) == 1
    assert demo_rows[0]["calls"] >= 1
    assert demo_rows[0]["total_cost_usd"] == 0.0  # fake mode is free
