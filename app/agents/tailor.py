"""The resume-tailoring agent: rewrite a resume TOWARD a job, honestly.

Tailoring is where an AI product faces its strongest temptation to lie:
the easiest way to "improve" a resume for a posting is to invent the
missing qualifications. This agent's defense is structural — the schema
itself demands two confessions:

- gaps_not_claimed: requirements the candidate genuinely lacks, which
  the tailored resume deliberately does NOT pretend to cover.
- change_log: every change made, so nothing is edited invisibly.

A model that must list what it did not claim is being audited by its own
output format. In Step 6, an automated judge reads these fields against
the stored raw resume and fails any tailoring whose claims do not trace
to the source — the fields below are that judge's evidence, designed in
before the judge exists.

`generate_tailored_content` is a pure function of its inputs (like
score_match), so production and the evaluation harness run the same code.
"""

from pydantic import BaseModel, Field

from app.llm import generate_structured
from app.resume import CandidateProfile, profile_card


class TailoredContent(BaseModel):
    """The tailoring contract — honesty is in the required fields."""

    target_summary: str = Field(
        description="A 2-3 sentence professional summary aimed at THIS job, "
        "built only from facts in the original resume"
    )
    skills_ordered: list[str] = Field(
        description="The candidate's REAL skills, reordered so the ones this "
        "job values come first. Reordering is honest; adding is not."
    )
    experience_bullets: list[str] = Field(
        description="Rewritten experience bullets emphasizing what this job "
        "cares about. Every fact must exist in the original resume."
    )
    keywords_covered: list[str] = Field(
        description="Words from the posting that the tailored resume "
        "legitimately covers"
    )
    gaps_not_claimed: list[str] = Field(
        description="Requirements from the posting the candidate does NOT "
        "meet, which this tailoring deliberately does not claim. Empty only "
        "if the candidate truly meets everything."
    )
    change_log: list[str] = Field(
        description="Plain sentences describing each change made and why"
    )


TAILOR_SYSTEM = """You tailor resumes toward specific job postings.

The line you never cross: REORDER and REPHRASE, never INVENT. Every
skill, employer, technology, and number in your output must exist in the
original resume text. When the posting wants something the resume cannot
honestly show, that item belongs in gaps_not_claimed — putting it
anywhere else is fabrication, and fabrication in a resume damages a real
person's career and reputation. The gaps list is a feature: candidates
who know their gaps can address them in a cover letter or interview."""


async def generate_tailored_content(
    profile: CandidateProfile,
    raw_resume_text: str,
    job_title: str,
    job_company: str,
    job_description: str,
) -> TailoredContent:
    """Pure core: same inputs, same behavior, in production and in evals."""
    return await generate_structured(
        agent="resume_tailor",
        system=TAILOR_SYSTEM,
        prompt=(
            f"ORIGINAL RESUME (the only source of facts):\n{raw_resume_text[:12000]}\n\n"
            f"CANDIDATE PROFILE:\n{profile_card(profile)}\n\n"
            f"TARGET JOB: {job_title} at {job_company}\n\n"
            f"POSTING:\n{job_description[:6000]}\n\n"
            "Tailor the resume toward this job."
        ),
        schema=TailoredContent,
        max_tokens=3000,
        fake_response={
            "target_summary": (
                f"Fake-mode summary aimed at {job_title}: engineer with "
                "python, sql, and docker experience."
            ),
            "skills_ordered": ["python", "docker", "sql"],
            "experience_bullets": [
                "Built backend services in python (fake mode).",
                "Containerized deployments with docker (fake mode).",
            ],
            "keywords_covered": ["python", "docker"],
            "gaps_not_claimed": [
                f"fake mode cannot read the real {job_title} posting"
            ],
            "change_log": [
                "Reordered skills to lead with python (fake mode).",
                "Rewrote bullets toward the posting (fake mode).",
            ],
        },
    )
