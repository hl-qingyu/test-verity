"""Use the preserved import number without changing internal identities."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_13"
down_revision = "20260914_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "managed_case",
        sa.Column(
            "imported_number",
            sa.Text(),
            nullable=True,
            comment="导入文件的用例编号原文，保留前导零且允许重复；空表示无原编号，展示内部顺序号",
        ),
    )
    op.alter_column(
        "managed_case", "number", comment="项目内自增内部顺序号，永久保留；无导入编号时作为展示编号"
    )
    op.execute("""
        UPDATE managed_case AS c SET imported_number = v.source->>'original_number'
        FROM case_version AS v
        WHERE v.case_id = c.id AND v.number = 1 AND v.source_kind = 'IMPORT'
          AND v.source->>'original_number' IS NOT NULL
          AND btrim(v.source->>'original_number', E' \\t\\n\\r') <> ''
    """)
    op.execute("""
        UPDATE case_library SET revision = revision + 1
        WHERE project_id IN (SELECT project_id FROM managed_case WHERE imported_number IS NOT NULL)
    """)


def downgrade() -> None:
    op.drop_column("managed_case", "imported_number")
    op.alter_column("managed_case", "number", comment="项目内自增展示编号，不使用导入原编号")
