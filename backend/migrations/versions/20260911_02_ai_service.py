"""Personal and platform AI connections; preserve existing users and sessions."""

import sqlalchemy as sa
from alembic import op

revision = "20260911_02"
down_revision = "20260911_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_account", sa.Column("ai_source", sa.Text(), server_default="PLATFORM", nullable=False)
    )
    op.add_column(
        "user_account",
        sa.Column("ai_source_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_check_constraint(
        "ck_user_ai_source", "user_account", "ai_source IN ('PLATFORM', 'PERSONAL')"
    )
    op.create_table(
        "ai_connection",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=False),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("user_account.id"), unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("encrypted_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = COALESCE(owner_id, 0)", name="ck_ai_owner"),
        sa.CheckConstraint("version > 0", name="ck_ai_version"),
    )


def downgrade() -> None:
    # Explicit rollback removes AI credentials; never execute automatically.
    op.drop_table("ai_connection")
    op.drop_constraint("ck_user_ai_source", "user_account", type_="check")
    op.drop_column("user_account", "ai_source_version")
    op.drop_column("user_account", "ai_source")
