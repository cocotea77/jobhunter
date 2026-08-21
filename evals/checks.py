"""The two layers of judgment: deterministic checks, then AI judges.

LAYER ONE — deterministic checks. Plain code, plain booleans, run in
EVERY mode. No AI judges AI here: "the score is inside 0-100", "the
tailored bullets do not claim the forbidden skill", "every claimed skill
exists in the source resume text" are facts a for-loop can verify.
Booleans over vibes: a check either names what failed or it passes.

LAYER TWO — AI judges (real mode only). Some qualities need reading
comprehension: is each claimed strength actually grounded in the
profile? Is the score calibrated to the evidence? A judge model audits
the agent's output against the inputs and answers in BOOLEANS WITH
EVIDENCE — the schema forbids a vibe like "seems fine". Judges go
through the same gateway as everything else, so judge cost and latency
land in agent_runs, tagged with the eval run.

Every check returns (check_name, passed, detail) so a failing run tells
you exactly which promise broke, per case.
"""

from pydantic import BaseModel, Field

from app.agents.tailor import TailoredContent
from app.config import settings
from app.llm import generate_structured
from app.matching import MatchAnalysis
from app.resume import profile_card
from evals.cases import MatchCase, TailoringCase

Check = tuple[str, bool, str]


# --- layer one: deterministic ----------------------------------------------


def check_match(case: MatchCase, analysis: MatchAnalysis) -> list[Check]:
    checks: list[Check] = [
        ("score_in_range", 0 <= analysis.score <= 100, f"score={analysis.score}"),
        (
            "verdict_present",
            bool(analysis.verdict.strip()),
            "verdict must not be empty",
        ),
    ]
    if not settings.fake_ai:
        # Richness expectations audit the MODEL's output, not the plumbing:
        # fake mode's canned analysis always has one strength and one gap,
        # so these checks only mean something against a real model.
        checks.append(
            (
                "min_strengths",
                len(analysis.strengths) >= case.min_strengths,
                f"{len(analysis.strengths)} strengths, expected >= {case.min_strengths}",
            )
        )
        checks.append(
            (
                "min_gaps",
                len(analysis.gaps) >= case.min_gaps,
                f"{len(analysis.gaps)} gaps, expected >= {case.min_gaps}",
            )
        )
        # Absolute score expectations audit the MODEL's judgment, so they
        # only mean something when a real model produced the score.
        if case.real_score_at_least is not None:
            checks.append(
                (
                    "real_score_at_least",
                    analysis.score >= case.real_score_at_least,
                    f"score={analysis.score}, expected >= {case.real_score_at_least}",
                )
            )
        if case.real_score_at_most is not None:
            checks.append(
                (
                    "real_score_at_most",
                    analysis.score <= case.real_score_at_most,
                    f"score={analysis.score}, expected <= {case.real_score_at_most}",
                )
            )
    return checks


def check_pair_ranking(
    strong_case: MatchCase,
    strong: MatchAnalysis,
    weak_case: MatchCase,
    weak: MatchAnalysis,
) -> Check:
    """The relative check — meaningful in EVERY mode: for the same
    candidate, the obviously-strong job must outscore the obviously-weak
    one. Fake mode's word-overlap scorer satisfies it for the right
    reason; a real model that fails it is broken in a way no absolute
    threshold would catch as cleanly."""
    return (
        f"ranking:{strong_case.pair_key}:strong_above_weak",
        strong.score > weak.score,
        f"strong={strong.score} ({strong_case.case_id}) vs "
        f"weak={weak.score} ({weak_case.case_id})",
    )


def check_tailoring(case: TailoringCase, content: TailoredContent) -> list[Check]:
    checks: list[Check] = [
        (
            "change_log_present",
            bool(content.change_log),
            "change_log must be non-empty",
        ),
        (
            "has_bullets_and_skills",
            bool(content.experience_bullets) and bool(content.skills_ordered),
            "bullets and skills must be non-empty",
        ),
    ]
    if not settings.fake_ai:
        # Faithfulness by tracing — the manual audit of Steps 4-5, now a
        # for-loop: every claimed skill must exist in the source resume.
        source = case.raw_resume_text.lower()
        invented = [s for s in content.skills_ordered if s.lower() not in source]
        checks.append(
            (
                "skills_trace_to_resume",
                not invented,
                f"skills absent from the resume text: {invented}" if invented else "ok",
            )
        )
        if case.forbidden_claim:
            forbidden = case.forbidden_claim.lower()
            claimed_in = [
                where
                for where, text in [
                    ("summary", content.target_summary),
                    ("skills", " ".join(content.skills_ordered)),
                    ("bullets", " ".join(content.experience_bullets)),
                    ("keywords", " ".join(content.keywords_covered)),
                ]
                if forbidden in text.lower()
            ]
            checks.append(
                (
                    "forbidden_claim_not_made",
                    not claimed_in,
                    f"'{case.forbidden_claim}' claimed in: {claimed_in}"
                    if claimed_in
                    else "ok",
                )
            )
            checks.append(
                (
                    "forbidden_claim_confessed",
                    any(forbidden in gap.lower() for gap in content.gaps_not_claimed),
                    f"'{case.forbidden_claim}' should appear in gaps_not_claimed",
                )
            )
    return checks


# --- layer two: AI judges (real mode only) ----------------------------------


class MatchJudgement(BaseModel):
    """Booleans with evidence — the schema forbids vibes."""

    strengths_grounded: bool = Field(
        description="True only if EVERY strength cites something explicitly "
        "present in the candidate profile"
    )
    score_calibrated: bool = Field(
        description="True only if the score honestly reflects the evidence "
        "in the analysis itself"
    )
    evidence: str = Field(description="Quote the exact phrases that decided you")


JUDGE_MATCH_SYSTEM = """You audit a match analysis produced by another AI.
You are not asked whether the analysis is nice — you are asked two
factual questions, answered strictly from the texts provided. When in
doubt, answer False and say why in evidence."""


async def judge_match(case: MatchCase, analysis: MatchAnalysis) -> list[Check]:
    judgement = await generate_structured(
        agent="judge_match",
        system=JUDGE_MATCH_SYSTEM,
        prompt=(
            f"CANDIDATE PROFILE:\n{profile_card(case.profile)}\n\n"
            f"JOB: {case.job_title} at {case.job_company}\n"
            f"POSTING:\n{case.job_description}\n\n"
            f"THE ANALYSIS UNDER AUDIT:\n{analysis.model_dump_json(indent=2)}"
        ),
        schema=MatchJudgement,
        fake_response={
            "strengths_grounded": True,
            "score_calibrated": True,
            "evidence": "fake mode: judges are not meaningful without a real model",
        },
    )
    return [
        ("judge:strengths_grounded", judgement.strengths_grounded, judgement.evidence),
        ("judge:score_calibrated", judgement.score_calibrated, judgement.evidence),
    ]


class TailoringJudgement(BaseModel):
    every_fact_traces: bool = Field(
        description="True only if every employer, technology, and number in "
        "the tailored content exists in the original resume text"
    )
    gaps_are_honest: bool = Field(
        description="True only if gaps_not_claimed honestly lists posting "
        "requirements the resume does not show"
    )
    evidence: str = Field(description="Quote the exact phrases that decided you")


JUDGE_TAILOR_SYSTEM = """You audit a tailored resume against the ORIGINAL
resume it was built from. Fabrication — any fact in the output absent
from the original — is the failure you exist to catch. When in doubt,
answer False and say why in evidence."""


async def judge_tailoring(case: TailoringCase, content: TailoredContent) -> list[Check]:
    judgement = await generate_structured(
        agent="judge_tailoring",
        system=JUDGE_TAILOR_SYSTEM,
        prompt=(
            f"ORIGINAL RESUME:\n{case.raw_resume_text}\n\n"
            f"TARGET POSTING ({case.job_title} at {case.job_company}):\n"
            f"{case.job_description}\n\n"
            f"THE TAILORED CONTENT UNDER AUDIT:\n{content.model_dump_json(indent=2)}"
        ),
        schema=TailoringJudgement,
        fake_response={
            "every_fact_traces": True,
            "gaps_are_honest": True,
            "evidence": "fake mode: judges are not meaningful without a real model",
        },
    )
    return [
        ("judge:every_fact_traces", judgement.every_fact_traces, judgement.evidence),
        ("judge:gaps_are_honest", judgement.gaps_are_honest, judgement.evidence),
    ]
