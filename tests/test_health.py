"""Tests for the health endpoint.

What a test is, in plain words: a small program that uses the application
the way a user (or another computer) would, and then checks that the result
is exactly what we promised. If a future change breaks the promise, the
test fails immediately — on your machine and on GitHub's checking computer —
before the mistake can reach the live website.

The TestClient below is a pretend web browser: it calls the application
directly in memory, with no real network and no running server needed.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_answers_ok():
    """The health endpoint must answer successfully."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_reports_status_and_identity():
    """The answer must say the service is ok and identify itself.

    Monitoring tools will rely on these exact fields, so their names are a
    promise: changing them later must be a conscious, reviewed decision —
    and this test is what forces that conversation to happen.
    """
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["app"] == "JobPilot"
    assert "version" in body
    assert body["environment"] in {"development", "test", "production"}
