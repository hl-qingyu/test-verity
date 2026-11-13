"""prototype_materials

Revision ID: 20260914_14
Revises: 20260914_13
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260914_14"
down_revision = "20260914_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_group",
        sa.Column(
            "purpose",
            sa.Text(),
            server_default="REQUIREMENT",
            nullable=False,
            comment="资料类别：REQUIREMENT需求资料、PROTOTYPE原型资料",
        ),
    )
    op.drop_constraint(op.f("uq_document_group_name"), "document_group", type_="unique")
    op.create_unique_constraint(
        "uq_document_group_name", "document_group", ["project_id", "purpose", "name"]
    )
    op.add_column(
        "source_document",
        sa.Column(
            "purpose",
            sa.Text(),
            server_default="REQUIREMENT",
            nullable=False,
            comment="资料类别：REQUIREMENT需求资料、PROTOTYPE原型资料",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "kind",
            sa.Text(),
            server_default="FILE",
            nullable=False,
            comment="来源类型：FILE上传文件、GITHUB实时仓库、LINK实时链接",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "name",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="原型资料显示名称；需求文件默认空并使用文件名",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "description",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="原型页面或交互说明；默认空字符串",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "url",
            sa.Text(),
            nullable=True,
            comment="LINK原型的HTTP或HTTPS地址；其他类型为空，不保存页面快照",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            nullable=True,
            comment="GITHUB来源的项目仓库关联ID；其他类型为空，不包含凭据",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "branch", sa.Text(), nullable=True, comment="GITHUB来源持续跟踪的分支；其他类型为空"
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "path", sa.Text(), nullable=True, comment="GITHUB原型目录或文件相对路径；其他类型为空"
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "selected_paths",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
            comment="用户明确选中的仓库文件路径清单；非GITHUB为空数组，不自动扩大范围",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "latest_commit",
            sa.String(length=40),
            nullable=True,
            comment="最近成功核实的GitHub提交SHA；未检查或非GITHUB为空",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "file_manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
            comment="最近固定提交的所选文件元数据清单：path、sha、size；不保存或执行源码",
        ),
    )
    op.add_column(
        "source_document",
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="最近成功检查GitHub的时间；未检查或非GITHUB为空",
        ),
    )
    op.alter_column(
        "source_document",
        "current_version",
        existing_type=sa.INTEGER(),
        comment="上传文件当前版本号，关联document_version.number；实时来源固定为1且不生成文件版本",
        existing_comment="当前资料版本号，关联同一资料的document_version.number",
        existing_nullable=False,
    )
    op.create_foreign_key(
        "fk_source_document_repository",
        "source_document",
        "project_repository",
        ["repository_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_document_group_purpose", "document_group", "purpose IN ('REQUIREMENT','PROTOTYPE')"
    )
    op.create_check_constraint(
        "ck_source_document_purpose", "source_document", "purpose IN ('REQUIREMENT','PROTOTYPE')"
    )
    op.create_check_constraint(
        "ck_source_document_kind",
        "source_document",
        "kind IN ('FILE','GITHUB','LINK') AND (kind = 'FILE' OR purpose = 'PROTOTYPE')",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM source_document WHERE purpose = 'PROTOTYPE') "
            "OR EXISTS(SELECT 1 FROM document_group WHERE purpose = 'PROTOTYPE')"
        )
    ):
        raise RuntimeError("已有原型资料，拒绝降级删除来源和分组")
    op.drop_constraint("ck_source_document_kind", "source_document", type_="check")
    op.drop_constraint("ck_source_document_purpose", "source_document", type_="check")
    op.drop_constraint("ck_document_group_purpose", "document_group", type_="check")
    op.drop_constraint("fk_source_document_repository", "source_document", type_="foreignkey")
    op.alter_column(
        "source_document",
        "current_version",
        existing_type=sa.INTEGER(),
        comment="当前资料版本号，关联同一资料的document_version.number",
        existing_comment="上传文件当前版本号，关联document_version.number；实时来源固定为1且不生成文件版本",
        existing_nullable=False,
    )
    op.drop_column("source_document", "checked_at")
    op.drop_column("source_document", "file_manifest")
    op.drop_column("source_document", "latest_commit")
    op.drop_column("source_document", "selected_paths")
    op.drop_column("source_document", "path")
    op.drop_column("source_document", "branch")
    op.drop_column("source_document", "repository_id")
    op.drop_column("source_document", "url")
    op.drop_column("source_document", "description")
    op.drop_column("source_document", "name")
    op.drop_column("source_document", "kind")
    op.drop_column("source_document", "purpose")
    op.drop_constraint("uq_document_group_name", "document_group", type_="unique")
    op.create_unique_constraint(
        op.f("uq_document_group_name"),
        "document_group",
        ["project_id", "name"],
        postgresql_nulls_not_distinct=False,
    )
    op.drop_column("document_group", "purpose")
