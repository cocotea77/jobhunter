"""Tests for Step 6's harness — the machinery that judges the machinery.

A harness with untested logic would be a guard nobody guards: if the
faithfulness check cannot detect an invented skill, or the gate cannot
detect a regression, every green run is a false comfort. So the checks
and the gate are tested like any other production code — with cases
designed to FAIL, proving the teeth are real.
"""

import pytest

from app.agents.tailor import TailoredContent
from app.config import settings
from app.matching import MatchAnalysis
from evals.cases import (
    TailoringCase,
    load_match_cases,
    load_tailoring_cases,
)
from evals.checks import check_pair_ranking, check_tailoring
from evals.run import apply_gate


def analysis(score: int, strengths=None, gaps=None) -> MatchAnalysis:
    return MatchAnalysis(
        score=score, verdict="v",
        strengths=strengths or ["s"], gaps=gaps or ["g"],
    )

def test_empty_gaps_are_valid_when_case_has_no_missing_requirement(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)

    case = load_tailoring_cases()[1]  # straightforward_backend

    checks = check_tailoring(
        case,
        content(
            skills=["python", "postgresql", "docker"],
            bullets=["built python fastapi services"],
            gaps=[],
        ),
    )

    assert all(ok for _, ok, _ in checks), [
        check for check in checks if not check[1]
    ]

# --- the golden datasets themselves are validated data ----------------------


def test_golden_datasets_load_and_validate():
    matches, tailorings = load_match_cases(), load_tailoring_cases()
    assert len(matches) >= 3 and len(tailorings) >= 2
    roles = {c.pair_role for c in matches if c.pair_key == "backend"}
    assert roles == {"strong", "weak"}, "the ranking pair must be complete"


# --- the relative check ------------------------------------------------------


def test_ranking_check_passes_when_strong_outscores_weak():
    strong_case, weak_case = load_match_cases()[0], load_match_cases()[1]
    name, ok, detail = check_pair_ranking(
        strong_case, analysis(80), weak_case, analysis(30)
    )
    assert ok


def test_ranking_check_fails_when_inverted_and_names_the_evidence():
    strong_case, weak_case = load_match_cases()[0], load_match_cases()[1]
    name, ok, detail = check_pair_ranking(
        strong_case, analysis(30), weak_case, analysis(80)
    )
    assert not ok
    assert "strong=30" in detail and "weak=80" in detail


# --- faithfulness tracing detects fabrication (real-mode checks) ------------


FAITH_CASE = TailoringCase(
    case_id="t/unit",
    profile=load_tailoring_cases()[0].profile,
    raw_resume_text="python fastapi postgresql docker on aws",
    job_title="Platform Engineer",
    job_company="Co",
    job_description="python platform; kubernetes required",
    forbidden_claim="kubernetes",
)


def content(skills, bullets, gaps, keywords=None, summary="s") -> TailoredContent:
    return TailoredContent(
        target_summary=summary, skills_ordered=skills,
        experience_bullets=bullets, keywords_covered=keywords or ["python"],
        gaps_not_claimed=gaps, change_log=["c"],
    )


def test_faithfulness_catches_an_invented_skill(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)  # tracing is a real-mode check
    checks = dict(
        (name, (ok, detail))
        for name, ok, detail in check_tailoring(
            FAITH_CASE,
            content(
                skills=["python", "terraform"],  # terraform is NOT in the resume
                bullets=["built python services"],
                gaps=["kubernetes"],
            ),
        )
    )
    ok, detail = checks["skills_trace_to_resume"]
    assert not ok and "terraform" in detail


def test_forbidden_claim_is_caught_wherever_it_hides(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)
    checks = dict(
        (name, (ok, detail))
        for name, ok, detail in check_tailoring(
            FAITH_CASE,
            content(
                skills=["python"],
                bullets=["deployed kubernetes clusters"],  # the fabrication
                gaps=["nothing missing"],
            ),
        )
    )
    ok, detail = checks["forbidden_claim_not_made"]
    assert not ok and "bullets" in detail
    ok, _ = checks["forbidden_claim_confessed"]
    assert not ok  # and the confession is missing too


def test_honest_output_passes_all_faithfulness_checks(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)
    checks = check_tailoring(
        FAITH_CASE,
        content(
            skills=["python", "docker"],
            bullets=["built python fastapi services on aws"],
            gaps=["kubernetes (required by the posting, not on the resume)"],
        ),
    )
    assert all(ok for _, ok, _ in checks), [c for c in checks if not c[1]]


# --- the gate's mechanics ----------------------------------------------------


PASSING = [("x", True, "")]
FAILING = [("x", False, "boom")]


def test_gate_flags_only_previously_passing_cases(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", True)
    baseline = {"fake": {"a": True, "b": False}}
    results = {"a": FAILING, "b": FAILING, "c": FAILING}  # c is new
    regressions, available = apply_gate(results, baseline)
    assert available
    assert regressions == ["a"]  # b was known-failing; c is new — neither gates


def test_gate_is_clean_when_nothing_regressed(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", True)
    baseline = {"fake": {"a": True}}
    regressions, available = apply_gate({"a": PASSING, "new": FAILING}, baseline)
    assert available and regressions == []


def test_gate_declines_to_judge_without_a_baseline_for_this_mode(monkeypatch):
    monkeypatch.setattr(settings, "fake_ai", False)
    regressions, available = apply_gate({"a": FAILING}, {"fake": {"a": True}})
    assert not available  # a real-mode run cannot be judged by a fake baseline


def test_schema_rejects_a_vibes_only_judgement():
    """Judges must answer in booleans with evidence — the schema enforces it."""
    from evals.checks import MatchJudgement

    with pytest.raises(Exception):
        MatchJudgement(evidence="seems fine")  # missing the booleans
