"""Document generation attempt progress and safe diagnostics in the database."""

from alembic import op

revision = "20261012_33"
down_revision = "20261012_32"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "case_generation_batch",
        "attempts",
        comment="每次调用的候选标识、状态、开始/进度时间及安全诊断；人工重试保留历史，不含密钥或上游原文",
    )


def downgrade():
    op.alter_column(
        "case_generation_batch",
        "attempts",
        comment="原始候选路径标识及人工重试尝试历史；不覆盖历史",
    )
