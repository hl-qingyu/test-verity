"""Persist reasoning effort; existing connections keep provider defaults."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_03"
down_revision = "20260911_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_connection",
        sa.Column("reasoning_effort", sa.Text(), server_default="default", nullable=False),
    )
    op.create_check_constraint(
        "ck_ai_reasoning_effort",
        "ai_connection",
        "reasoning_effort IN ('default', 'none', 'minimal', 'low', 'medium', "
        "'high', 'xhigh', 'max', 'ultra')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ai_reasoning_effort", "ai_connection", type_="check")
    op.drop_column("ai_connection", "reasoning_effort")
