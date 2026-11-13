"""Hide deleted projects while preserving all associated records."""

import sqlalchemy as sa
from alembic import op

revision = "20261016_38"
down_revision = "20261016_37"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "project",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="项目逻辑删除时间，带时区；空表示未删除",
        ),
    )
    op.add_column(
        "project",
        sa.Column(
            "deleted_by", sa.BigInteger(), nullable=True, comment="删除项目的用户ID；空表示未删除"
        ),
    )
    op.create_foreign_key(
        "fk_project_deleted_by", "project", "user_account", ["deleted_by"], ["id"]
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM project WHERE deleted_at IS NOT NULL LIMIT 1"))
        .first()
    ):
        raise RuntimeError("已有项目删除审计，禁止降级丢失历史")
    op.drop_constraint("fk_project_deleted_by", "project", type_="foreignkey")
    op.drop_column("project", "deleted_by")
    op.drop_column("project", "deleted_at")
