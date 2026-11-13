"""Add standalone code analysis tasks."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260918_27"
down_revision = "20260917_26"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "code_analysis_task",
        sa.Column(
            "id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="代码分析任务主键"
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID；任务和结果仅项目内共享",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="发起人账号ID；仅使用此人的个人AI配置",
        ),
        sa.Column(
            "request_id",
            sa.String(36),
            nullable=False,
            comment="客户端请求UUID；同项目同用户幂等防止重复计费",
        ),
        sa.Column(
            "retry_of",
            sa.BigInteger(),
            sa.ForeignKey("code_analysis_task.id"),
            nullable=True,
            comment="人工重试的原任务ID；首次分析为空",
        ),
        sa.Column("title", sa.String(200), nullable=False, comment="用户填写的代码分析记录名称"),
        sa.Column(
            "focus", sa.Text(), nullable=False, server_default="", comment="本次代码检查关注点"
        ),
        sa.Column("targets", postgresql.JSONB(), nullable=False, comment="代码检查目标枚举列表"),
        sa.Column(
            "input_snapshot",
            postgresql.JSONB(),
            nullable=False,
            comment="固定代码、需求/原型文字和来源版本快照；不包含密钥",
        ),
        sa.Column(
            "report",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="校验后的代码分析报告；失败或未完成为空对象",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="QUEUED",
            comment="QUEUED排队/RUNNING分析中/COMPLETED完成/FAILED失败/CANCELLED取消",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            nullable=False,
            server_default="",
            comment="安全失败原因码；不保存上游原始错误",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            nullable=False,
            comment="个人AI配置名称、模型和版本；不含地址或密钥",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="人工处理并发修订号",
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
            "project_id", "actor_id", "request_id", name="uq_code_analysis_request"
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_code_analysis_status",
        ),
        comment="代码分析任务；保存固定代码输入、结构化发现和独立对话入口",
    )
    op.create_index("ix_code_analysis_task_project_id", "code_analysis_task", ["project_id"])


def downgrade():
    bind = op.get_bind()
    if bind.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM code_analysis_task)")):
        raise RuntimeError("已有代码分析任务，不允许降级删除历史")
    op.drop_index("ix_code_analysis_task_project_id", table_name="code_analysis_task")
    op.drop_table("code_analysis_task")
