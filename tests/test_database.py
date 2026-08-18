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
    """
    assert _fetch_one("SELECT version_num FROM alembic_version") == "0001"


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
