"""case_management

Revision ID: 20260912_09
Revises: 20260912_08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260912_09"
down_revision = "20260912_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_category",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="分类主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("name", sa.Text(), nullable=False, comment="分类名称，同项目唯一"),
        sa.Column("updated_by", sa.BigInteger(), nullable=False, comment="最后维护分类的用户ID"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "id", name="uq_case_category_project"),
        sa.UniqueConstraint("project_id", "name", name="uq_case_category_name"),
        comment="项目共享用例分类，允许自定义名称和空分类",
    )
    op.create_index(
        op.f("ix_case_category_project_id"), "case_category", ["project_id"], unique=False
    )
    op.create_table(
        "case_import",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="导入批次主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("filename", sa.Text(), nullable=False, comment="导入原文件名"),
        sa.Column(
            "storage_key",
            sa.String(length=32),
            nullable=False,
            comment="私有原件随机存储键，不是用户路径",
        ),
        sa.Column("sha256", sa.String(length=64), nullable=False, comment="原件SHA256校验值"),
        sa.Column("request_id", sa.String(length=36), nullable=False, comment="上传幂等请求UUID"),
        sa.Column(
            "raw_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="已校验的工作表、单元格、公式位置及合并范围快照",
        ),
        sa.Column(
            "preview",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="导入映射、错误警告和待确认用例快照",
        ),
        sa.Column(
            "preview_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="预览修订号，防止旧预览误确认",
        ),
        sa.Column(
            "library_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="预览时用例库修订号，确认时核对",
        ),
        sa.Column(
            "committed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
            comment="是否已确认入库，重复确认不新增用例",
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False, comment="上传用户ID"),
        sa.Column(
            "confirmed_by", sa.BigInteger(), nullable=True, comment="确认入库用户ID，未确认时为空"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="导入上传时间，带时区",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "id", name="uq_case_import_project"),
        sa.UniqueConstraint("project_id", "request_id", name="uq_case_import_request"),
        sa.UniqueConstraint("storage_key"),
        comment="用例导入原件、解析数据和确认批次，确认后只读",
    )
    op.create_index(op.f("ix_case_import_project_id"), "case_import", ["project_id"], unique=False)
    op.create_table(
        "case_library",
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "next_number",
            sa.BigInteger(),
            server_default="1",
            nullable=False,
            comment="下一个平台用例编号，项目内递增，不采用导入编号",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="用例库并发修订号，操作时校验防止覆盖",
        ),
        sa.CheckConstraint("next_number > 0", name="ck_case_next_number"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("project_id"),
        comment="项目用例库自增编号与并发修订号",
    )
    op.create_table(
        "managed_case",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="用例内部主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "number",
            sa.BigInteger(),
            nullable=False,
            comment="项目内自增展示编号，不使用导入原编号",
        ),
        sa.Column(
            "category_id",
            sa.BigInteger(),
            nullable=True,
            comment="所属分类ID；空为未分类，分类必须同项目",
        ),
        sa.Column(
            "current_version", sa.Integer(), nullable=False, comment="当前设计版本号，从1开始"
        ),
        sa.Column("request_id", sa.String(length=36), nullable=False, comment="创建幂等请求UUID"),
        sa.Column("created_by", sa.BigInteger(), nullable=False, comment="用例创建用户ID"),
        sa.Column(
            "updated_by", sa.BigInteger(), nullable=False, comment="最后操作用户ID，包括分类调整"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="用例创建时间，带时区",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "category_id"],
            ["case_category.project_id", "case_category.id"],
            name="fk_case_category_project",
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
        sa.UniqueConstraint("project_id", "id", name="uq_managed_case_project"),
        sa.UniqueConstraint("project_id", "number", name="uq_managed_case_number"),
        sa.UniqueConstraint("project_id", "request_id", name="uq_managed_case_request"),
        comment="项目用例稳定身份和当前分类，编号永久保留",
    )
    op.create_index(
        op.f("ix_managed_case_project_id"), "managed_case", ["project_id"], unique=False
    )
    op.create_table(
        "case_version",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="设计版本主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column("case_id", sa.BigInteger(), nullable=False, comment="所属用例ID，必须同项目"),
        sa.Column("number", sa.Integer(), nullable=False, comment="设计版本号，同一用例内递增"),
        sa.Column("module", sa.Text(), server_default="", nullable=False, comment="功能模块"),
        sa.Column("structure", sa.Text(), server_default="", nullable=False, comment="功能结构"),
        sa.Column(
            "case_type",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="用例类型，空为未提供",
        ),
        sa.Column(
            "priority",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="优先级P0至P4，空为未提供",
        ),
        sa.Column("description", sa.Text(), server_default="", nullable=False, comment="用例描述"),
        sa.Column("title", sa.Text(), server_default="", nullable=False, comment="验证用例子项"),
        sa.Column(
            "preconditions",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="前置条件，保留换行",
        ),
        sa.Column(
            "steps",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="操作步骤，保留时序和换行",
        ),
        sa.Column(
            "expected",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="场景级预期结果，不要求与步骤行数相等",
        ),
        sa.Column("remark", sa.Text(), server_default="", nullable=False, comment="备注"),
        sa.Column(
            "data_requirements",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="测试数据要求，空为未提供",
        ),
        sa.Column(
            "cleanup", sa.Text(), server_default="", nullable=False, comment="清理要求，空为未提供"
        ),
        sa.Column(
            "source_kind", sa.Text(), nullable=False, comment="来源类型：MANUAL人工创建、IMPORT导入"
        ),
        sa.Column(
            "import_id", sa.BigInteger(), nullable=True, comment="来源导入批次ID，人工创建为空"
        ),
        sa.Column(
            "source",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="来源工作表、行号、原序号编号及原测试结果",
        ),
        sa.Column("created_by", sa.BigInteger(), nullable=False, comment="该版本创建人ID"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="版本创建时间，带时区",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "case_id"],
            ["managed_case.project_id", "managed_case.id"],
            name="fk_case_version_project",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "import_id"],
            ["case_import.project_id", "case_import.id"],
            name="fk_case_version_import",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_id", "number", name="uq_case_version_number"),
        sa.UniqueConstraint("project_id", "id", name="uq_case_version_project"),
        comment="用例设计追加版本，修改设计保留旧版",
    )
    op.create_index(op.f("ix_case_version_case_id"), "case_version", ["case_id"], unique=False)
    op.create_table(
        "case_record",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="记录主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "version_id", sa.BigInteger(), nullable=False, comment="固定设计版本ID，必须同项目"
        ),
        sa.Column("kind", sa.Text(), nullable=False, comment="记录类型TEST测试结果或REVIEW审核"),
        sa.Column(
            "result",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="未测、通过、失败、阻塞、跳过、废弃或空",
        ),
        sa.Column(
            "tester",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="填写或导入的测试人员名称，空为未提供",
        ),
        sa.Column(
            "review_status",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="待审核、已审核；测试记录中为空",
        ),
        sa.Column(
            "source_kind", sa.Text(), nullable=False, comment="记录来源MANUAL人工或IMPORT导入"
        ),
        sa.Column(
            "recorded_by",
            sa.BigInteger(),
            nullable=False,
            comment="实际录入用户ID，不等同测试执行人",
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="录入时间，不冒充实际测试执行时间",
        ),
        sa.CheckConstraint("kind IN ('TEST','REVIEW')", name="ck_case_record_kind"),
        sa.ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["case_version.project_id", "case_version.id"],
            name="fk_case_record_version",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="用例版本的追加测试及审核记录，旧记录不覆盖",
    )
    op.create_index(op.f("ix_case_record_version_id"), "case_record", ["version_id"], unique=False)


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM managed_case) "
            "OR EXISTS (SELECT 1 FROM case_category) OR EXISTS (SELECT 1 FROM case_import)"
        )
    ):
        raise RuntimeError("Cannot remove existing case-management data.")
    op.drop_index(op.f("ix_case_record_version_id"), table_name="case_record")
    op.drop_table("case_record")
    op.drop_index(op.f("ix_case_version_case_id"), table_name="case_version")
    op.drop_table("case_version")
    op.drop_index(op.f("ix_managed_case_project_id"), table_name="managed_case")
    op.drop_table("managed_case")
    op.drop_table("case_library")
    op.drop_index(op.f("ix_case_import_project_id"), table_name="case_import")
    op.drop_table("case_import")
    op.drop_index(op.f("ix_case_category_project_id"), table_name="case_category")
    op.drop_table("case_category")
