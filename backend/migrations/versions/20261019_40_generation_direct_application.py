"""Keep direct application audits out of the worker queue; preserve historical records."""

import sqlalchemy as sa
from alembic import op

revision = "20261019_40"
down_revision = "20261016_39"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table_comment(
        "case_generation_application",
        "人工确认用例直接入库的结果审计；逐条事务，历史后台批次保留",
    )
    op.alter_column(
        "case_generation_application",
        "status",
        existing_type=sa.String(16),
        server_default="FAILED",
        comment="COMPLETED本次处理完成；FAILED提交中或未完成，已成功项保留；QUEUED和RUNNING仅历史后台记录",
    )
    op.alter_column(
        "case_generation_application",
        "error_code",
        existing_type=sa.String(100),
        comment="本次提交未完成原因；generation_submission_interrupted表示尚有未完成项，空表示处理完结；条目错误见items",
    )


def downgrade():
    op.create_table_comment(
        "case_generation_application",
        "人工统一确认的候选应用批次；逐条事务并保留成功和失败",
    )
    op.alter_column(
        "case_generation_application",
        "status",
        existing_type=sa.String(16),
        server_default="QUEUED",
        comment="QUEUED排队、RUNNING逐条处理中、COMPLETED处理完成、FAILED暂停",
    )
    op.alter_column(
        "case_generation_application",
        "error_code",
        existing_type=sa.String(100),
        comment="任务级失败码；撤权或失败审计不可保存时暂停",
    )
