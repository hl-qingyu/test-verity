"""github_projects

Revision ID: 20260912_04
Revises: 20260911_03
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_04"
down_revision = "20260911_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Reviewed: only the confirmed GitHub and minimal project tables.
    op.create_table(
        "github_connection",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("resource_owner", sa.Text(), nullable=False),
        sa.Column("github_login", sa.Text(), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('personal', 'organization')", name="ck_github_kind"),
        sa.CheckConstraint("version > 0", name="ck_github_version"),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_github_connection_owner_id"), "github_connection", ["owner_id"], unique=False
    )
    op.create_table(
        "project",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("identifier", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identifier"),
    )
    op.create_index(op.f("ix_project_owner_id"), "project", ["owner_id"], unique=False)
    op.create_table(
        "github_repository",
        sa.Column("connection_id", sa.BigInteger(), nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=False),
        sa.Column("private", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["github_connection.id"],
        ),
        sa.PrimaryKeyConstraint("connection_id", "github_id"),
    )
    op.create_table(
        "project_member",
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("project_id", "user_id"),
    )
    op.create_table(
        "project_repository",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("default_branch", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('BACKEND', 'FLUTTER', 'WEB', 'OTHER')", name="ck_project_repo_kind"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["user_account.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "github_id", name="uq_project_repository"),
    )
    op.create_index(
        op.f("ix_project_repository_project_id"), "project_repository", ["project_id"], unique=False
    )


def downgrade() -> None:
    # Reviewed: only the confirmed GitHub and minimal project tables.
    op.drop_index(op.f("ix_project_repository_project_id"), table_name="project_repository")
    op.drop_table("project_repository")
    op.drop_table("project_member")
    op.drop_table("github_repository")
    op.drop_index(op.f("ix_project_owner_id"), table_name="project")
    op.drop_table("project")
    op.drop_index(op.f("ix_github_connection_owner_id"), table_name="github_connection")
    op.drop_table("github_connection")
