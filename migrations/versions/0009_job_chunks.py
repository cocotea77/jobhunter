"""Create job_chunks: the retrieval unit for the RAG pipeline.

Revision ID: 0009
Revises: 0008 (match jobs)

One row per chunk of one job description, carrying BOTH retrieval
representations: a pgvector embedding (meaning) and a stored, generated
tsvector column (words) with a GIN index — the two halves of hybrid
search, indexed side by side in the same row. The tsvector is a
GENERATED column: Postgres computes and maintains it from content
automatically, so application code can never forget to update it —
the same philosophy as every constraint in this project: rules the
database enforces have no bugs.
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_chunks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column(
            "tsv",
            sa.dialects.postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_id", "chunk_index", name="uq_job_chunk_index"),
    )
    op.create_index(
        "ix_job_chunks_tsv", "job_chunks", ["tsv"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_job_chunks_tsv", table_name="job_chunks")
    op.drop_table("job_chunks")
