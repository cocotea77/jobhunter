"""Create the jobs table (and activate the pgvector extension).

Revision ID: 0001
Revises: (nothing — this is the first migration)

How this file was made — the workflow every future schema change follows:
  1. The Job model was written in app/models.py.
  2. `alembic revision --autogenerate -m "create jobs table"` compared the
     models against the (empty) database and generated the create_table
     call below.
  3. The generated draft was REVIEWED and adjusted by hand: readable
     revision number, comments, and the pgvector activation added.
Autogenerate drafts; a human reviews. Always in that order.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Activate the pgvector extension. It is not needed until Step 4
    # (storing AI embeddings), but activating it in the very first
    # migration follows the "fail early" principle: we chose our Docker
    # image and our hosting plan specifically because they support
    # pgvector — this line proves that choice was honored on day one,
    # in every environment, instead of surprising us weeks later.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_jobs_source_external_id"),
    )


def downgrade() -> None:
    # Downgrade reverses upgrade, in reverse order. Being able to walk
    # backwards is what makes migrations safe to experiment with.
    op.drop_table("jobs")
    op.execute("DROP EXTENSION IF EXISTS vector")
