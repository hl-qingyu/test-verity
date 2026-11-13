"""Allow prototype repositories without changing existing classifications."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_17"
down_revision = "20260914_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_project_repo_kind", "project_repository", type_="check")
    op.create_check_constraint(
        "ck_project_repo_kind",
        "project_repository",
        "kind IN ('BACKEND', 'FLUTTER', 'WEB', 'PROTOTYPE', 'OTHER')",
    )
    op.alter_column(
        "project_repository",
        "kind",
        existing_type=sa.Text(),
        comment="代码类型：BACKEND后端、FLUTTER应用、WEB前端、PROTOTYPE原型、OTHER其他",
    )


def downgrade() -> None:
    # Existing prototype rows must be deliberately reclassified before rollback.
    op.drop_constraint("ck_project_repo_kind", "project_repository", type_="check")
    op.create_check_constraint(
        "ck_project_repo_kind",
        "project_repository",
        "kind IN ('BACKEND', 'FLUTTER', 'WEB', 'OTHER')",
    )
    op.alter_column(
        "project_repository",
        "kind",
        existing_type=sa.Text(),
        comment="代码类型：BACKEND后端、FLUTTER应用、WEB前端、OTHER其他",
    )
