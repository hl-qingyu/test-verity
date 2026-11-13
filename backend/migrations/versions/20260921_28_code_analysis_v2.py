"""Code analysis v2 provenance, independent handling and conversations."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260921_28"
down_revision = "20260918_27"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "code_analysis_task",
        sa.Column(
            "metadata_snapshot",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="创建方式、来源授权关联、原始选择及Skill固定内容；不含凭据",
        ),
    )
    op.add_column(
        "code_analysis_task",
        sa.Column(
            "handling",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="按发现key保存独立人工处理和审计历史；不修改原报告",
        ),
    )
    op.create_table(
        "code_analysis_chat_turn",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="代码分析对话轮次主键"
        ),
        sa.Column(
            "task_id",
            sa.BigInteger(),
            sa.ForeignKey("code_analysis_task.id"),
            nullable=False,
            comment="所属代码分析记录ID",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="本轮发起人ID；使用其个人AI配置",
        ),
        sa.Column(
            "request_id",
            sa.String(36),
            nullable=False,
            comment="本轮请求UUID；同分析内幂等防重复计费",
        ),
        sa.Column(
            "finding_key",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="本轮引用发现key；未引用为空",
        ),
        sa.Column("question", sa.Text(), nullable=False, comment="本轮用户提问"),
        sa.Column(
            "answer",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="完整AI回答；未成功完成为空",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="QUEUED",
            comment="QUEUED排队/RUNNING回答中/COMPLETED完成/FAILED失败/CANCELLED取消",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            nullable=False,
            server_default="",
            comment="安全错误码；不保存上游原始错误",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            comment="本轮固定代码报告、处理状态和已完成对话历史快照",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            nullable=False,
            comment="提问者AI名称、模型及版本；不含地址或密钥",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="对话创建时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="对话状态更新时间，带时区",
        ),
        sa.UniqueConstraint("task_id", "request_id", name="uq_code_chat_request"),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_code_chat_status",
        ),
        comment="代码分析独立对话轮次；仅包含本分析固定输入、发现与历史，使用提问者个人AI",
    )
    op.create_index("ix_code_analysis_chat_turn_task_id", "code_analysis_chat_turn", ["task_id"])
    op.create_index(
        "uq_code_chat_active",
        "code_analysis_chat_turn",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS(SELECT 1 FROM code_analysis_chat_turn) OR EXISTS("
            "SELECT 1 FROM code_analysis_task "
            "WHERE metadata_snapshot <> '{}'::jsonb OR handling <> '{}'::jsonb)"
        )
    ):
        raise RuntimeError("已有代码分析v2历史，禁止降级删除")
    op.drop_table("code_analysis_chat_turn")
    op.drop_column("code_analysis_task", "handling")
    op.drop_column("code_analysis_task", "metadata_snapshot")
