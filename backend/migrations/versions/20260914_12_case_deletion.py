"""Preserve deleted case identities and history."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_12"
down_revision = "20260914_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "managed_case",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="逻辑删除时间，带时区；空表示未删除，删除后保留编号及历史",
        ),
    )
    op.add_column(
        "managed_case",
        sa.Column(
            "deleted_by", sa.BigInteger(), nullable=True, comment="删除操作用户ID；空表示未删除"
        ),
    )
    op.create_foreign_key(
        "managed_case_deleted_by_fkey", "managed_case", "user_account", ["deleted_by"], ["id"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM managed_case WHERE deleted_at IS NOT NULL)")
    ):
        raise RuntimeError("存在已删除用例，禁止降级丢失删除记录")
    op.drop_constraint("managed_case_deleted_by_fkey", "managed_case", type_="foreignkey")
    op.drop_column("managed_case", "deleted_by")
    op.drop_column("managed_case", "deleted_at")
