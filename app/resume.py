"""Resumes: extracting the text, then understanding it.

Two jobs live here, deliberately separated:

1. extract_text — mechanical: get the words out of the uploaded file.
   No AI involved; failures are the file's fault and say so plainly.
2. parse_resume — the project's FIRST REAL AGENT: reads the text and
   produces a structured CandidateProfile through the Step 2 gateway.

The parser's defining constraint is honesty, enforced twice over. The
system prompt forbids inventing anything not present in the resume. And
the runbook makes YOU audit it: every skill and title in the output must
appear in the actual resume text. An AI feature you have not audited
against its source is a liability wearing a demo's clothes.
"""

from io import BytesIO

from pydantic import BaseModel, Field
from pypdf import PdfReader

from app.llm import generate_structured


class ResumeExtractionError(Exception):
    """The file could not give us text — a user problem, reported kindly."""


def extract_text(filename: str, content: bytes) -> str:
    """Get the words out of an uploaded resume file.

    Supported: PDF (text-based) and plain text (.txt, .md). A scanned
    PDF — photographs of pages — contains no extractable text; we say so
    honestly rather than passing an empty page to the AI. (Reading scans
    would need OCR, optical character recognition — a known, deliberate
    limitation, documented rather than half-built.)
    """
    lowered = filename.lower()
    if lowered.endswith(".pdf"):
        try:
            reader = PdfReader(BytesIO(content))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as error:
            raise ResumeExtractionError(f"Could not read this PDF: {error}") from error
        if len(text.strip()) < 50:
            raise ResumeExtractionError(
                "This PDF contains no readable text — it is probably a scan "
                "(photographs of pages). Please upload a text-based PDF or a "
                ".txt file."
            )
        return text.strip()
    if lowered.endswith((".txt", ".md")):
        try:
            return content.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise ResumeExtractionError(
                "This text file is not UTF-8 encoded and could not be read."
            ) from error
    raise ResumeExtractionError(
        "Unsupported file type. Please upload a .pdf, .txt, or .md resume."
    )


class CandidateProfile(BaseModel):
    """The structured reading of one resume — the parser's contract.

    Every field description doubles as an instruction to the model,
    because the gateway sends the schema itself as part of the prompt.
    """

    name: str = Field(description="The candidate's name exactly as written")
    headline: str = Field(
        description="One line describing the candidate, built ONLY from the resume"
    )
    skills: list[str] = Field(
        description="Skills EXPLICITLY present in the resume — never inferred"
    )
    titles: list[str] = Field(
        description="Job titles the candidate has actually held, per the resume"
    )
    years_of_experience: int = Field(
        description="Total professional years, 0 if not stated or computable"
    )
    summary: str = Field(
        description="3-4 sentences summarizing the candidate, strictly grounded"
    )


PARSER_SYSTEM = """You read resumes and produce structured profiles.

The one rule that outranks all others: NEVER invent. Every skill, title,
employer, and number in your output must be explicitly present in the
resume text. If something is absent, leave it absent — an empty list is a
correct answer; a plausible guess is a wrong one. You are the foundation
other systems will trust; a fabricated skill here becomes a lie told to
an employer later."""


async def parse_resume(text: str) -> CandidateProfile:
    """The first real agent: resume text in, honest structure out."""
    return await generate_structured(
        agent="resume_parser",
        system=PARSER_SYSTEM,
        prompt=f"Read this resume and produce the profile:\n\n{text[:15000]}",
        schema=CandidateProfile,
        fake_response={
            "name": "Fake-Mode Candidate",
            "headline": "Software engineer (fake mode: canned profile)",
            "skills": ["python", "sql", "docker"],
            "titles": ["Software Engineer"],
            "years_of_experience": 3,
            "summary": (
                "This is fake mode's canned profile. Switch FAKE_AI=false "
                "with a real key to parse the actual resume text."
            ),
        },
    )


def profile_card(profile: CandidateProfile) -> str:
    """One compact text describing the candidate — the text that gets
    embedded for matching. One deliberate representation, used everywhere,
    so 'what does matching think a candidate is?' has exactly one answer."""
    return (
        f"{profile.headline}\n"
        f"Titles: {', '.join(profile.titles)}\n"
        f"Skills: {', '.join(profile.skills)}\n"
        f"Experience: {profile.years_of_experience} years\n"
        f"{profile.summary}"
    )
