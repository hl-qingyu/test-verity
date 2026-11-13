"""Independent human acceptance for fixed analysis reports."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261015_36"
down_revision = "20261014_35"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analysis_acceptance",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="验收记录主键"),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID",
        ),
        sa.Column(
            "module",
            sa.String(20),
            nullable=False,
            comment="分析模块：requirements/generate/coverage/code/changes",
        ),
        sa.Column(
            "record_id",
            sa.BigInteger(),
            nullable=False,
            comment="原分析记录ID；需求模块为风险报告ID，其他为任务或run ID",
        ),
        sa.Column(
            "source_token",
            sa.String(64),
            nullable=False,
            comment="固定原始报告内容标识；原报告变化时验收失效且不冒用旧结论",
        ),
        sa.Column(
            "state",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="逐条有效性与依据核验、回归可用性、人工遗漏与基准清单及范围结论",
        ),
        sa.Column(
            "history",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="每次人工保存的完整验收状态、操作者及时间审计；原件不覆盖",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="验收并发修订号；从1开始",
        ),
        sa.Column(
            "updated_by",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="最近保存验收的项目成员ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="首次人工验收保存时间；带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="最近人工验收保存时间；带时区",
        ),
        sa.UniqueConstraint(
            "project_id", "module", "record_id", name="uq_analysis_acceptance_record"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_analysis_acceptance_revision"),
        comment="五类AI分析的独立人工验收；不改变原报告与业务处理",
    )
    op.create_index("ix_analysis_acceptance_project_id", "analysis_acceptance", ["project_id"])


def downgrade():
    op.drop_index("ix_analysis_acceptance_project_id", table_name="analysis_acceptance")
    op.drop_table("analysis_acceptance")
