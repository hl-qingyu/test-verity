"""Register personal browser directory associations without uploading source content."""

import sqlalchemy as sa
from alembic import op

revision = "20260914_19"
down_revision = "20260914_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "local_code_source",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="关联主键"),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID",
        ),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="目录授权所属用户ID",
        ),
        sa.Column(
            "client_id",
            sa.Text(),
            nullable=False,
            comment="浏览器生成的稳定关联UUID，用于重复提交去重",
        ),
        sa.Column("name", sa.Text(), nullable=False, comment="本地代码来源显示名称"),
        sa.Column(
            "directory_name", sa.Text(), nullable=False, comment="授权目录的末级名称，不是绝对路径"
        ),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="代码类型：BACKEND后端、FLUTTER应用、WEB前端、PROTOTYPE原型、OTHER其他",
        ),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="元数据乐观锁版本号",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="关联创建时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
            comment="元数据最近更新时间，带时区",
        ),
        sa.UniqueConstraint("project_id", "owner_id", "client_id", name="uq_local_code_client"),
        sa.CheckConstraint(
            "kind IN ('BACKEND', 'FLUTTER', 'WEB', 'PROTOTYPE', 'OTHER')", name="ck_local_code_kind"
        ),
        sa.CheckConstraint("version > 0", name="ck_local_code_version"),
        comment="用户本机代码目录的项目关联，仅存元数据，不保存代码或磁盘路径",
    )
    op.create_index("ix_local_code_source_project_id", "local_code_source", ["project_id"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM local_code_source")):
        raise RuntimeError("本地代码关联已有记录，拒绝删除历史数据")
    op.drop_table("local_code_source")
