"""Golden cases: inputs with KNOWN correct properties.

A golden case is not "an example" — it is a promise: given exactly these
inputs, a healthy agent's output must have these properties. The cases
below were designed in pairs and extremes on purpose:

- a STRONG match and a WEAK match for the same candidate, so the suite
  can assert the relationship between them (strong must outscore weak) —
  a check that stays meaningful even in fake mode, because our fake
  scorer is word overlap and the real model should agree directionally;
- a tailoring case whose posting demands a skill the resume clearly
  LACKS, so faithfulness has something concrete to catch: that skill
  appearing anywhere except gaps_not_claimed is fabrication.

Cases live in JSON files (evals/golden/) so adding one is an editable,
reviewable, one-file Pull Request — the intended way this suite grows,
especially with incidents from real users later (Step 10: every incident
ends as a case here).
"""

import json
import pathlib

from pydantic import BaseModel, Field

from app.resume import CandidateProfile

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"


class MatchCase(BaseModel):
    """One matching golden case."""

    case_id: str
    profile: CandidateProfile
    job_title: str
    job_company: str
    job_description: str
    # Deterministic expectations (checked in every mode):
    min_strengths: int = 1
    min_gaps: int = 0
    # Real-mode-only expectations (the model's judgment, not the plumbing):
    real_score_at_least: int | None = None
    real_score_at_most: int | None = None
    # Pairing for the relative check: "strong" and "weak" cases with the
    # same pair_key are asserted as strong.score > weak.score.
    pair_key: str | None = None
    pair_role: str | None = Field(default=None, description="'strong' or 'weak'")


class TailoringCase(BaseModel):
    """One tailoring golden case."""

    case_id: str
    profile: CandidateProfile
    raw_resume_text: str
    job_title: str
    job_company: str
    job_description: str
    # A skill the posting wants that the resume clearly LACKS. Real-mode
    # faithfulness: it must appear in gaps_not_claimed and must NOT be
    # claimed in summary/skills/bullets.
    forbidden_claim: str | None = None


def load_match_cases() -> list[MatchCase]:
    data = json.loads((GOLDEN_DIR / "match_cases.json").read_text())
    return [MatchCase.model_validate(item) for item in data]


def load_tailoring_cases() -> list[TailoringCase]:
    data = json.loads((GOLDEN_DIR / "tailoring_cases.json").read_text())
    return [TailoringCase.model_validate(item) for item in data]
