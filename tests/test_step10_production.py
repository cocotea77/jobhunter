"""Step 10 tests: production readiness, verified before production exists.

A deploy cannot be fully tested from a laptop — but the PROMISES the
deploy relies on can be, and that is what this file does: the tripwires
that refuse dangerous production configurations, the monitoring that
must initialize cleanly with and without its DSN, the dev-only
conveniences that must vanish in production, and the deploy recipe's
one non-negotiable ordering (migrate, THEN serve) pinned as text so a
careless edit cannot silently reverse it.
"""

import asyncio
import pathlib

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app, init_monitoring
from tests.test_step7_auth import cleanup_users

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


# --- the production tripwires ------------------------------------------------


@needs_db
def test_production_refuses_signin_without_an_email_provider(monkeypatch):
    """Console mode prints sign-in links (credentials!) into the log.
    Fine on a laptop; a leak in production — so production refuses."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "resend_api_key", "")
    with TestClient(app) as client:
        response = client.post(
            "/auth/request-link", json={"email": "trip@test.example"}
        )
        assert response.status_code == 503
        assert "RESEND_API_KEY" in response.json()["detail"]
    cleanup_users("trip@test.example")


@needs_db
def test_production_refuses_the_development_admin_token(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "admin_token", "dev-admin-token")
    with TestClient(app) as client:
        response = client.post(
            "/ingest",
            json={"greenhouse": []},
            headers={"x-admin-token": "dev-admin-token"},
        )
        assert response.status_code == 503
        assert "ADMIN_TOKEN" in response.json()["detail"]


@needs_db
def test_dev_link_never_appears_in_production(monkeypatch):
    """The development convenience must vanish where it would be a leak:
    in production the sign-in link travels ONLY by email."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "resend_api_key", "configured")

    async def email_goes_out(email: str, link: str) -> None:
        pass  # the provider call, stubbed — its absence is what we test

    import app.main as main_module

    monkeypatch.setattr(main_module, "send_login_email", email_goes_out)
    try:
        with TestClient(app) as client:
            body = client.post(
                "/auth/request-link", json={"email": "prodlink@test.example"}
            ).json()
            assert body["sent"] is True
            assert "dev_link" not in body
    finally:
        cleanup_users("prodlink@test.example")


@needs_db
def test_session_cookie_is_secure_outside_development(monkeypatch):
    """Outside development the cookie must carry Secure (HTTPS-only) —
    asserted on the actual Set-Cookie header a sign-in produces."""
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "resend_api_key", "configured")

    captured = {}

    async def email_goes_out(email: str, link: str) -> None:
        captured["token"] = link.split("token=")[1]

    import app.main as main_module

    monkeypatch.setattr(main_module, "send_login_email", email_goes_out)
    try:
        with TestClient(app) as client:
            client.post(
                "/auth/request-link", json={"email": "secure@test.example"}
            )
            response = client.get(f"/auth/verify?token={captured['token']}")
            cookie_header = response.headers["set-cookie"]
            assert "Secure" in cookie_header
            assert "HttpOnly" in cookie_header
    finally:
        cleanup_users("secure@test.example")


# --- monitoring --------------------------------------------------------------


def test_monitoring_is_a_no_op_without_a_dsn(monkeypatch):
    monkeypatch.setattr(settings, "sentry_dsn", "")
    init_monitoring()  # must simply not raise


def test_monitoring_initializes_with_a_dsn(monkeypatch):
    """A syntactically valid DSN initializes the client without network
    traffic (events are sent asynchronously later, and there are none)."""
    monkeypatch.setattr(
        settings, "sentry_dsn", "https://examplekey@o0.ingest.sentry.io/0"
    )
    init_monitoring()  # must not raise


# --- the deploy recipe's promises, pinned as text ----------------------------


ROOT = pathlib.Path(__file__).parent.parent


def test_start_script_migrates_before_serving():
    """The one ordering the whole deploy relies on. Pinned so that a
    future edit reversing the lines fails a named test, not a deploy."""
    script = (ROOT / "start.sh").read_text()
    assert script.index("alembic upgrade head") < script.index("uvicorn"), (
        "start.sh must run migrations BEFORE starting the server"
    )
    assert "set -e" in script, (
        "start.sh must stop on the first error, or a failed migration "
        "would be followed by a server start against the wrong schema"
    )


def test_dockerfile_ships_migrations_and_the_start_script():
    dockerfile = (ROOT / "Dockerfile").read_text()
    for needed in ("COPY migrations", "COPY alembic.ini", "COPY start.sh"):
        assert needed in dockerfile, f"Dockerfile is missing: {needed}"
    assert "tests" in (ROOT / ".dockerignore").read_text(), (
        "tests do not belong in the production image"
    )


def test_nightly_refresh_workflow_is_scheduled_and_admin_authenticated():
    workflow = (ROOT / ".github" / "workflows" / "refresh-jobs.yml").read_text()
    assert "schedule:" in workflow and "cron:" in workflow
    assert "x-admin-token" in workflow and "PROD_ADMIN_TOKEN" in workflow
    assert "workflow_dispatch" in workflow  # hand-pressable for the runbook
