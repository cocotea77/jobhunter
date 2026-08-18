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

from sqlalchemy import DateTime, Text, UniqueConstraint, func
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
