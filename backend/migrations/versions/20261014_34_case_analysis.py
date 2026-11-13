"""case_analysis

Revision ID: 20261014_34
Revises: 20261012_33
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_34"
down_revision = "20261012_33"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_analysis_run",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="分析记录主键"
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "actor_id", sa.BigInteger(), nullable=False, comment="本次执行发起人；只用本人AI"
        ),
        sa.Column(
            "request_id", sa.String(length=36), nullable=False, comment="项目内本人请求UUID；幂等"
        ),
        sa.Column(
            "parent_id", sa.BigInteger(), nullable=True, comment="复核或重试来源ID；首次为空"
        ),
        sa.Column("title", sa.String(length=200), nullable=False, comment="分析名称"),
        sa.Column(
            "mode", sa.String(length=16), nullable=False, comment="COMPARE对照需求或QUALITY仅质量"
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="PREPARED",
            nullable=False,
            comment="PREPARED待开始/QUEUED排队/RUNNING分析/COMPLETED完成/FAILED失败/CANCELLED取消",
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="完整固定资料、批注、用例内部ID和设计版本；无密钥",
        ),
        sa.Column(
            "metadata_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="资料授权绑定、Skill指令版本哈希、准备请求摘要",
        ),
        sa.Column(
            "report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="校验后的原始报告；未完成为空对象",
        ),
        sa.Column(
            "handling",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="人工问题处理、草案和应用审计；原报告不变",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="本人AI模型和配置版本；无密钥地址",
        ),
        sa.Column(
            "attempts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
            comment="每次固定输入执行的原始响应及安全诊断，失败仍保留",
        ),
        sa.Column(
            "error_code",
            sa.String(length=100),
            server_default="",
            nullable=False,
            comment="安全失败原因码；空表示无错误",
        ),
        sa.Column(
            "revision", sa.Integer(), server_default="1", nullable=False, comment="并发人工修订号"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="状态或处理更新时间，带时区",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["case_analysis_run.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "actor_id", "request_id", name="uq_case_analysis_request"
        ),
        comment="用例分析记录；固定输入、原报告与独立人工处理",
    )
    op.create_index(
        op.f("ix_case_analysis_run_project_id"), "case_analysis_run", ["project_id"], unique=False
    )
    op.create_table(
        "case_analysis_application",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="主键"),
        sa.Column("run_id", sa.BigInteger(), nullable=False, comment="所属分析记录ID"),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "actor_id", sa.BigInteger(), nullable=False, comment="统一确认人ID；本次设计审核人"
        ),
        sa.Column(
            "request_id",
            sa.String(length=36),
            nullable=False,
            comment="应用请求UUID；幂等防重复写入",
        ),
        sa.Column(
            "fingerprint", sa.String(length=64), nullable=False, comment="确认集合及草稿版本摘要"
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="QUEUED",
            nullable=False,
            comment="QUEUED排队、RUNNING逐条处理中、COMPLETED处理完成、FAILED暂停",
        ),
        sa.Column(
            "items",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
            comment="固定条目操作、版本、草稿、状态、失败原因和成功映射；每条独立事务",
        ),
        sa.Column(
            "error_code",
            sa.String(length=100),
            server_default="",
            nullable=False,
            comment="任务级失败码；撤权或失败审计不可保存时暂停",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["case_analysis_run.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "request_id", name="uq_case_analysis_application_request"),
        comment="人工统一确认的候选应用批次；逐条事务并保留成功和失败",
    )
    op.create_index(
        op.f("ix_case_analysis_application_run_id"),
        "case_analysis_application",
        ["run_id"],
        unique=False,
    )
    op.create_table(
        "case_analysis_chat_turn",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False, comment="主键"),
        sa.Column("run_id", sa.BigInteger(), nullable=False, comment="所属分析记录ID"),
        sa.Column(
            "actor_id", sa.BigInteger(), nullable=False, comment="本轮提问者ID；只使用其个人AI"
        ),
        sa.Column(
            "request_id", sa.String(length=36), nullable=False, comment="对话请求UUID；记录内幂等"
        ),
        sa.Column(
            "function_key",
            sa.String(length=200),
            server_default="",
            nullable=False,
            comment="固定功能ref；整体对话为空",
        ),
        sa.Column(
            "finding_key",
            sa.String(length=200),
            server_default="",
            nullable=False,
            comment="引用候选或问题key；无引用为空",
        ),
        sa.Column("question", sa.Text(), nullable=False, comment="本轮人工提问"),
        sa.Column(
            "answer",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="完整模型回答；未完成为空",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="本记录本功能固定输入、报告、人工处理与已完成历史",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="提问者AI名称、模型和版本；无密钥",
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="QUEUED",
            nullable=False,
            comment="QUEUED排队、RUNNING回答中、COMPLETED完成、FAILED失败、CANCELLED取消",
        ),
        sa.Column(
            "error_code",
            sa.String(length=100),
            server_default="",
            nullable=False,
            comment="安全失败原因码",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["case_analysis_run.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "request_id", name="uq_case_analysis_chat_turn_request"),
        comment="用例分析记录及功能隔离的本人AI对话轮次",
    )
    op.create_index(
        op.f("ix_case_analysis_chat_turn_run_id"),
        "case_analysis_chat_turn",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "uq_case_analysis_chat_active",
        "case_analysis_chat_turn",
        ["run_id", "function_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )


def downgrade() -> None:
    for table in ("case_analysis_run", "case_analysis_chat_turn", "case_analysis_application"):
        if op.get_bind().scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("用例分析已有历史记录，禁止删除表降级")
    op.drop_index(
        "uq_case_analysis_chat_active",
        table_name="case_analysis_chat_turn",
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )
    op.drop_index(op.f("ix_case_analysis_chat_turn_run_id"), table_name="case_analysis_chat_turn")
    op.drop_table("case_analysis_chat_turn")
    op.drop_index(
        op.f("ix_case_analysis_application_run_id"), table_name="case_analysis_application"
    )
    op.drop_table("case_analysis_application")
    op.drop_index(op.f("ix_case_analysis_run_project_id"), table_name="case_analysis_run")
    op.drop_table("case_analysis_run")
