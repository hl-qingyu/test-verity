"""Skill administrator conversations; local file content remains authoritative."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261014_35"
down_revision = "20261014_34"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skill_chat_turn",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="对话轮次主键"),
        sa.Column(
            "actor_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="提问管理员ID；仅使用其本人AI配置",
        ),
        sa.Column("skill_key", sa.String(80), nullable=False, comment="固定白名单中的Skill标识"),
        sa.Column(
            "request_id", sa.String(36), nullable=False, comment="本人本Skill内请求UUID；防重复收费"
        ),
        sa.Column(
            "fingerprint",
            sa.String(64),
            nullable=False,
            comment="本轮问题、草稿、固定内容标识和引用的请求哈希",
        ),
        sa.Column("question", sa.Text(), nullable=False, comment="本轮管理员修改要求"),
        sa.Column(
            "answer",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="模型返回的修改说明；未完成为空",
        ),
        sa.Column(
            "candidate_body",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="待人工对照的完整建议正文；不包含文件元信息；未完成为空",
        ),
        sa.Column(
            "raw_response",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="本轮完整模型原始响应；失败保留；未接收为空",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="固定Skill正文、契约、所选参考、内容标识及已完成对话；不包含密钥",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="本人AI名称、模型及配置版本；不包含密钥",
        ),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="QUEUED",
            comment="QUEUED排队、RUNNING回答中、COMPLETED完成、FAILED失败、CANCELLED取消",
        ),
        sa.Column(
            "error_code",
            sa.String(100),
            nullable=False,
            server_default="",
            comment="安全失败原因码；空表示无错误",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="提问创建时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="最近状态变化时间；带时区",
        ),
        sa.UniqueConstraint("actor_id", "skill_key", "request_id", name="uq_skill_chat_request"),
        comment="按管理员账号和Skill隔离的辅助修改对话；建议不直接写文件",
    )
    op.create_index(
        "uq_skill_chat_active",
        "skill_chat_turn",
        ["actor_id", "skill_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('QUEUED','RUNNING')"),
    )


def downgrade():
    op.drop_table("skill_chat_turn")
