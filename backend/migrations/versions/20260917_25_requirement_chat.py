"""Persistent requirement conversations and a worker-owned queue."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_25"
down_revision = "20260915_24"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requirement_chat_turn",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="对话轮次主键及顺序"
        ),
        sa.Column(
            "report_id",
            sa.BigInteger(),
            sa.ForeignKey("requirement_risk_report.id"),
            nullable=False,
            comment="关联的固定需求分析结果ID，也是需求分析对话归属",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="本轮发起人ID，仅使用此人AI配置",
        ),
        sa.Column(
            "request_id",
            sa.String(36),
            nullable=False,
            comment="客户端提交UUID，同一分析内幂等防重复计费",
        ),
        sa.Column("question", sa.Text(), nullable=False, comment="用户本轮提问正文"),
        sa.Column(
            "answer",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="完整AI回复；未完成或失败为空，不将部分回复标记成功",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="QUEUED",
            comment="QUEUED排队/RUNNING回答中/COMPLETED完成/FAILED失败/CANCELLED停止",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            nullable=False,
            server_default="",
            comment="安全失败原因码；无错误为空，不保存上游原始错误",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            comment="本轮固定资料、风险、处理与已完成历史消息快照；不含密钥",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            nullable=False,
            comment="本人AI配置名称、模型和配置版本；不含地址和密钥",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="轮次提交时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="轮次最近状态更新时间，带时区",
        ),
        sa.UniqueConstraint("report_id", "request_id", name="uq_chat_request"),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')", name="ck_chat_status"
        ),
        comment="需求分析对话轮次；按分析结果共享历史，独立Worker调用本人AI，不修改风险",
    )
    op.create_index("ix_requirement_chat_turn_report_id", "requirement_chat_turn", ["report_id"])
    op.create_index(
        "uq_chat_active",
        "requirement_chat_turn",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM requirement_chat_turn)")):
        raise RuntimeError("已有对话记录，不允许降级删除历史")
    op.drop_table("requirement_chat_turn")
