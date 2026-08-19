"""Add embeddings to jobs; create candidates and matches.

Revision ID: 0003
Revises: 0002 (agent_runs)

Made by the standard workflow: models first, autogenerate drafted,
human reviewed. Note the pgvector import — the vector column type the
very first migration activated the extension for. Day one's decision,
paying off on schedule.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("embedding", Vector(1536), nullable=True))

    op.create_table(
        "candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("profile", JSONB(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("vector_score", sa.Float(), nullable=False),
        sa.Column("llm_score", sa.Integer(), nullable=True),
        sa.Column("analysis", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("candidate_id", "job_id", name="uq_matches_candidate_job"),
    )


def downgrade() -> None:
    op.drop_table("matches")
    op.drop_table("candidates")
    op.drop_column("jobs", "embedding")
