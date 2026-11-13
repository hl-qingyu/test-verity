"""Retire shared AI configuration without deleting credentials or historical fields."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_15"
down_revision = "20260914_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "user_account",
        "ai_source",
        existing_type=sa.Text(),
        server_default="PERSONAL",
        comment="历史AI来源字段，PLATFORM平台、PERSONAL个人；现已停用，仅使用用户个人配置",
    )
    op.alter_column(
        "user_account",
        "ai_source_version",
        existing_type=sa.Integer(),
        comment="历史AI来源版本号，已停用，不参与当前配置选择",
    )
    op.create_table_comment(
        "ai_connection", "用户个人AI配置，密钥加密保存；历史平台记录保留但禁止使用"
    )
    op.alter_column(
        "ai_connection",
        "id",
        existing_type=sa.BigInteger(),
        comment="配置主键为所属用户ID；0仅为停用的历史平台记录",
    )
    op.alter_column(
        "ai_connection",
        "owner_id",
        existing_type=sa.BigInteger(),
        comment="所属用户ID；为空仅表示停用的历史平台记录",
    )


def downgrade() -> None:
    op.alter_column(
        "user_account",
        "ai_source",
        existing_type=sa.Text(),
        server_default="PLATFORM",
        comment="当前AI使用来源：PLATFORM平台统一，PERSONAL个人配置",
    )
    op.alter_column(
        "user_account",
        "ai_source_version",
        existing_type=sa.Integer(),
        comment="AI使用来源的乐观锁版本号",
    )
    op.create_table_comment("ai_connection", "个人或平台统一的AI服务配置，密钥以密文保存")
    op.alter_column(
        "ai_connection",
        "id",
        existing_type=sa.BigInteger(),
        comment="配置主键：0为平台统一配置，其他值为所属用户ID",
    )
    op.alter_column(
        "ai_connection",
        "owner_id",
        existing_type=sa.BigInteger(),
        comment="所属用户ID；平台统一配置为空",
    )
