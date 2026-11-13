"""Version local prototype directories without replacing earlier material versions."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261019_41"
down_revision = "20261019_40"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_source_document_kind", "source_document", type_="check")
    op.create_check_constraint(
        "ck_source_document_kind",
        "source_document",
        "kind IN ('FILE','DIRECTORY','GITHUB','LINK') AND (kind = 'FILE' OR purpose = 'PROTOTYPE')",
    )
    op.alter_column(
        "source_document",
        "kind",
        existing_type=sa.Text(),
        comment="来源类型：FILE上传文件、DIRECTORY上传目录、GITHUB实时仓库、LINK实时链接",
    )
    op.add_column(
        "document_version",
        sa.Column(
            "directory_files",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="DIRECTORY固定版本文件索引：相对path、sha256、size字节、extension及私有storage_key；其他版本为空数组",
        ),
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM source_document WHERE kind='DIRECTORY')")
    ):
        raise RuntimeError("目录资料仍有历史版本，禁止丢失文件索引")
    op.drop_column("document_version", "directory_files")
    op.drop_constraint("ck_source_document_kind", "source_document", type_="check")
    op.create_check_constraint(
        "ck_source_document_kind",
        "source_document",
        "kind IN ('FILE','GITHUB','LINK') AND (kind = 'FILE' OR purpose = 'PROTOTYPE')",
    )
    op.alter_column(
        "source_document",
        "kind",
        existing_type=sa.Text(),
        comment="来源类型：FILE上传文件、GITHUB实时仓库、LINK实时链接",
    )
