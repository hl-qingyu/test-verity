"""analysis_diagnostics

Revision ID: 20260915_23
Revises: 20260915_22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_23"
down_revision = "20260915_22"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requirement_analysis",
        sa.Column(
            "diagnostics",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
            comment="分析阶段、耗时、读取计数及安全上游诊断；不含原文、思考内容或密钥，空对象为历史未记录",
        ),
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM requirement_analysis WHERE diagnostics <> '{}'::jsonb)"
        )
    ):
        raise RuntimeError("存在分析诊断记录，禁止降级丢失历史")
    op.drop_column("requirement_analysis", "diagnostics")
