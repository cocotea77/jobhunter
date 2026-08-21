"""Create usage_counters; add candidates.consent_at.

Revision ID: 0007
Revises: 0006 (accounts and ownership)

usage_counters is one row per (user, action, day) with a uniqueness rule
the quota increment relies on for atomicity. consent_at records WHEN the
user agreed at upload time — nullable because rows from before this step
predate the checkbox (the same honest-nullable reasoning as user_id in
0006).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_counters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "action", "day", name="uq_usage_user_action_day"
        ),
    )

    op.add_column(
        "candidates",
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("candidates", "consent_at")
    op.drop_table("usage_counters")
