"""requirement_soft_delete

Revision ID: 20260914_20
Revises: 20260914_19
"""

import sqlalchemy as sa
from alembic import op

revision = "20260914_20"
down_revision = "20260914_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requirement_rule",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="逻辑删除时间，带时区；为空表示可用，非空表示随功能分类一起删除，历史与来源保留",
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM requirement_rule WHERE deleted_at IS NOT NULL)")
    ):
        raise RuntimeError("Refuse to resurrect deleted requirements by dropping deleted_at")
    op.drop_column("requirement_rule", "deleted_at")
