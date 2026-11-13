"""Clarify the now-shared material table and scoped group semantics."""

from alembic import op

revision = "20260914_16"
down_revision = "20260914_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table_comment(
        "document_group",
        "项目内按需求或原型类别隔离的资料分组，允许空分组",
        existing_comment="项目内的原始资料分组，允许空分组",
    )
    op.alter_column(
        "document_group",
        "name",
        comment="资料分组名称，同项目及同资料类别内唯一",
        existing_comment="资料分组名称，同项目内唯一",
    )
    op.create_table_comment(
        "source_document",
        "需求与原型资料来源；上传文件按版本保存，GitHub及链接记录实时配置",
        existing_comment="原始资料逻辑记录，保存分组、排序与当前版本",
    )


def downgrade() -> None:
    op.create_table_comment("document_group", "项目内的原始资料分组，允许空分组")
    op.alter_column("document_group", "name", comment="资料分组名称，同项目内唯一")
    op.create_table_comment("source_document", "原始资料逻辑记录，保存分组、排序与当前版本")
