"""documents

Revision ID: 20260912_06
Revises: 20260912_05
"""

import sqlalchemy as sa
from alembic import op

revision = "20260912_06"
down_revision = "20260912_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_group",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="ck_document_group_name"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "id", name="uq_document_group_project"),
        sa.UniqueConstraint("project_id", "name", name="uq_document_group_name"),
    )
    op.create_index(
        op.f("ix_document_group_project_id"), "document_group", ["project_id"], unique=False
    )
    op.create_table(
        "document_library",
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("project_id"),
    )
    op.create_table(
        "source_document",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.BigInteger(), nullable=True),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.CheckConstraint("current_version > 0", name="ck_source_document_version"),
        sa.ForeignKeyConstraint(
            ["project_id", "group_id"],
            ["document_group.project_id", "document_group.id"],
            name="fk_source_document_group",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "id", name="uq_source_document_project"),
    )
    op.create_index(
        op.f("ix_source_document_project_id"), "source_document", ["project_id"], unique=False
    )
    op.create_table(
        "document_version",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("project_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("extension", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=32), nullable=False),
        sa.Column("upload_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("number > 0", name="ck_document_version_number"),
        sa.CheckConstraint("size > 0", name="ck_document_size"),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user_account.id"],
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "document_id"],
            ["source_document.project_id", "source_document.id"],
            name="fk_document_version_document",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["project.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "number", name="uq_document_version_number"),
        sa.UniqueConstraint("project_id", "upload_id", name="uq_document_upload_id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_document_version_project_id"), "document_version", ["project_id"], unique=False
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM document_version) "
            "OR EXISTS (SELECT 1 FROM document_group)"
        )
    ):
        raise RuntimeError("Refusing to remove existing project documents or groups.")
    op.drop_index(op.f("ix_document_version_project_id"), table_name="document_version")
    op.drop_table("document_version")
    op.drop_index(op.f("ix_source_document_project_id"), table_name="source_document")
    op.drop_table("source_document")
    op.drop_table("document_library")
    op.drop_index(op.f("ix_document_group_project_id"), table_name="document_group")
    op.drop_table("document_group")
