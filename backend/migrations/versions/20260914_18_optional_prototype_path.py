"""Document empty prototype scope as the repository root."""

from alembic import op

revision = "20260914_18"
down_revision = "20260914_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "source_document",
        "path",
        comment="GITHUB原型目录或文件相对路径；空字符串表示整个仓库，非GITHUB为NULL",
        existing_comment="GITHUB原型目录或文件相对路径；其他类型为空",
    )


def downgrade() -> None:
    op.alter_column("source_document", "path", comment="GITHUB原型目录或文件相对路径；其他类型为空")
