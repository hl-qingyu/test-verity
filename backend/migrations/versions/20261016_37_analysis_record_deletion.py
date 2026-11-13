"""Preserve fixed evidence while hiding deleted analysis records."""

import sqlalchemy as sa
from alembic import op

revision = "20261016_37"
down_revision = "20261015_36"
branch_labels = None
depends_on = None

TABLES = (
    "requirement_risk_analysis",
    "requirement_risk_report",
    "code_analysis_task",
    "change_analysis_task",
    "case_generation_run",
    "case_analysis_run",
)


def upgrade():
    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="分析记录逻辑删除时间，带时区；空表示未删除",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "deleted_by",
                sa.BigInteger(),
                nullable=True,
                comment="删除本分析记录的用户ID；空表示未删除",
            ),
        )
        op.create_foreign_key(
            f"fk_{table}_deleted_by", table, "user_account", ["deleted_by"], ["id"]
        )


def downgrade():
    connection = op.get_bind()
    for table in TABLES:
        if connection.execute(
            sa.text(f'SELECT 1 FROM "{table}" WHERE deleted_at IS NOT NULL LIMIT 1')
        ).first():
            raise RuntimeError("已有分析删除审计，禁止降级丢失历史")
    for table in reversed(TABLES):
        op.drop_constraint(f"fk_{table}_deleted_by", table, type_="foreignkey")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
