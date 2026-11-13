"""Complete requirement risk analysis, scoped chat and manual risks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260917_26"
down_revision = "20260917_25"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requirement_risk_analysis",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="分析任务主键"),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID；任务及结果仅项目内共享",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="任务发起人ID，仅使用此人个人AI配置",
        ),
        sa.Column(
            "request_id",
            sa.String(36),
            nullable=False,
            comment="客户端提交UUID，同项目同用户幂等防止重复计费",
        ),
        sa.Column(
            "retry_of",
            sa.BigInteger(),
            sa.ForeignKey("requirement_risk_analysis.id"),
            nullable=True,
            comment="人工重试的原任务ID；首次分析为空",
        ),
        sa.Column("title", sa.String(200), nullable=False, comment="用户填写的分析记录名称"),
        sa.Column(
            "focus",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="本次补充关注范围；空表示所选资料",
        ),
        sa.Column(
            "selections",
            postgresql.JSONB(),
            nullable=False,
            comment="发起时选择的资料和固定版本清单；不包含密钥或资料正文",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="实际发送的v3输入和来源绑定快照；准备前为空对象",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="QUEUED",
            comment="QUEUED排队/RUNNING分析中/COMPLETED完成/FAILED失败/CANCELLED停止",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            nullable=False,
            server_default="",
            comment="安全失败原因码；无错误为空，不保存上游原始错误",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            nullable=False,
            comment="本人AI配置名称、模型和配置版本；不含地址和密钥",
        ),
        sa.Column(
            "report_id",
            sa.BigInteger(),
            sa.ForeignKey("requirement_risk_report.id"),
            nullable=True,
            comment="校验并入库后的风险报告ID；未完成时为空",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="任务创建时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="任务最近状态更新时间，带时区",
        ),
        sa.UniqueConstraint(
            "project_id", "actor_id", "request_id", name="uq_risk_analysis_request"
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_risk_analysis_status",
        ),
        comment="需求风险首次AI分析任务；固定用户选择和执行结果，不替代风险报告",
    )
    op.create_index(
        "ix_requirement_risk_analysis_project_id", "requirement_risk_analysis", ["project_id"]
    )

    op.drop_index("uq_chat_active", table_name="requirement_chat_turn")
    op.add_column(
        "requirement_chat_turn",
        sa.Column(
            "function_key",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="对话归属功能key；空字符串表示需求分析对话",
        ),
    )
    op.add_column(
        "requirement_chat_turn",
        sa.Column(
            "risk_key",
            sa.String(200),
            nullable=False,
            server_default="",
            comment="本轮明确引用的风险key；无风险引用为空字符串",
        ),
    )
    op.create_index(
        "uq_chat_active",
        "requirement_chat_turn",
        ["report_id", "function_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )

    op.create_table(
        "requirement_manual_risk",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="人工风险主键"),
        sa.Column(
            "report_id",
            sa.BigInteger(),
            sa.ForeignKey("requirement_risk_report.id"),
            nullable=False,
            comment="所属固定分析报告ID",
        ),
        sa.Column("function_key", sa.String(200), nullable=False, comment="所属报告内功能key"),
        sa.Column(
            "message_turn_id",
            sa.BigInteger(),
            sa.ForeignKey("requirement_chat_turn.id"),
            nullable=False,
            comment="来源AI回复轮次ID，用于返回对话追溯",
        ),
        sa.Column(
            "request_id", sa.String(36), nullable=False, comment="客户端提交UUID，同一报告内幂等"
        ),
        sa.Column("title", sa.String(500), nullable=False, comment="人工确认的风险标题"),
        sa.Column(
            "severity", sa.String(16), nullable=False, comment="风险等级HIGH高/MEDIUM中/LOW低"
        ),
        sa.Column(
            "risk_type", sa.String(32), nullable=False, comment="风险类型，沿用需求风险报告枚举"
        ),
        sa.Column("description", sa.Text(), nullable=False, comment="人工确认的问题描述"),
        sa.Column(
            "evidence",
            postgresql.JSONB(),
            nullable=False,
            comment="人工核对的固定原文来源、位置、摘录和观察",
        ),
        sa.Column("impact", sa.Text(), nullable=False, comment="可能造成的业务、实现或验收影响"),
        sa.Column("questions", postgresql.JSONB(), nullable=False, comment="待产品确认问题清单"),
        sa.Column(
            "improvement",
            postgresql.JSONB(),
            nullable=False,
            comment="完善建议、理由及取舍，仍需人工确认",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="PENDING",
            comment="当前处理状态",
        ),
        sa.Column(
            "note",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="当前人工处理结论；待确认时可为空",
        ),
        sa.Column(
            "history",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="人工处理状态与结论的追加历史",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="并发修订号，每次有效处理递增",
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="新增风险的操作人ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="风险确认入库时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="最近人工处理时间，带时区",
        ),
        sa.UniqueConstraint("report_id", "request_id", name="uq_manual_risk_request"),
        sa.CheckConstraint("severity IN ('HIGH','MEDIUM','LOW')", name="ck_manual_risk_severity"),
        sa.CheckConstraint(
            "status IN ('PENDING','NEEDS_INFO','RESOLVED','NOT_APPLICABLE')",
            name="ck_manual_risk_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_manual_risk_revision"),
        comment="从需求分析对话人工确认新增的风险；独立于AI原始报告并参与累计清单",
    )
    op.create_index(
        "ix_requirement_manual_risk_report_id", "requirement_manual_risk", ["report_id"]
    )


def downgrade():
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM requirement_risk_analysis) "
            "OR EXISTS (SELECT 1 FROM requirement_manual_risk)"
        )
    ):
        raise RuntimeError("已有需求分析任务或人工风险，不允许降级删除历史")
    op.drop_table("requirement_manual_risk")
    op.drop_index("uq_chat_active", table_name="requirement_chat_turn")
    op.drop_column("requirement_chat_turn", "risk_key")
    op.drop_column("requirement_chat_turn", "function_key")
    op.create_index(
        "uq_chat_active",
        "requirement_chat_turn",
        ["report_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )
    op.drop_table("requirement_risk_analysis")
