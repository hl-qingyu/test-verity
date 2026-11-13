"""Create only the confirmed user and session tables.

Revision ID: 20260911_01
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "20260911_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("login_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("platform_role", sa.Text(), server_default="USER", nullable=False),
        sa.Column("status", sa.Text(), server_default="ACTIVE", nullable=False),
        sa.Column("failed_login_count", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("user_account.id")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("user_account.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("login_name"),
        sa.CheckConstraint("login_name ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'", name="ck_user_login_name"),
        sa.CheckConstraint("platform_role IN ('ADMIN', 'USER')", name="ck_user_role"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED', 'DELETED')", name="ck_user_status"),
        sa.CheckConstraint("failed_login_count BETWEEN 0 AND 5", name="ck_user_failed_login_count"),
        sa.CheckConstraint("char_length(display_name) BETWEEN 1 AND 80", name="ck_user_name"),
    )
    op.create_table(
        "user_session",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("user_account.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("token_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_session_expiry"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_session_token_hash"),
    )
    op.create_index("ix_user_session_user_id", "user_session", ["user_id"])
    op.create_index("ix_user_session_expires_at", "user_session", ["expires_at"])


def downgrade() -> None:
    # Explicit rollback destroys login history; never run automatically.
    op.drop_table("user_session")
    op.drop_table("user_account")
