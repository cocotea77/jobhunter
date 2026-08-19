"""Create eval_runs and eval_case_results; add run_id to agent_runs.

Revision ID: 0005
Revises: 0004 (agent layer tables)

The quality ledger. agent_runs.run_id lets every AI call be attributed
to the eval run that caused it (NULL = organic traffic), which is how a
run reports its own exact cost.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_runs", sa.Column("run_id", sa.String(), nullable=True))

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("suite", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("fake_mode", sa.Boolean(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Float(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "eval_case_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("failures", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("eval_case_results")
    op.drop_table("eval_runs")
    op.drop_column("agent_runs", "run_id")
