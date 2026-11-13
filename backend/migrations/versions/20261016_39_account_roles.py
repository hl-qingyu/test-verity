"""Add account roles with existing ordinary-user permissions."""

import sqlalchemy as sa
from alembic import op

revision = "20261016_39"
down_revision = "20261016_38"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_user_role", "user_account", type_="check")
    op.create_check_constraint(
        "ck_user_role",
        "user_account",
        "platform_role IN ('ADMIN', 'TEST', 'DEV', 'PRODUCT', 'MANAGER', 'USER')",
    )
    op.alter_column(
        "user_account",
        "platform_role",
        existing_type=sa.Text(),
        server_default="TEST",
        comment="平台角色：ADMIN管理员、TEST测试、DEV开发、PRODUCT产品、MANAGER经理；USER保留历史普通用户，非ADMIN沿用普通用户权限",
    )


def downgrade():
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM user_account WHERE platform_role NOT IN ('ADMIN', 'USER') LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("已有新增角色账号，禁止降级覆盖角色；须先由管理员明确调整账号角色")
    op.alter_column(
        "user_account",
        "platform_role",
        existing_type=sa.Text(),
        server_default="USER",
        comment="平台角色：ADMIN管理员，USER普通用户",
    )
    op.drop_constraint("ck_user_role", "user_account", type_="check")
    op.create_check_constraint("ck_user_role", "user_account", "platform_role IN ('ADMIN', 'USER')")
