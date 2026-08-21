"""Step 8 tests: the survival mechanisms, each proven.

The pattern throughout: create the dangerous situation for real (a user
over quota, a burned budget, an account full of data) and prove the
mechanism holds — then prove ordinary life continues around it (browsing
works during a budget stop; other users are untouched by one user's
quota). Safety that only refuses is half-built; safety that refuses
PRECISELY is the product.
"""

import asyncio
import pathlib

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.test_step7_auth import cleanup_users, sign_in

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


pytestmark = pytest.mark.skipif(
    not _database_is_running(),
    reason="database is not running — start it with: docker compose up -d",
)


def upload(client: TestClient, consent: bool = True):
    data = {"consent": "true"} if consent else {}
    return client.post(
        "/candidates",
        files={"file": ("r.txt", b"python sql docker engineer", "text/plain")},
        data=data,
    )


def sql(query: str):
    async def go():
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            return await connection.fetchval(query)
        finally:
            await connection.close()

    return asyncio.run(go())


# --- consent ----------------------------------------------------------------


def test_upload_without_consent_is_refused_before_processing():
    try:
        with TestClient(app) as client:
            sign_in(client, "consent@test.example")
            refused = upload(client, consent=False)
            assert refused.status_code == 400
            assert "consent" in refused.json()["detail"]

            accepted = upload(client, consent=True)
            assert accepted.status_code == 200
            consent_at = sql(
                f"SELECT consent_at FROM candidates WHERE id = {accepted.json()['id']}"
            )
            assert consent_at is not None  # the agreement has a timestamp
    finally:
        cleanup_users("consent@test.example")


# --- quotas ------------------------------------------------------------------


def test_quota_allows_the_limit_and_refuses_the_next(monkeypatch):
    monkeypatch.setattr(settings, "quota_matching_runs_per_day", 2)
    try:
        with TestClient(app) as client:
            sign_in(client, "quota@test.example")
            cid = upload(client).json()["id"]

            assert client.post(f"/candidates/{cid}/match").status_code == 200
            assert client.post(f"/candidates/{cid}/match").status_code == 200
            third = client.post(f"/candidates/{cid}/match")
            assert third.status_code == 429
            assert "midnight UTC" in third.json()["detail"]
    finally:
        cleanup_users("quota@test.example")


def test_one_users_quota_does_not_touch_another(monkeypatch):
    monkeypatch.setattr(settings, "quota_matching_runs_per_day", 1)
    try:
        with TestClient(app) as heavy:
            sign_in(heavy, "heavy@test.example")
            cid = upload(heavy).json()["id"]
            assert heavy.post(f"/candidates/{cid}/match").status_code == 200
            assert heavy.post(f"/candidates/{cid}/match").status_code == 429

        from app.db import engine

        asyncio.run(engine.dispose(close=False))

        with TestClient(app) as light:
            sign_in(light, "light@test.example")
            cid2 = upload(light).json()["id"]
            # Heavy's exhaustion is heavy's alone.
            assert light.post(f"/candidates/{cid2}/match").status_code == 200
    finally:
        cleanup_users("heavy@test.example", "light@test.example")


def test_quota_rows_reset_by_day_not_by_amnesia():
    """Yesterday's counter row simply does not match CURRENT_DATE — the
    reset needs no scheduled job, no cleanup, no code: the day column IS
    the reset."""

    async def plant_yesterday(user_id: int):
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            await connection.execute(
                "INSERT INTO usage_counters (user_id, action, day, count) VALUES "
                f"({user_id}, 'matching_runs', CURRENT_DATE - 1, 999)"
            )
        finally:
            await connection.close()

    try:
        with TestClient(app) as client:
            sign_in(client, "yesterday@test.example")
            user_id = client.get("/me").json()["id"]
            asyncio.run(plant_yesterday(user_id))
            cid = upload(client).json()["id"]
            # 999 uses YESTERDAY; today starts at zero.
            assert client.post(f"/candidates/{cid}/match").status_code == 200
    finally:
        cleanup_users("yesterday@test.example")


# --- the budget stop ---------------------------------------------------------


def burn_budget() -> None:
    """Simulate a spent day: one recorded call whose cost equals the cap.
    (The stop reads agent_runs — so the test speaks agent_runs.)"""
    async def go():
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            await connection.execute(
                "INSERT INTO agent_runs (agent, model, latency_ms, input_tokens, "
                "output_tokens, cost_usd, success) VALUES "
                f"('budget_test', 'fake', 1, 0, 0, {settings.max_daily_spend_usd}, true)"
            )
        finally:
            await connection.close()

    asyncio.run(go())


def unburn_budget() -> None:
    async def go():
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            await connection.execute(
                "DELETE FROM agent_runs WHERE agent = 'budget_test'"
            )
        finally:
            await connection.close()

    asyncio.run(go())


def test_budget_stop_pauses_ai_but_not_browsing():
    try:
        with TestClient(app) as client:
            sign_in(client, "budget@test.example")
            cid = upload(client).json()["id"]
            assert client.post(f"/candidates/{cid}/match").status_code == 200

            burn_budget()

            # AI actions: politely paused, 503, with the reason.
            paused = client.post(f"/candidates/{cid}/match")
            assert paused.status_code == 503
            assert "budget" in paused.json()["detail"].lower()
            assert client.post(
                f"/candidates/{cid}/chat", json={"message": "hi"}
            ).status_code == 503

            # Browsing computed results: untouched. Read-only, not dead.
            assert client.get(f"/candidates/{cid}/matches").status_code == 200
            assert client.get(f"/candidates/{cid}").status_code == 200

            # The operator sees it at a glance.
            health = client.get("/health").json()
            assert health["budget"]["exhausted"] is True
    finally:
        unburn_budget()
        cleanup_users("budget@test.example")


def test_budget_state_is_reported_when_healthy():
    with TestClient(app) as client:
        budget = client.get("/health").json()["budget"]
        assert budget["exhausted"] is False
        assert budget["cap_usd"] == settings.max_daily_spend_usd


# --- delete-my-account: the promise, counted ---------------------------------


def test_delete_me_removes_every_row_everywhere():
    email = "erase@test.example"
    with TestClient(app) as client:
        sign_in(client, email)
        user_id = client.get("/me").json()["id"]
        cid = upload(client).json()["id"]
        client.post(f"/candidates/{cid}/match")
        client.post(f"/candidates/{cid}/chat", json={"message": "hello"})

        # The data exists — establish that first, or the proof is hollow.
        assert sql(f"SELECT count(*) FROM candidates WHERE user_id = {user_id}") == 1
        assert sql(
            "SELECT count(*) FROM chat_sessions cs JOIN candidates c ON "
            f"cs.candidate_id = c.id WHERE c.user_id = {user_id}"
        ) == 1

        assert client.delete("/me").json()["deleted"] is True

    # Every table, counted. This block IS the privacy page's promise.
    assert sql(f"SELECT count(*) FROM users WHERE id = {user_id}") == 0
    assert sql(f"SELECT count(*) FROM candidates WHERE user_id = {user_id}") == 0
    assert sql(f"SELECT count(*) FROM auth_sessions WHERE user_id = {user_id}") == 0
    assert sql(f"SELECT count(*) FROM login_tokens WHERE user_id = {user_id}") == 0
    assert sql(f"SELECT count(*) FROM usage_counters WHERE user_id = {user_id}") == 0
    orphans = sql(
        "SELECT count(*) FROM matches m LEFT JOIN candidates c ON "
        "m.candidate_id = c.id WHERE c.id IS NULL"
    )
    assert orphans == 0  # no match survived its candidate
    stray_messages = sql(
        "SELECT count(*) FROM chat_messages cm LEFT JOIN chat_sessions cs ON "
        "cm.session_id = cs.id WHERE cs.id IS NULL"
    )
    assert stray_messages == 0


# --- log hygiene: resume text never meets a logger ---------------------------


def test_no_logging_statement_touches_resume_text():
    """A static promise: nowhere in the application code does a print or
    logger line mention raw resume text. Crude on purpose — a reviewer
    can hold the whole rule in their head, and it fails loudly at the
    exact line if someone adds convenient debug logging of a resume."""
    app_dir = pathlib.Path(__file__).parent.parent / "app"
    offenders = []
    for path in app_dir.rglob("*.py"):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            logging_line = "print(" in line or "logger." in line or "logging." in line
            if logging_line and ("raw_text" in line or "resume_text" in line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, f"resume content in logging statements: {offenders}"


def test_privacy_page_exists_and_names_the_delete_promise():
    with TestClient(app) as client:
        text = client.get("/privacy").text
        assert "DELETE /me" in text and "never appears in our logs" in text
