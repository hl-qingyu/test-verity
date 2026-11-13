"""Allow mixed-owner connections, preserving existing credentials and selections."""

import sqlalchemy as sa
from alembic import op

revision = "20260912_05"
down_revision = "20260912_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_github_kind", "github_connection", type_="check")
    op.create_check_constraint(
        "ck_github_kind", "github_connection", "kind IN ('personal', 'organization', 'automatic')"
    )
    op.add_column(
        "github_repository",
        sa.Column("owner_type", sa.Text(), server_default="User", nullable=False),
    )
    op.execute(
        "UPDATE github_repository r SET owner_type = 'Organization' "
        "FROM github_connection c WHERE r.connection_id = c.id AND c.kind = 'organization'"
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM github_connection WHERE kind = 'automatic')")
    ):
        raise RuntimeError("Cannot downgrade while mixed-owner connections exist.")
    op.drop_column("github_repository", "owner_type")
    op.drop_constraint("ck_github_kind", "github_connection", type_="check")
    op.create_check_constraint(
        "ck_github_kind", "github_connection", "kind IN ('personal', 'organization')"
    )
