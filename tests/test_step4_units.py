"""Tests for Step 4's units — no database, no network, instant.

Covered here: text extraction's honest failures, the profile card's
single-representation rule, the fake scorer's determinism and bounds, and
the fake embeddings' defining property (shared words -> nearby vectors).
The full loop against the real database lives in test_database.py.
"""

import asyncio
import math

import pytest

from app import llm
from app.config import settings
from app.embeddings import fake_embedding
from app.matching import MatchAnalysis, score_match
from app.resume import (
    CandidateProfile,
    ResumeExtractionError,
    extract_text,
    parse_resume,
    profile_card,
)

# --- extraction: mechanical, with honest failures ---------------------------


def test_plain_text_resume_is_extracted():
    assert extract_text("resume.txt", b"Jane Doe\npython sql") == "Jane Doe\npython sql"


def test_unsupported_file_type_fails_with_guidance():
    with pytest.raises(ResumeExtractionError, match="Unsupported file type"):
        extract_text("resume.docx", b"anything")


def test_a_broken_pdf_fails_as_the_files_fault():
    """Garbage bytes with a .pdf name must produce OUR clear error —
    never a raw library traceback escaping to the user."""
    with pytest.raises(ResumeExtractionError, match="Could not read this PDF"):
        extract_text("resume.pdf", b"this is not a pdf at all")


def test_non_utf8_text_file_fails_clearly():
    with pytest.raises(ResumeExtractionError, match="not UTF-8"):
        extract_text("resume.txt", b"\xff\xfe\x00broken")


# --- the parser and the profile card ---------------------------------------


@pytest.fixture()
def silent_recorder(monkeypatch):
    """Fake mode on, and gateway recording captured away from the database."""

    async def swallow(**fields):
        pass

    monkeypatch.setattr(llm, "record_run", swallow)
    monkeypatch.setattr(settings, "fake_ai", True)

    # Step 8 put a budget check at the gateway's entrance; it reads the
    # database, and these are pure unit tests — stub it open.
    async def budget_is_fine():
        pass

    import app.safety

    monkeypatch.setattr(app.safety, "ensure_budget_available", budget_is_fine)


def test_parser_returns_a_validated_profile_in_fake_mode(silent_recorder):
    profile = asyncio.run(parse_resume("python sql docker engineer"))
    assert isinstance(profile, CandidateProfile)
    assert profile.skills  # the canned profile is schema-valid


def test_profile_card_contains_what_matching_will_search_by():
    """One representation, used for embedding AND shown to the scorer.
    If a field matters to matching, it must appear here — this test is
    the reminder when someone adds a profile field later."""
    profile = CandidateProfile(
        name="Jane",
        headline="Backend engineer",
        skills=["python", "sql"],
        titles=["Software Engineer"],
        years_of_experience=4,
        summary="Builds services.",
    )
    card = profile_card(profile)
    for needle in ["Backend engineer", "python", "sql", "Software Engineer", "4"]:
        assert needle in card


# --- the scorer's contract --------------------------------------------------


def test_fake_scores_are_deterministic_and_in_range(silent_recorder):
    profile = CandidateProfile(
        name="J", headline="x", skills=["python"], titles=["Engineer"],
        years_of_experience=1, summary="s",
    )

    async def score(title):
        return await score_match(profile, title, "Co", "desc")

    first = asyncio.run(score("Python Backend Engineer"))
    second = asyncio.run(score("Python Backend Engineer"))
    other = asyncio.run(score("Marketing Manager"))

    assert isinstance(first, MatchAnalysis)
    assert first.score == second.score  # same job -> same fake score
    assert 0 <= first.score <= 100 and 0 <= other.score <= 100
    assert first.score != other.score  # different jobs -> varied ranking


def test_schema_rejects_out_of_range_scores():
    """The calibration rule lives in the schema, not in hope."""
    with pytest.raises(Exception):
        MatchAnalysis(score=150, verdict="x", strengths=[], gaps=[])


# --- fake embeddings' defining property -------------------------------------


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (
        (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0
    )


def test_shared_words_land_nearby_and_disjoint_words_do_not():
    """The property the whole fake-mode matching demo rests on."""
    python_job = fake_embedding("python backend sql services")
    python_resume = fake_embedding("python sql engineer")
    marketing = fake_embedding("campaigns brand budgets")

    assert cosine(python_job, python_resume) > cosine(python_resume, marketing)


def test_fake_embeddings_are_deterministic_and_normalized():
    a = fake_embedding("python sql")
    b = fake_embedding("python sql")
    assert a == b
    assert abs(math.sqrt(sum(x * x for x in a)) - 1.0) < 1e-9
    assert len(a) == settings.embedding_dimensions
