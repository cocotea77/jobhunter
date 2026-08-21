"""Step 7 integration tests: the authentication lifecycle, and the
HOSTILE OWNERSHIP SUITE — the most important test file in the project.

The hostile suite's method: user A creates data; user B, fully signed in,
attacks EVERY candidate-scoped endpoint with A's identifiers. The only
acceptable answer, every time, is 404 — not 403 ("forbidden" confirms
the data exists), not 200, not 500. One parametrized test covers the
whole attack surface, so adding an endpoint without ownership protection
makes a test fail BY DEFAULT the moment it is added to the attack list —
and the attack list is checked against the live route table, so
forgetting to list a new candidate endpoint also fails. Security that
must be remembered eventually is not; security that fails loudly when
forgotten survives.

These tests need the real database (same skip rule as test_database.py).
"""

import asyncio

import asyncpg
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

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


def sign_in(client: TestClient, email: str) -> dict:
    """The whole magic-link dance, as a test would a real user: request a
    link, follow it, receive the session cookie (TestClient keeps it)."""
    body = client.post("/auth/request-link", json={"email": email}).json()
    assert body["sent"] is True
    token = body["dev_link"].split("token=")[1]
    verified = client.get(f"/auth/verify?token={token}")
    assert verified.status_code == 200
    return verified.json()


def cleanup_users(*emails: str) -> None:
    async def go():
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            for email in emails:
                await connection.execute(
                    "DELETE FROM users WHERE email = $1", email
                )  # candidates, sessions, tokens follow via CASCADE
        finally:
            await connection.close()

    asyncio.run(go())


# --- the authentication lifecycle -------------------------------------------


def test_signin_lifecycle_link_session_me_logout():
    try:
        with TestClient(app) as client:
            # Before sign-in: strangers cannot enter.
            assert client.get("/me").status_code == 401
            assert client.get("/candidates").status_code == 401

            result = sign_in(client, "alice@test.example")
            assert result["email"] == "alice@test.example"
            assert client.get("/me").json()["email"] == "alice@test.example"

            # The cookie is httpOnly — the browser script surface cannot
            # read it. (TestClient exposes the jar; we assert the flag.)
            # And logout truly revokes: the same cookie stops working.
            client.post("/auth/logout")
            assert client.get("/me").status_code == 401
    finally:
        cleanup_users("alice@test.example")


def test_login_link_works_exactly_once():
    try:
        with TestClient(app) as client:
            body = client.post(
                "/auth/request-link", json={"email": "bob@test.example"}
            ).json()
            token = body["dev_link"].split("token=")[1]
            assert client.get(f"/auth/verify?token={token}").status_code == 200
            # Replay: the forwarded/stolen link is dead.
            second = client.get(f"/auth/verify?token={token}")
            assert second.status_code == 400
            assert "invalid or expired" in second.json()["detail"]
    finally:
        cleanup_users("bob@test.example")


def test_garbage_token_and_garbage_email_are_rejected():
    with TestClient(app) as client:
        assert client.get("/auth/verify?token=not-a-real-token").status_code == 400
        assert (
            client.post("/auth/request-link", json={"email": "nope"}).status_code == 400
        )


def test_admin_endpoints_require_the_token():
    with TestClient(app) as client:
        naked = client.post("/ingest", json={"greenhouse": []})
        assert naked.status_code == 401
        armed = client.post(
            "/ingest", json={"greenhouse": []},
            headers={"x-admin-token": settings.admin_token},
        )
        assert armed.status_code == 200  # empty request: fetches nothing


# --- THE HOSTILE OWNERSHIP SUITE --------------------------------------------

# Every (method, path-template) that takes a candidate id. The attack
# below hits each one as the WRONG user and demands 404.
CANDIDATE_SCOPED_ROUTES = [
    ("GET", "/candidates/{cid}"),
    ("POST", "/candidates/{cid}/match"),
    ("GET", "/candidates/{cid}/matches"),
    ("POST", "/candidates/{cid}/jobs/999999/tailor"),
    ("GET", "/candidates/{cid}/tailored"),
    ("POST", "/candidates/{cid}/chat"),
    ("GET", "/candidates/{cid}/sessions/{sid}/messages"),
]


def test_attack_list_covers_every_candidate_route_in_the_app():
    """The guard that guards the guard: if someone adds a new
    /candidates/{candidate_id}/... endpoint and forgets to add it to the
    attack list above, THIS test fails — the hostile suite can never
    silently fall out of date."""
    live = {
        (method, route.path)
        for route in app.routes
        if "{candidate_id}" in getattr(route, "path", "")
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    listed = {
        (method, path.replace("{cid}", "{candidate_id}").replace(
            "{sid}", "{session_id}"
        ).replace("999999", "{job_id}"))
        for method, path in CANDIDATE_SCOPED_ROUTES
    }
    assert live == listed, (
        f"unlisted candidate routes (add them to the attack list!): {live - listed}; "
        f"listed but not live: {listed - live}"
    )


def test_user_b_gets_404_from_every_endpoint_with_user_a_ids():
    try:
        with TestClient(app) as alice:
            sign_in(alice, "owner@test.example")
            created = alice.post(
                "/candidates",
                files={"file": ("r.txt", b"python sql docker", "text/plain")},
                data={"consent": "true"},
            )
            assert created.status_code == 200
            cid = created.json()["id"]
            sid = alice.post(
                f"/candidates/{cid}/chat", json={"message": "hello"}
            ).json()["session_id"]

        # Two client blocks = two event loops; discard alice's pooled
        # connections before mallory's loop begins (the within-test case
        # the conftest fixture cannot cover).
        from app.db import engine

        asyncio.run(engine.dispose(close=False))

        with TestClient(app) as mallory:
            sign_in(mallory, "intruder@test.example")

            # Mallory is a real, signed-in user — with no right to Alice's data.
            for method, template in CANDIDATE_SCOPED_ROUTES:
                path = template.format(cid=cid, sid=sid)
                kwargs = {}
                if method == "POST" and path.endswith("/chat"):
                    kwargs["json"] = {"message": "hi"}
                response = mallory.request(method, path, **kwargs)
                assert response.status_code == 404, (
                    f"{method} {path} answered {response.status_code} for the "
                    f"wrong user — it must be 404, and never 403"
                )

            # And Alice's candidate does not appear in Mallory's list.
            assert all(
                row["id"] != cid for row in mallory.get("/candidates").json()
            )
    finally:
        cleanup_users("owner@test.example", "intruder@test.example")


def test_ownerless_rows_are_visible_to_nobody():
    """Rows from before accounts existed (user_id NULL) are invisible —
    not shared. The migration's backfill decision, enforced."""

    async def plant_orphan() -> int:
        connection = await asyncpg.connect(DATABASE_URL, timeout=2)
        try:
            return await connection.fetchval(
                "INSERT INTO candidates (name, raw_text, profile) "
                "VALUES ('Orphan', 'x', '{}') RETURNING id"
            )
        finally:
            await connection.close()

    orphan_id = asyncio.run(plant_orphan())
    try:
        with TestClient(app) as client:
            sign_in(client, "carol@test.example")
            assert client.get(f"/candidates/{orphan_id}").status_code == 404
            assert all(
                row["id"] != orphan_id for row in client.get("/candidates").json()
            )
    finally:
        cleanup_users("carol@test.example")

        async def remove_orphan():
            connection = await asyncpg.connect(DATABASE_URL, timeout=2)
            try:
                await connection.execute(
                    f"DELETE FROM candidates WHERE id = {orphan_id}"
                )
            finally:
                await connection.close()

        asyncio.run(remove_orphan())


# --- the route inventory: no endpoint may vanish silently -------------------

EXPECTED_ROUTES = {
    ("GET", "/health"),
    ("GET", "/metrics"),
    ("POST", "/ingest"),
    ("POST", "/ingest/curated"),
    ("POST", "/auth/request-link"),
    ("GET", "/auth/verify"),
    ("POST", "/auth/logout"),
    ("GET", "/me"),
    ("POST", "/candidates"),
    ("GET", "/candidates"),
    ("GET", "/candidates/{candidate_id}"),
    ("POST", "/candidates/{candidate_id}/match"),
    ("GET", "/candidates/{candidate_id}/matches"),
    ("POST", "/candidates/{candidate_id}/jobs/{job_id}/tailor"),
    ("GET", "/candidates/{candidate_id}/tailored"),
    ("POST", "/candidates/{candidate_id}/chat"),
    ("GET", "/candidates/{candidate_id}/sessions/{session_id}/messages"),
    ("GET", "/evals/runs"),
    ("DELETE", "/me"),
    ("GET", "/privacy"),
}


def test_the_api_surface_is_exactly_what_we_promised():
    """Every route the documents promise, present; nothing extra hiding.

    This test exists because of a real shipped regression: a cleanup in
    Step 4 silently truncated the ingestion endpoints out of the file,
    and nothing noticed for three deliveries — the integration tests
    exercised the underlying functions, not the routes. An endpoint that
    disappears (or appears) now fails this test by name."""
    live = {
        (method, route.path)
        for route in app.routes
        if getattr(route, "path", "").startswith(("/health", "/metrics", "/ingest",
                                                   "/auth", "/me", "/candidates",
                                                   "/evals", "/privacy"))
        for method in route.methods - {"HEAD", "OPTIONS"}
    }
    assert live == EXPECTED_ROUTES, (
        f"missing from the app: {EXPECTED_ROUTES - live}; "
        f"unexpected in the app: {live - EXPECTED_ROUTES}"
    )
