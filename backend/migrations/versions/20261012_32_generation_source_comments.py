"""Clarify generated design provenance without rewriting the applied migration."""

from alembic import op

revision = "20261012_32"
down_revision = "20261012_31"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("case_version", "import_id", comment="来源导入批次ID；非导入版本为空")
    op.alter_column(
        "case_version",
        "source",
        comment="导入原行编号和结果，或生成记录/候选/应用批次/对话引用；人工为空",
    )


def downgrade():
    op.alter_column("case_version", "import_id", comment="来源导入批次ID，人工创建为空")
    op.alter_column("case_version", "source", comment="来源工作表、行号、原序号编号及原测试结果")
