"""requirement_analysis

Revision ID: 20260915_22
Revises: 20260914_21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_22"
down_revision = "20260914_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "requirement_analysis",
        sa.Column(
            "id",
            sa.BigInteger(),
            sa.Identity(always=False),
            nullable=False,
            comment="需求分析任务主键",
        ),
        sa.Column("project_id", sa.BigInteger(), nullable=False, comment="所属项目ID"),
        sa.Column(
            "actor_id", sa.BigInteger(), nullable=False, comment="发起人ID，仅使用本人AI配置"
        ),
        sa.Column(
            "request_id",
            sa.String(length=36),
            nullable=False,
            comment="发起请求UUID，同项目同用户重复请求返回原任务",
        ),
        sa.Column(
            "retry_of", sa.BigInteger(), nullable=True, comment="人工重试的原任务ID；首次为空"
        ),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            comment="任务状态QUEUED排队、PREPARING准备、RUNNING分析、COMPLETE完成、PARTIAL部分完成、FAILED失败、CANCELLED取消",
        ),
        sa.Column(
            "error",
            sa.Text(),
            server_default="",
            nullable=False,
            comment="安全错误码；空表示无执行错误，不保存上游正文",
        ),
        sa.Column(
            "request",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="固定发起选择、用途、个人配置版本和关注点；不含密钥",
        ),
        sa.Column(
            "ai_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="发起时个人AI配置脱敏元数据快照，不含密钥或密文",
        ),
        sa.Column(
            "skill",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="实际Skill及契约文本、版本和SHA256摘要快照",
        ),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            comment="固定分析输入、资料内容及位置、GitHub提交证据；二进制仅引用私有原件",
        ),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="校验通过的Skill v2结果；未完成或失败为空",
        ),
        sa.Column(
            "adoptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="人工采纳请求、操作者、时间及功能候选到正式记录的固定映射",
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
            comment="最近状态更新或领取时间，带时区",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED','PREPARING','RUNNING','COMPLETE','PARTIAL','FAILED','CANCELLED')",
            name="ck_analysis_status",
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
            ["retry_of"],
            ["requirement_analysis.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "actor_id", "request_id", name="uq_analysis_request"),
        comment="项目共享需求分析任务、固定输入证据及人工采纳记录；不记录执行通过",
    )
    op.create_index(
        op.f("ix_requirement_analysis_project_id"),
        "requirement_analysis",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_requirement_analysis_status"), "requirement_analysis", ["status"], unique=False
    )
    op.add_column(
        "requirement_rule",
        sa.Column(
            "analysis_id",
            sa.BigInteger(),
            nullable=True,
            comment="生成来源需求分析任务ID；空为人工创建，任务证据永久保留",
        ),
    )
    op.add_column(
        "requirement_rule",
        sa.Column(
            "analysis_candidate_key",
            sa.Text(),
            nullable=True,
            comment="来源任务内候选标识；空为人工创建，不随人工修订改变",
        ),
    )
    op.create_foreign_key(
        "fk_requirement_analysis_origin",
        "requirement_rule",
        "requirement_analysis",
        ["analysis_id"],
        ["id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM requirement_analysis)")):
        raise RuntimeError("存在需求分析历史，禁止降级删除")
    op.drop_constraint("fk_requirement_analysis_origin", "requirement_rule", type_="foreignkey")
    op.drop_column("requirement_rule", "analysis_candidate_key")
    op.drop_column("requirement_rule", "analysis_id")
    op.drop_index(op.f("ix_requirement_analysis_status"), table_name="requirement_analysis")
    op.drop_index(op.f("ix_requirement_analysis_project_id"), table_name="requirement_analysis")
    op.drop_table("requirement_analysis")
