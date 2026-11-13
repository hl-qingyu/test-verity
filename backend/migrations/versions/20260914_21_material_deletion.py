"""Soft delete materials while preserving source versions and evidence."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_21"
down_revision = "20260914_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_document",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="资料逻辑删除时间，带时区；空表示未删除，原件和版本引用继续保留",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "deleted_by",
            sa.BigInteger(),
            nullable=True,
            comment="删除资料的操作用户ID；空表示未删除",
        ),
    )
    op.create_foreign_key(
        "source_document_deleted_by_fkey", "source_document", "user_account", ["deleted_by"], ["id"]
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM source_document WHERE deleted_at IS NOT NULL)")
    ):
        raise RuntimeError("存在已删除资料，禁止降级丢失删除记录")
    op.drop_constraint("source_document_deleted_by_fkey", "source_document", type_="foreignkey")
    op.drop_column("source_document", "deleted_by")
    op.drop_column("source_document", "deleted_at")
