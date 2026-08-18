"""Tests for the health endpoint.

Step 1 makes the health endpoint depend on the database — which raises a
question every professional test suite must answer: how do we test both
outcomes ("database fine" and "database down") quickly, on any machine,
without needing a real database in one state or the other?

The answer is a standard technique: in these tests we REPLACE the real
database check with a stand-in that returns whatever state the test needs.
This keeps the tests instant and Docker-free, and lets us test the failure
path — which would otherwise require breaking a real database on purpose.

(The real database check is still tested against a real database — in
tests/test_database.py, which runs whenever the database is up, and always
in Continuous Integration.)
"""

from fastapi.testclient import TestClient

# Import the module itself under a clear alias, AND the application object
# inside it. (Importing both as "app..." would make one name shadow the
# other — a real bug this file originally had, caught by running it.)
from app import main as main_module

client = TestClient(main_module.app)


async def pretend_database_is_fine() -> str:
    return "ok"


async def pretend_database_is_down() -> str:
    return "unreachable (ConnectionRefusedError)"


def test_healthy_when_database_is_reachable(monkeypatch):
    """Database fine -> 200, status "ok", and full identity reported."""
    monkeypatch.setattr(main_module, "database_status", pretend_database_is_fine)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["app"] == "JobHunter"
    assert "version" in body
    assert body["environment"] in {"development", "test", "production"}


def test_degraded_when_database_is_down(monkeypatch):
    """Database down -> 503 and an honest explanation in the body.

    The 503 status code is the contract with the outside world: hosting
    platforms and uptime monitors read the code, not the text. A health
    endpoint that answers 200 while its database is down would silence
    every alarm designed to protect us.
    """
    monkeypatch.setattr(main_module, "database_status", pretend_database_is_down)

    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert "unreachable" in body["database"]
