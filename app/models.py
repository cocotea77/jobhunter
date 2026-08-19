"""The database models: Python classes that define our tables.

Each class below describes one table — its columns, their types, and its
rules. This is the single source of truth for what the database looks
like. Alembic (the migration tool) compares these classes against the real
database and generates the change scripts that keep the two in step.

The style used is SQLAlchemy 2.0's typed style: each column is declared as
   name: Mapped[python_type] = mapped_column(...)
which gives us editor autocompletion and type checking for free.
"""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The parent class every model inherits from. Alembic reads the
    complete table catalog from Base.metadata."""


class Job(Base):
    """One job posting, fetched from a public source.

    This table is created now (Step 1) and filled in Step 3, when the
    ingestion pipeline starts pulling real postings. Designing the table
    first forces the data questions to be answered before any fetching
    code exists — the professional order.
    """

    __tablename__ = "jobs"

    # Every posting also has an identity at its source. The pair
    # (source, external_id) is declared unique, which is how the database
    # itself guarantees that fetching the same posting twice can never
    # create a duplicate row — a rule enforced by Postgres, not by our
    # code remembering to check. Rules the database enforces cannot be
    # forgotten by a future programmer.
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    # Where this posting came from: "greenhouse", "lever", "remotive", ...
    source: Mapped[str]

    # The posting's identifier inside that source's own system.
    external_id: Mapped[str]

    company: Mapped[str]
    title: Mapped[str]

    # Optional (note the `| None`): many remote postings have no location.
    location: Mapped[str | None]

    # The full posting text. Text = unlimited length, unlike a
    # default string column.
    description: Mapped[str] = mapped_column(Text)

    # Link back to the original posting, so users can apply at the source.
    url: Mapped[str]

    # When the source says the job was posted. Optional: not every source
    # provides it. timezone=True stores an unambiguous moment in time —
    # naive timestamps cause subtle bugs the moment a server runs in UTC.
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # When WE fetched it. server_default=func.now() means the database
    # fills this in itself at insert time — one less thing application
    # code can forget or fake.
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # The posting's meaning vector (Step 4). Nullable: a job exists the
    # moment it is fetched; its embedding arrives in a second pass, and
    # matching simply skips jobs not yet embedded. The pgvector column
    # type is why we chose this Postgres image on day one.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)


class AgentRun(Base):
    """One row per AI round trip — the project's flight recorder.

    Written by app/llm.py (the gateway) on every call, success or failure.
    Nothing else writes here; everything that wants to know "which agent,
    how many calls, how slow, how much money" reads from here — the
    /metrics endpoint today, the spending stop (Step 8) and the evaluation
    harness (Step 6) later. One door in, many readers out.
    """

    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Who asked: "resume_parser", "coach", "demo" ... — the label every
    # metric is grouped by.
    agent: Mapped[str]

    # Which model answered: "claude-sonnet-4-6", "fake", ...
    model: Mapped[str]

    # How long the round trip took, in milliseconds.
    latency_ms: Mapped[int]

    # How much text went in and came out, in tokens (word pieces).
    # Output tokens are the expensive kind.
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]

    # What this single call cost, in US dollars, computed from the price
    # table at call time. Small numbers that add up — which is the point
    # of recording them.
    cost_usd: Mapped[float]

    # Did the call succeed? Failures are recorded too (success=False plus
    # the error text) — an invisible failure cannot be fixed.
    success: Mapped[bool]
    error: Mapped[str | None] = mapped_column(Text)

    # When it happened. The database fills this in itself.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Candidate(Base):
    """One person's resume, understood.

    raw_text is the resume exactly as extracted — the ground truth that
    every AI output about this person must trace back to. profile is the
    parser agent's structured reading of it. embedding is the meaning
    vector of the profile, used by stage one of matching. Keeping all
    three lets later steps AUDIT the AI against the source — the honesty
    checks of Step 6 depend on raw_text surviving unmodified.
    """

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    raw_text: Mapped[str] = mapped_column(Text)
    profile: Mapped[dict] = mapped_column(JSONB)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Match(Base):
    """One candidate matched against one job — with the evidence.

    vector_score comes from stage one (meaning similarity, 0 to 1).
    llm_score and analysis come from stage two, and are OPTIONAL by
    design: only the top few matches get the expensive explanation, and a
    scorer failure degrades a match to vector-only instead of killing the
    run. NULL here is not missing data — it is a recorded decision.
    """

    __tablename__ = "matches"

    # One row per (candidate, job) pair — re-running matching updates
    # rather than duplicates, enforced by the database as always.
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_matches_candidate_job"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    vector_score: Mapped[float]
    llm_score: Mapped[int | None]
    analysis: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )



class TailoredResume(Base):
    """One tailored resume: candidate + target job + the agent's output.

    content holds the full TailoredContent — including gaps_not_claimed
    and change_log, the honesty evidence Step 6's judge will read against
    candidates.raw_text.
    """

    __tablename__ = "tailored_resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    content: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatSession(Base):
    """One conversation between one candidate and the coach."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChatMessage(Base):
    """One message in a session. role is "user" or "assistant"; assistant
    rows carry meta: which tools ran, latency, whether the turn timed out
    — the observable trace of every agentic decision."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

