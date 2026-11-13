"""Case generation, fixed batches, reviewed applications and lifecycle history."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261012_31"
down_revision = "20261010_30"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_generation_run",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="主键"),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="发起人ID；使用本人AI",
        ),
        sa.Column(
            "request_id", sa.String(36), nullable=False, comment="准备请求UUID；同项目同用户幂等"
        ),
        sa.Column("title", sa.String(200), nullable=False, comment="生成记录名称"),
        sa.Column("mode", sa.String(16), nullable=False, comment="INITIAL首次生成或UPDATE维护"),
        sa.Column(
            "status",
            sa.String(16),
            server_default="PREPARED",
            nullable=False,
            comment="PREPARED待确认、QUEUED排队、RUNNING处理中、COMPLETED完成、FAILED失败、CANCELLED取消",
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="完整固定生成输入；不含凭据",
        ),
        sa.Column(
            "metadata_snapshot",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="固定Skill、来源绑定和请求摘要；不含密钥",
        ),
        sa.Column(
            "handling",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="候选人工草稿、澄清、应用映射及审计；原报告不改写",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="人工操作并发修订号",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        sa.UniqueConstraint(
            "project_id", "actor_id", "request_id", name="uq_case_generation_run_request"
        ),
        comment="用例生成记录及固定准备输入、分批计划、独立人工处理",
    )
    op.create_index("ix_case_generation_run_project_id", "case_generation_run", ["project_id"])
    op.create_table(
        "case_generation_batch",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="主键"),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("case_generation_run.id"),
            nullable=False,
            comment="所属生成记录ID",
        ),
        sa.Column(
            "batch_ref", sa.String(200), nullable=False, comment="固定计划批次标识；重试沿用"
        ),
        sa.Column("request_id", sa.String(36), nullable=False, comment="实际本次模型调用请求UUID"),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="本次调用人ID；重试使用重试者AI",
        ),
        sa.Column(
            "status",
            sa.String(16),
            server_default="PREPARED",
            nullable=False,
            comment="PREPARED未发起、QUEUED排队、RUNNING处理中、COMPLETED完成、FAILED失败、CANCELLED取消",
        ),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="本批固定输入；重试仅更换请求身份",
        ),
        sa.Column(
            "report",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="严格校验后的原始本批报告；未成功为空",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="本人AI配置名称、模型、版本；无密钥",
        ),
        sa.Column(
            "attempts",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
            comment="原始候选路径标识及人工重试尝试历史；不覆盖历史",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            server_default="",
            nullable=False,
            comment="安全失败码；无原始上游错误",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        sa.UniqueConstraint("run_id", "batch_ref", name="uq_case_generation_batch_request"),
        comment="用例生成固定批次及原始报告；失败只人工重试",
    )
    op.create_index("ix_case_generation_batch_run_id", "case_generation_batch", ["run_id"])
    op.create_table(
        "case_generation_application",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="主键"),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("case_generation_run.id"),
            nullable=False,
            comment="所属生成记录ID",
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="统一确认人ID；本次设计审核人",
        ),
        sa.Column(
            "request_id", sa.String(36), nullable=False, comment="应用请求UUID；幂等防重复写入"
        ),
        sa.Column("fingerprint", sa.String(64), nullable=False, comment="确认集合及草稿版本摘要"),
        sa.Column(
            "status",
            sa.String(16),
            server_default="QUEUED",
            nullable=False,
            comment="QUEUED排队、RUNNING逐条处理中、COMPLETED处理完成、FAILED暂停",
        ),
        sa.Column(
            "items",
            postgresql.JSONB(),
            server_default="[]",
            nullable=False,
            comment="固定条目操作、版本、草稿、状态、失败原因和成功映射；每条独立事务",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            server_default="",
            nullable=False,
            comment="任务级失败码；撤权或失败审计不可保存时暂停",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        sa.UniqueConstraint("run_id", "request_id", name="uq_case_generation_application_request"),
        comment="人工统一确认的候选应用批次；逐条事务并保留成功和失败",
    )
    op.create_index(
        "ix_case_generation_application_run_id", "case_generation_application", ["run_id"]
    )
    op.create_table(
        "case_generation_chat_turn",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="主键"),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("case_generation_run.id"),
            nullable=False,
            comment="所属生成记录ID",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="本轮提问者ID；只使用其个人AI",
        ),
        sa.Column("request_id", sa.String(36), nullable=False, comment="对话请求UUID；记录内幂等"),
        sa.Column(
            "function_key",
            sa.String(200),
            server_default="",
            nullable=False,
            comment="固定功能ref；整体对话为空",
        ),
        sa.Column(
            "finding_key",
            sa.String(200),
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
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="本记录本功能固定输入、报告、人工处理与已完成历史",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="提问者AI名称、模型和版本；无密钥",
        ),
        sa.Column(
            "status",
            sa.String(16),
            server_default="QUEUED",
            nullable=False,
            comment="QUEUED排队、RUNNING回答中、COMPLETED完成、FAILED失败、CANCELLED取消",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            server_default="",
            nullable=False,
            comment="安全失败原因码",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        sa.UniqueConstraint("run_id", "request_id", name="uq_case_generation_chat_turn_request"),
        sa.Index(
            "uq_generation_chat_active",
            "run_id",
            "function_key",
            unique=True,
            postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
        ),
        comment="用例生成记录及功能隔离的本人AI对话轮次",
    )
    op.create_index("ix_case_generation_chat_turn_run_id", "case_generation_chat_turn", ["run_id"])
    op.create_table(
        "case_lifecycle_record",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="主键"),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID",
        ),
        sa.Column(
            "case_id",
            sa.BigInteger(),
            sa.ForeignKey("managed_case.id"),
            nullable=False,
            comment="所属用例ID",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="人工启停操作者ID",
        ),
        sa.Column("lifecycle", sa.String(16), nullable=False, comment="ACTIVE活动或RETIRED停用"),
        sa.Column("reason", sa.Text(), nullable=False, comment="人工启停理由"),
        sa.Column(
            "basis",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="来源生成记录及候选、或人工操作依据",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="最近状态时间；带时区",
        ),
        comment="用例人工启停历史；不改变设计版本和旧测试结果",
    )
    op.add_column(
        "managed_case",
        sa.Column(
            "lifecycle",
            sa.String(16),
            nullable=False,
            server_default="ACTIVE",
            comment="用例生命周期ACTIVE活动或RETIRED停用；独立于测试结果和逻辑删除",
        ),
    )
    op.create_check_constraint(
        "ck_case_lifecycle", "managed_case", "lifecycle IN ('ACTIVE','RETIRED')"
    )
    op.alter_column(
        "case_version", "source_kind", comment="来源MANUAL人工、IMPORT导入或GENERATION人工采纳生成"
    )
    op.alter_column(
        "case_record",
        "source_kind",
        comment="记录来源MANUAL人工、IMPORT导入或GENERATION人工采纳生成",
    )


def downgrade():
    op.alter_column("case_record", "source_kind", comment="记录来源MANUAL人工或IMPORT导入")
    op.alter_column("case_version", "source_kind", comment="来源类型：MANUAL人工创建、IMPORT导入")
    op.drop_constraint("ck_case_lifecycle", "managed_case", type_="check")
    op.drop_column("managed_case", "lifecycle")
    op.drop_table("case_lifecycle_record")
    op.drop_table("case_generation_chat_turn")
    op.drop_table("case_generation_application")
    op.drop_table("case_generation_batch")
    op.drop_table("case_generation_run")
