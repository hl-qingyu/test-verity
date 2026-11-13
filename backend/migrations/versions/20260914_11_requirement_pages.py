"""requirement_pages

Revision ID: 20260914_11
Revises: 20260912_10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260914_11"
down_revision = "20260912_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requirement_category",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="分类主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "parent_id",
            sa.BigInteger(),
            nullable=True,
            comment="所属模块ID；为空表示顶层模块，仅允许两级",
        ),
        sa.Column("name", sa.Text(), nullable=False, comment="分类名称，1至80字，同级唯一"),
        sa.Column("position", sa.Integer(), nullable=False, comment="同级展示顺序，按数值升序"),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_requirement_category_self"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["requirement_category.project_id", "requirement_category.id"],
            name="fk_requirement_category_parent",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "id", name="uq_requirement_category_project"),
        comment="项目功能模块与功能点，空分类永久保留；父级为空表示模块",
    )
    op.create_index(
        op.f("ix_requirement_category_project_id"),
        "requirement_category",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "uq_requirement_category_name",
        "requirement_category",
        ["project_id", sa.literal_column("coalesce(parent_id, 0)"), "name"],
        unique=True,
    )
    op.create_table(
        "requirement_classification",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="分类操作主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("actor_id", sa.BigInteger(), nullable=False, comment="操作用户ID"),
        sa.Column(
            "before",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="操作前涉及分类及验收点归属；新增分类时对应项为空",
        ),
        sa.Column(
            "after",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="操作后分类及验收点归属，用于撤销冲突检查",
        ),
        sa.Column(
            "undone",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="是否已撤销，真表示不能再次撤销",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="分类操作时间，带时区",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="分类新增、改名、移动及撤销的审计记录，仅保存分类字段",
    )
    op.create_index(
        op.f("ix_requirement_classification_project_id"),
        "requirement_classification",
        ["project_id"],
        unique=False,
    )
    op.create_table(
        "requirement_library",
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="页面并发修订号，每次写入递增",
        ),
        sa.Column(
            "next_number",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="下一个项目内验收点编号",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("project_id"),
        comment="项目验收点库编号及并发修订号",
    )
    op.create_table(
        "requirement_rule",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="验收点主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("number", sa.Integer(), nullable=False, comment="项目内永久递增展示编号"),
        sa.Column(
            "request_id",
            sa.String(length=36),
            nullable=False,
            comment="新建请求UUID，用于防止重复创建",
        ),
        sa.Column(
            "category_id", sa.BigInteger(), nullable=True, comment="功能点或模块ID；为空表示待归类"
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            comment="业务及审核版本号，从1递增；分类操作不递增",
        ),
        sa.Column("title", sa.Text(), nullable=False, comment="验收点名称"),
        sa.Column("role", sa.Text(), nullable=False, comment="适用业务角色；空字符串表示未填写"),
        sa.Column(
            "preconditions", sa.Text(), nullable=False, comment="业务前置条件；空字符串表示未填写"
        ),
        sa.Column("action", sa.Text(), nullable=False, comment="业务操作步骤"),
        sa.Column("expected", sa.Text(), nullable=False, comment="场景预期结果"),
        sa.Column(
            "question", sa.Text(), nullable=False, comment="需要补充的问题；空字符串表示无问题"
        ),
        sa.Column(
            "resolution",
            sa.Text(),
            nullable=False,
            comment="问题处理结论或人工确认说明；空字符串表示未填写",
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="审核状态：NEEDS_INFO待补充、REVIEW待审核、CONFIRMED已确认",
        ),
        sa.Column("updated_by", sa.BigInteger(), nullable=False, comment="最后修改或审核的用户ID"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="最后业务修改或审核时间，带时区",
        ),
        sa.CheckConstraint(
            "status IN ('NEEDS_INFO','REVIEW','CONFIRMED')", name="ck_requirement_rule_status"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "category_id"],
            ["requirement_category.project_id", "requirement_category.id"],
            name="fk_requirement_rule_category",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "id", name="uq_requirement_rule_project"),
        sa.UniqueConstraint("project_id", "number", name="uq_requirement_rule_number"),
        sa.UniqueConstraint("project_id", "request_id", name="uq_requirement_rule_request"),
        comment="项目共享验收点当前业务内容；分类变更不改变业务版本和审核状态",
    )
    op.create_index(
        op.f("ix_requirement_rule_project_id"), "requirement_rule", ["project_id"], unique=False
    )
    op.create_table(
        "requirement_history",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="历史记录主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("rule_id", sa.BigInteger(), nullable=False, comment="所属验收点ID"),
        sa.Column("version", sa.Integer(), nullable=False, comment="本次业务审核版本号"),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="完整业务内容、确认状态及来源版本快照，不随当前修改",
        ),
        sa.Column("actor_id", sa.BigInteger(), nullable=False, comment="本次操作用户ID"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="版本创建时间，带时区",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["requirement_rule.project_id", "requirement_rule.id"],
            name="fk_requirement_history_rule",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "version", name="uq_requirement_history_version"),
        comment="不可覆盖的验收点业务和审核版本快照，含固定资料来源",
    )
    op.create_table(
        "requirement_source",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="来源记录主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("rule_id", sa.BigInteger(), nullable=False, comment="关联验收点ID"),
        sa.Column(
            "document_version_id",
            sa.BigInteger(),
            nullable=False,
            comment="固定资料版本ID，不自动切换新版",
        ),
        sa.Column(
            "role", sa.Text(), nullable=False, comment="资料用途：DOCUMENT需求文档、PROTOTYPE原型图"
        ),
        sa.Column(
            "location",
            sa.Text(),
            nullable=False,
            comment="人工填写的章节、单元格或页面位置；空字符串表示整份资料",
        ),
        sa.Column(
            "excerpt", sa.Text(), nullable=False, comment="人工摘录或对照说明；不代表机器验证的原文"
        ),
        sa.CheckConstraint("role IN ('DOCUMENT','PROTOTYPE')", name="ck_requirement_source_role"),
        sa.ForeignKeyConstraint(
            ["project_id", "document_version_id"],
            ["document_version.project_id", "document_version.id"],
            name="fk_requirement_source_document",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["requirement_rule.project_id", "requirement_rule.id"],
            name="fk_requirement_source_rule",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rule_id", "document_version_id", name="uq_requirement_source_version"),
        comment="验收点当前固定文档或原型图版本来源；历史来源保留在验收点版本中",
    )


def downgrade() -> None:
    connection = op.get_bind()
    for table in ("requirement_category", "requirement_rule", "requirement_classification"):
        if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM " + table + ")")):
            raise RuntimeError("Refuse to remove saved requirement data")
    op.drop_table("requirement_source")
    op.drop_table("requirement_history")
    op.drop_index(op.f("ix_requirement_rule_project_id"), table_name="requirement_rule")
    op.drop_table("requirement_rule")
    op.drop_table("requirement_library")
    op.drop_index(
        op.f("ix_requirement_classification_project_id"), table_name="requirement_classification"
    )
    op.drop_table("requirement_classification")
    op.drop_index("uq_requirement_category_name", table_name="requirement_category")
    op.drop_index(op.f("ix_requirement_category_project_id"), table_name="requirement_category")
    op.drop_table("requirement_category")
