"""Queue a resume of the same analysis CLI history in the existing worker."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261120_46"
down_revision = "20261117_45"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_terminal_resume",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
            comment="续接进程主键及终端输出执行编号",
        ),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID",
        ),
        sa.Column(
            "record_kind",
            sa.String(16),
            nullable=False,
            comment="记录类型：requirements需求、code代码、changes变更、coverage用例",
        ),
        sa.Column(
            "record_id",
            sa.BigInteger(),
            nullable=False,
            comment="对应类型的分析任务ID；需求使用分析任务ID，任务可尚无正式报告",
        ),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="分析发起人账号ID；使用其固定个人CLI配置",
        ),
        sa.Column(
            "request_id",
            sa.String(36),
            nullable=False,
            comment="客户端续接请求UUID；同项目、类型和记录内幂等",
        ),
        sa.Column(
            "ai_config",
            JSONB(),
            nullable=False,
            comment="固定本人CLI方式、模型、强度及配置版本；不保存密钥",
        ),
        sa.Column("rows", sa.Integer(), nullable=False, comment="终端初始行数；范围8至120行"),
        sa.Column("cols", sa.Integer(), nullable=False, comment="终端初始列数；范围20至300列"),
        sa.Column(
            "status",
            sa.String(16),
            server_default="QUEUED",
            nullable=False,
            comment="QUEUED排队、RUNNING进程运行、COMPLETED正常退出、FAILED失败、CANCELLED停止",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            server_default="",
            nullable=False,
            comment="安全失败原因码；空字符串表示无错误",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="提交时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="状态更新时间，带时区",
        ),
        sa.CheckConstraint(
            "record_kind IN ('requirements','code','changes','coverage')",
            name="ck_analysis_terminal_resume_kind",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_analysis_terminal_resume_status",
        ),
        sa.UniqueConstraint(
            "project_id",
            "record_kind",
            "record_id",
            "request_id",
            name="uq_analysis_terminal_resume_request",
        ),
        comment="分析记录的原生CLI续接进程；同一分析可多次续接，原生模型轮次保存在私有会话",
    )
    op.create_index(
        "uq_analysis_terminal_resume_active",
        "analysis_terminal_resume",
        ["project_id", "record_kind", "record_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )


def downgrade():
    op.drop_table("analysis_terminal_resume")
