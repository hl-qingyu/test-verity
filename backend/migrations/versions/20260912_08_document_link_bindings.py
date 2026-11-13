"""document_link_bindings

Revision ID: 20260912_08
Revises: 20260912_07
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_08"
down_revision = "20260912_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_document_version_project", "document_version", ["project_id", "id"]
    )
    op.create_table(
        "document_link_binding",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
            comment="关联记录主键，可用于分析快照追溯",
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            nullable=False,
            comment="所属项目ID，来源及目标版本必须同项目",
        ),
        sa.Column(
            "source_version_id", sa.BigInteger(), nullable=False, comment="来源Markdown的固定版本ID"
        ),
        sa.Column(
            "href",
            sa.Text(),
            nullable=False,
            comment="Markdown解析后的链接地址，仅作匹配标识，不用于访问文件或网络",
        ),
        sa.Column(
            "href_hash",
            sa.String(length=64),
            nullable=False,
            comment="链接地址规范化后SHA256，用于同一来源版本内匹配链接",
        ),
        sa.Column(
            "target_version_id",
            sa.BigInteger(),
            nullable=False,
            comment="人工选定的目标附件固定版本ID，不自动跟随新版",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            comment="同来源版本及链接的关联修订号，从1递增，修改追加新记录",
        ),
        sa.Column(
            "inherited_from_id",
            sa.BigInteger(),
            nullable=True,
            comment="从上一来源版本继承的关联记录ID；为空表示人工选择",
        ),
        sa.Column(
            "created_by", sa.BigInteger(), nullable=False, comment="建立或继承关联的操作人用户ID"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="关联建立时间，带时区",
        ),
        sa.CheckConstraint("revision > 0", name="ck_link_binding_revision"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["inherited_from_id"],
            ["document_link_binding.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_version_id"],
            ["document_version.project_id", "document_version.id"],
            name="fk_link_source_project",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "target_version_id"],
            ["document_version.project_id", "document_version.id"],
            name="fk_link_target_project",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_version_id", "href_hash", "revision", name="uq_link_binding_revision"
        ),
        comment="Markdown链接的追加式关联历史，固定来源和目标附件版本，不覆盖旧关联",
    )
    op.create_index(
        op.f("ix_document_link_binding_project_id"),
        "document_link_binding",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_link_binding_source_version_id"),
        "document_link_binding",
        ["source_version_id"],
        unique=False,
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM document_link_binding)")):
        raise RuntimeError("Refusing to remove existing document link bindings.")
    op.drop_index(
        op.f("ix_document_link_binding_source_version_id"), table_name="document_link_binding"
    )
    op.drop_index(op.f("ix_document_link_binding_project_id"), table_name="document_link_binding")
    op.drop_table("document_link_binding")
    op.drop_constraint("uq_document_version_project", "document_version", type_="unique")
