"""Create match_jobs: background matching with honest progress.

Revision ID: 0008
Revises: 0007 (safety, quotas, consent)

One row per requested matching run. status walks queued -> running ->
done (or failed, with the reason in error — including the special reason
"interrupted by a server restart", written by the startup sweep so a
crash can never leave a zombie 'running' row forever).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("total_to_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scored", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="CASCADE"
        ),
    )


def downgrade() -> None:
    op.drop_table("match_jobs")
