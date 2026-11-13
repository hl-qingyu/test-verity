"""Describe automatic import preview; preserve stored batches and case data."""

from alembic import op

revision = "20260912_10"
down_revision = "20260912_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("case_import", "preview", comment="自动校验、重复对比和待确认用例快照")


def downgrade() -> None:
    op.alter_column("case_import", "preview", comment="导入映射、错误警告和待确认用例快照")
