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
    names the latest one. Step 7's migration is "0006".)
    """
    assert _fetch_one("SELECT version_num FROM alembic_version") == "0006"


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


def test_candidates_and_matches_tables_exist():
    """Step 4's tables were created by migration 0003."""
    assert _fetch_one("SELECT to_regclass('public.candidates')") == "candidates"
    assert _fetch_one("SELECT to_regclass('public.matches')") == "matches"


def test_agent_layer_tables_exist():
    """Step 5's tables were created by migration 0004."""
    for table in ("tailored_resumes", "chat_sessions", "chat_messages"):
        assert _fetch_one(f"SELECT to_regclass('public.{table}')") == table


def test_eval_tables_exist():
    """Step 6's tables were created by migration 0005."""
    for table in ("eval_runs", "eval_case_results"):
        assert _fetch_one(f"SELECT to_regclass('public.{table}')") == table


def test_account_tables_exist():
    """Step 7's tables were created by migration 0006."""
    for table in ("users", "login_tokens", "auth_sessions"):
        assert _fetch_one(f"SELECT to_regclass('public.{table}')") == table


def test_full_product_flow_upload_match_rank_in_fake_mode():
    """The whole Step 4 loop, end to end, through the real machinery:
    seed jobs -> embed -> upload a resume -> parse (fake) -> match ->
    ranked results -> every AI call recorded. Free (fake mode), real
    database, cleans up after itself.
    """
    import asyncio as aio

    from fastapi.testclient import TestClient

    from app.ingestion.pipeline import embed_missing_jobs, store
    from app.ingestion.sources import RawPosting
    from app.main import app

    jobs = [
        RawPosting(
            source="itest", external_id=f"flow-{n}", company="FlowCo",
            title=title, location=None, url="http://example.com",
            posted_at=None,
            description=description,
        )
        for n, (title, description) in enumerate([
            ("Python Backend Engineer", "python sql docker apis backend services"),
            ("Machine Learning Engineer", "python models training pipelines docker"),
            ("Marketing Manager", "campaigns brand social media budgets"),
        ])
    ]

    async def seed():
        from app.db import engine

        await engine.dispose(close=False)  # discard pools from earlier loops
        await store(jobs)
        return await embed_missing_jobs()

    embedded = aio.run(seed())
    assert embedded >= 3  # ours, plus any strays lacking vectors

    # Discard the seeding loop's connection pool before the web client
    # opens its own loop — otherwise the recorder inside the app borrows a
    # dead-loop connection, its protective catch swallows the write (the
    # product survives, as designed), and the metrics row we assert on is
    # silently missing. Observed exactly once, then pinned here forever.
    async def fresh_pool():
        from app.db import engine

        await engine.dispose(close=False)

    aio.run(fresh_pool())

    candidate_id = None
    try:
        with TestClient(app) as client:
            from tests.test_step7_auth import sign_in

            sign_in(client, "flow@test.example")
            # Upload: a .txt resume, parsed by the (fake-mode) agent.
            upload = client.post(
                "/candidates",
                files={"file": ("resume.txt", b"python sql docker engineer", "text/plain")},
            )
            assert upload.status_code == 200
            candidate_id = upload.json()["id"]
            assert upload.json()["profile"]["skills"]  # a profile exists

            # Match: both stages run; fake scorer explains the top ones.
            summary = client.post(f"/candidates/{candidate_id}/match")
            assert summary.status_code == 200
            body = summary.json()
            assert body["jobs_considered"] >= 3
            assert body["explained_by_ai"] >= 1
            assert body["degraded_to_vector_only"] == 0

            # Rank: explained matches first, scores present and ordered.
            matches = client.get(f"/candidates/{candidate_id}/matches").json()
            assert len(matches) >= 3
            explained = [m for m in matches if m["llm_score"] is not None]
            assert explained, "top matches must carry AI analysis"
            scores = [m["llm_score"] for m in explained]
            assert scores == sorted(scores, reverse=True)
            assert explained[0]["analysis"]["strengths"]

            # Unknown candidate: honest 404, not a crash.
            assert client.post("/candidates/999999/match").status_code == 404
            # And a stranger (no session at all): 401 before anything runs.
            from fastapi.testclient import TestClient as TC

            with TC(app) as stranger:
                assert stranger.get(f"/candidates/{candidate_id}").status_code == 401

            # Every paid-call kind appeared in the flight recorder.
            agents = {row["agent"] for row in client.get("/metrics").json()}
            assert {"resume_parser", "match_scorer", "embedder"} <= agents
    finally:

        async def cleanup():
            connection = await asyncpg.connect(DATABASE_URL, timeout=2)
            try:
                await connection.execute(
                    "DELETE FROM users WHERE email = 'flow@test.example'"
                )  # candidates and matches follow via ON DELETE CASCADE
                await connection.execute("DELETE FROM jobs WHERE source = 'itest'")
            finally:
                await connection.close()

        aio.run(cleanup())


def test_storing_the_same_batch_twice_adds_nothing_the_second_time():
    """Idempotency, proven against the real database: the first store adds
    rows; the identical second store adds zero — the Step 1 constraint
    plus "on conflict do nothing", working exactly as promised. The test
    cleans up after itself."""
    import asyncio as aio

    from app.ingestion.pipeline import store
    from app.ingestion.sources import RawPosting

    batch = [
        RawPosting(
            source="itest",
            external_id=f"idem-{n}",
            company="ITestCo",
            title="Engineer",
            location=None,
            description="x",
            url="http://example.com",
            posted_at=None,
        )
        for n in range(3)
    ]
    # Both stores run inside ONE event loop — the same lesson as the
    # gateway test above: the application's pooled connections belong to
    # the loop that created them; a second asyncio.run() is a second loop.
    async def run_both_and_cleanup() -> tuple[int, int]:
        # One more layer of the same onion: earlier tests may have used the
        # application's engine in THEIR loops, leaving pooled connections
        # that belong to loops which no longer exist. dispose(close=False)
        # says: "discard the pool; do not try to close those connections —
        # their loop is gone." SQLAlchemy provides it for exactly this
        # situation. Fresh loop, fresh pool, deterministic test.
        from app.db import engine

        await engine.dispose(close=False)
        try:
            first = await store(batch)
            second = await store(batch)
            return first, second
        finally:
            connection = await asyncpg.connect(DATABASE_URL, timeout=2)
            try:
                await connection.execute("DELETE FROM jobs WHERE source = 'itest'")
            finally:
                await connection.close()

    first, second = aio.run(run_both_and_cleanup())
    assert first == 3   # first time: three new rows
    assert second == 0  # second time: nothing new — idempotency, proven


def test_agent_layer_flow_tailor_and_coach_in_fake_mode():
    """Step 5 end to end through the real machinery: tailor a resume for
    a real stored job; hold a two-turn coach conversation that uses tools
    (including the tailor sub-agent); verify the transcript, its per-turn
    metadata, and the security boundary. Free, real database, cleans up.
    """
    import asyncio as aio

    from fastapi.testclient import TestClient

    from app.ingestion.pipeline import embed_missing_jobs, store
    from app.ingestion.sources import RawPosting
    from app.main import app

    jobs = [
        RawPosting(
            source="itest5", external_id=f"a-{n}", company="AgentCo",
            title=title, location=None, url="http://example.com",
            posted_at=None, description=desc,
        )
        for n, (title, desc) in enumerate([
            ("Python Platform Engineer", "python sql docker platform services"),
            ("Data Engineer", "python sql pipelines warehouses"),
        ])
    ]

    async def seed():
        from app.db import engine

        await engine.dispose(close=False)
        await store(jobs)
        await embed_missing_jobs()

    aio.run(seed())

    async def fresh_pool():
        from app.db import engine

        await engine.dispose(close=False)

    aio.run(fresh_pool())

    candidate_id = None
    try:
        with TestClient(app) as client:
            from tests.test_step7_auth import sign_in

            sign_in(client, "agentflow@test.example")
            candidate_id = client.post(
                "/candidates",
                files={"file": ("r.txt", b"python sql docker engineer", "text/plain")},
            ).json()["id"]
            client.post(f"/candidates/{candidate_id}/match")

            # Direct tailoring: pick the top match's real job_id.
            top_job = client.get(f"/candidates/{candidate_id}/matches").json()[0]
            tailored = client.post(
                f"/candidates/{candidate_id}/jobs/{top_job['job_id']}/tailor"
            )
            assert tailored.status_code == 200
            content = tailored.json()["content"]
            assert content["gaps_not_claimed"] and content["change_log"]

            # Coach turn 1: it must LOOK, then answer from the data.
            turn1 = client.post(
                f"/candidates/{candidate_id}/chat",
                json={"message": "What are my top matches?"},
            ).json()
            session_id = turn1["session_id"]
            assert "list_matches" in turn1["tools_used"]
            assert turn1["timed_out"] is False
            assert "AgentCo" in turn1["reply"] or "Engineer" in turn1["reply"]

            # Coach turn 2, same session: delegate to the tailor sub-agent.
            before = len(client.get(f"/candidates/{candidate_id}/tailored").json())
            turn2 = client.post(
                f"/candidates/{candidate_id}/chat",
                json={"message": "Please tailor my resume for the top match.",
                      "session_id": session_id},
            ).json()
            assert "tailor_resume" in turn2["tools_used"]
            after = len(client.get(f"/candidates/{candidate_id}/tailored").json())
            assert after == before + 1  # the sub-agent really saved a row

            # The transcript: 4 messages, assistant rows carrying metadata.
            transcript = client.get(
                f"/candidates/{candidate_id}/sessions/{session_id}/messages"
            ).json()
            assert [m["role"] for m in transcript] == [
                "user", "assistant", "user", "assistant"
            ]
            assert transcript[1]["meta"]["tools_used"] == turn1["tools_used"]
            assert transcript[1]["meta"]["latency_ms"] >= 0

            # The security boundary: another candidate cannot enter this
            # session — and is told "not found", not "forbidden".
            pass  # the cross-user session attack now lives in
            # tests/test_step7_auth.py's hostile suite, which covers every
            # candidate-scoped route — including this one — as a signed-in
            # intruder.

            # Supervisor validation over HTTP: empty message -> 400.
            assert client.post(
                f"/candidates/{candidate_id}/chat", json={"message": ""}
            ).status_code == 400

            # Every agent of the step appeared in the flight recorder.
            agents = {row["agent"] for row in client.get("/metrics").json()}
            assert {"resume_tailor", "coach"} <= agents
    finally:

        async def cleanup():
            connection = await asyncpg.connect(DATABASE_URL, timeout=2)
            try:
                await connection.execute(
                    "DELETE FROM users WHERE email = 'agentflow@test.example'"
                )
                await connection.execute("DELETE FROM jobs WHERE source = 'itest5'")
            finally:
                await connection.close()

        aio.run(cleanup())


def test_eval_run_records_results_and_attributes_its_own_cost():
    """One real fake-mode eval run through the real machinery: an
    eval_runs row, per-case results, and — the run-attribution promise —
    agent_runs rows carrying this run's id, whose summed cost equals the
    run's recorded cost. Cleans up after itself."""
    import asyncio as aio

    from evals.run import persist_run, run_match_suite

    async def one_run():
        from app.db import engine
        from app.llm import current_run_id

        await engine.dispose(close=False)
        run_id = "itest-run-0001"
        token = current_run_id.set(run_id)
        try:
            results = await run_match_suite()
            total, passed, cost = await persist_run(
                run_id, "match", "integration test", results
            )
        finally:
            current_run_id.reset(token)
        return run_id, total, passed, cost

    run_id, total, passed, cost = aio.run(one_run())
    try:
        assert total >= 4 and passed == total  # 3 cases + the ranking pair
        assert cost == 0.0  # fake mode is free, provably

        attributed = _fetch_one(
            f"SELECT count(*) FROM agent_runs WHERE run_id = '{run_id}'"
        )
        assert attributed >= 3  # one scorer call per golden case, tagged

        stored = _fetch_one(
            f"SELECT passed FROM eval_runs WHERE id = '{run_id}'"
        )
        assert stored == passed

        case_rows = _fetch_one(
            f"SELECT count(*) FROM eval_case_results WHERE run_id = '{run_id}'"
        )
        assert case_rows == total
    finally:

        async def cleanup():
            connection = await asyncpg.connect(DATABASE_URL, timeout=2)
            try:
                await connection.execute(
                    f"DELETE FROM eval_runs WHERE id = '{run_id}'"
                )  # case results cascade
                await connection.execute(
                    f"DELETE FROM agent_runs WHERE run_id = '{run_id}'"
                )
            finally:
                await connection.close()

        aio.run(cleanup())
