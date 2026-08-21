"""Tests for Step 5's agent layer — no database, no network, instant.

What is under test here is the MACHINERY of agency, with the model and
the tools stood in: the bounded loop, tool dispatch, error-as-data, the
iteration cap's honest fallback, and the supervisor's validation. The
full conversation against the real database lives in test_database.py.
"""

import asyncio

import pytest

from app import llm
from app.agents import coach
from app.agents.coach import run_coach_turn
from app.agents.orchestrator import handle_chat
from app.agents.tailor import TailoredContent, generate_tailored_content
from app.config import settings
from app.llm import ModelTurn, ToolCall
from app.resume import CandidateProfile


@pytest.fixture()
def counting_recorder(monkeypatch):
    """Fake mode on; gateway recording captured; returns the capture list."""
    runs = []

    async def capture(**fields):
        runs.append(fields)

    monkeypatch.setattr(llm, "record_run", capture)
    monkeypatch.setattr(settings, "fake_ai", True)

    # Step 8 put a budget check at the gateway's entrance; it reads the
    # database, and these are pure unit tests — stub it open.
    async def budget_is_fine():
        pass

    import app.safety

    monkeypatch.setattr(app.safety, "ensure_budget_available", budget_is_fine)
    return runs


PROFILE = CandidateProfile(
    name="Jane", headline="Backend engineer", skills=["python", "sql"],
    titles=["Software Engineer"], years_of_experience=4, summary="Builds services.",
)


# --- the tailor's honesty contract ------------------------------------------


def test_tailor_output_carries_the_honesty_fields(counting_recorder):
    content = asyncio.run(
        generate_tailored_content(PROFILE, "raw resume text", "ML Engineer", "Co", "desc")
    )
    assert isinstance(content, TailoredContent)
    assert content.gaps_not_claimed, "the gaps confession must never be omitted"
    assert content.change_log, "every change must be declared"


def test_tailor_schema_refuses_output_missing_the_confession():
    """The honesty rule lives in the schema — omitting gaps_not_claimed is
    a validation error, not a quiet degradation."""
    with pytest.raises(Exception):
        TailoredContent(
            target_summary="s", skills_ordered=["python"],
            experience_bullets=["b"], keywords_covered=["k"],
            change_log=["c"],  # gaps_not_claimed deliberately missing
        )


# --- the coach loop's machinery ---------------------------------------------


def fake_matches_tool(monkeypatch, calls):
    """Stand in the tool executor: records calls, returns one match."""

    async def stub(name, tool_input, candidate_id):
        calls.append((name, candidate_id))
        return {
            "matches": [
                {"job_id": 7, "title": "Python Engineer", "company": "DataCo",
                 "llm_score": 82, "vector_score": 0.31, "analysis": None}
            ]
        }

    monkeypatch.setattr(coach, "execute_tool", stub)


def test_coach_looks_before_answering(counting_recorder, monkeypatch):
    """'What are my matches?' -> tool first, then an answer built from the
    tool's result — two recorded round trips, one tool call."""
    calls = []
    fake_matches_tool(monkeypatch, calls)

    reply, tools_used = asyncio.run(
        run_coach_turn(1, [], "What are my top matches?")
    )

    assert tools_used == ["list_matches"]
    assert calls == [("list_matches", 1)]  # candidate_id came from the server
    assert "Python Engineer" in reply  # the answer cites the tool's data
    assert len(counting_recorder) == 2  # look, then answer — both measured


def test_iteration_cap_ends_the_loop_honestly(counting_recorder, monkeypatch):
    """A model that requests tools forever hits the cap and the user gets
    an honest fallback — never an infinite loop, never a crash."""

    def always_wants_tools(user_message, iteration, last_tool_result):
        call = ToolCall(id=f"loop_{iteration}", name="list_matches", input={})
        return ModelTurn(
            text="", tool_calls=[call], stop_reason="tool_use",
            raw_content=[{"type": "tool_use", "id": call.id,
                          "name": "list_matches", "input": {}}],
        )

    calls = []
    fake_matches_tool(monkeypatch, calls)
    monkeypatch.setattr(coach, "plan_fake_turn", always_wants_tools)

    reply, tools_used = asyncio.run(run_coach_turn(1, [], "hi"))

    assert len(tools_used) == settings.coach_max_iterations
    assert "step budget" in reply  # the honest fallback, not silence


def test_a_crashing_tool_becomes_data_not_a_crash(counting_recorder, monkeypatch):
    """Rule 3: the tool explodes; the conversation survives and ends with
    a reply. The failure travelled INTO the dialogue as {"error": ...}."""

    async def exploding_tool(name, tool_input, candidate_id):
        raise ConnectionError("database ran away")

    monkeypatch.setattr(coach, "execute_tool", exploding_tool)

    reply, tools_used = asyncio.run(
        run_coach_turn(1, [], "What are my top matches?")
    )

    assert tools_used == ["list_matches"]  # it tried
    assert reply  # and still answered — no exception escaped


# --- the supervisor's validation --------------------------------------------


def test_empty_message_is_rejected_before_any_work():
    with pytest.raises(ValueError, match="must not be empty"):
        asyncio.run(handle_chat(1, "   ", None))


def test_oversized_message_is_rejected_with_the_numbers():
    too_long = "x" * (settings.chat_max_message_chars + 1)
    with pytest.raises(ValueError, match="too long"):
        asyncio.run(handle_chat(1, too_long, None))
