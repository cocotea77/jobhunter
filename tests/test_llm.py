"""Tests for the AI gateway (app/llm.py) — no database, no network, instant.

The technique, same as test_health.py: we replace the parts that touch the
outside world with stand-ins. Here two seams exist on purpose:

  - record_run(...)        (writes to the database)   -> captured in a list
  - _call_real_model(...)  (calls the real AI service) -> scripted answers

Everything between those seams — fake mode, cost arithmetic, schema
validation, the retry-once-then-fail-loudly policy, failure recording —
is the gateway's real logic, and it runs for real in these tests.

(The database half of the story — that a row truly lands in agent_runs —
is covered in tests/test_database.py against the real Postgres.)
"""

import asyncio

import pytest
from pydantic import BaseModel

from app import llm
from app.config import settings


class Captured:
    """Collects every record_run call so tests can inspect it."""

    def __init__(self):
        self.runs: list[dict] = []

    async def record(self, **fields):
        self.runs.append(fields)


@pytest.fixture()
def captured(monkeypatch):
    """Replace the database write with an in-memory capture, and force
    fake mode on regardless of the developer's local .env."""
    capture = Captured()
    monkeypatch.setattr(llm, "record_run", capture.record)
    monkeypatch.setattr(settings, "fake_ai", True)
    return capture


class Analysis(BaseModel):
    """A small schema for the structured-output tests."""

    summary: str
    word_count: int


# --- fake mode -------------------------------------------------------------


def test_fake_mode_returns_the_declared_answer(captured):
    answer = asyncio.run(
        llm.generate_text(
            agent="test_agent",
            prompt="Say hello.",
            fake_response="Hello from fake mode.",
        )
    )
    assert answer == "Hello from fake mode."


def test_fake_mode_records_one_run_with_zero_cost(captured):
    asyncio.run(
        llm.generate_text(agent="test_agent", prompt="Hi.", fake_response="Hi.")
    )
    assert len(captured.runs) == 1
    run = captured.runs[0]
    assert run["agent"] == "test_agent"
    assert run["model"] == "fake"
    assert run["success"] is True
    assert run["cost_usd"] == 0.0
    assert run["latency_ms"] >= 0


# --- structured output and validation --------------------------------------


def test_structured_answer_is_validated_and_typed(captured):
    result = asyncio.run(
        llm.generate_structured(
            agent="test_agent",
            prompt="Analyze.",
            schema=Analysis,
            fake_response={"summary": "Fine.", "word_count": 2},
        )
    )
    assert isinstance(result, Analysis)
    assert result.summary == "Fine."
    assert result.word_count == 2


def test_code_fence_decoration_is_stripped():
    fenced = '```json\n{"summary": "ok", "word_count": 1}\n```'
    assert llm._strip_code_fences(fenced) == '{"summary": "ok", "word_count": 1}'


# --- the retry-once-then-fail-loudly policy --------------------------------


class ScriptedModel:
    """Stands in for the real AI service, answering from a script."""

    def __init__(self, answers: list[str]):
        self.answers = list(answers)
        self.calls = 0

    async def call(self, system, prompt, max_tokens):
        self.calls += 1
        return self.answers.pop(0), 10, 5


def test_malformed_then_valid_answer_succeeds_via_one_retry(captured, monkeypatch):
    """First answer is broken JSON; the retry corrects it. The user sees
    only success — and both round trips were recorded."""
    scripted = ScriptedModel(
        ["this is not json at all", '{"summary": "Fixed.", "word_count": 1}']
    )
    monkeypatch.setattr(settings, "fake_ai", False)
    monkeypatch.setattr(llm, "_call_real_model", scripted.call)

    result = asyncio.run(
        llm.generate_structured(
            agent="test_agent",
            prompt="Analyze.",
            schema=Analysis,
            fake_response={"summary": "unused", "word_count": 0},
        )
    )
    assert result.summary == "Fixed."
    assert scripted.calls == 2
    assert len(captured.runs) == 2


def test_two_malformed_answers_fail_loudly(captured, monkeypatch):
    """Two bad answers -> a clear error, never silent garbage."""
    scripted = ScriptedModel(["nonsense", "still nonsense"])
    monkeypatch.setattr(settings, "fake_ai", False)
    monkeypatch.setattr(llm, "_call_real_model", scripted.call)

    with pytest.raises(RuntimeError, match="invalid structured output twice"):
        asyncio.run(
            llm.generate_structured(
                agent="test_agent",
                prompt="Analyze.",
                schema=Analysis,
                fake_response={"summary": "unused", "word_count": 0},
            )
        )
    assert scripted.calls == 2


# --- failures are recorded, then re-raised ---------------------------------


def test_a_failed_call_is_recorded_with_the_error(captured, monkeypatch):
    async def exploding_model(system, prompt, max_tokens):
        raise ConnectionError("service unreachable")

    monkeypatch.setattr(settings, "fake_ai", False)
    monkeypatch.setattr(llm, "_call_real_model", exploding_model)

    with pytest.raises(ConnectionError):
        asyncio.run(
            llm.generate_text(agent="test_agent", prompt="Hi.", fake_response="x")
        )

    assert len(captured.runs) == 1
    run = captured.runs[0]
    assert run["success"] is False
    assert "ConnectionError" in run["error"]


# --- cost arithmetic --------------------------------------------------------


def test_cost_is_computed_from_the_price_table():
    # 1,000,000 input tokens at $3 + 1,000,000 output tokens at $15 = $18.
    assert llm.estimate_cost_usd("claude-sonnet-4-6", 1_000_000, 1_000_000) == 18.0


def test_unknown_models_are_priced_pessimistically():
    """When in doubt, overestimate cost — never underestimate it."""
    unknown = llm.estimate_cost_usd("mystery-model", 1_000_000, 1_000_000)
    assert unknown == 18.0  # the most expensive known rate
