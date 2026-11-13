"""Preserve fixed inputs while preparing and executing change-analysis batches."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20261022_42"
down_revision = "20261019_41"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_change_analysis_status", "change_analysis_task", type_="check")
    op.create_check_constraint(
        "ck_change_analysis_status",
        "change_analysis_task",
        "status IN ('QUEUED','RUNNING','PREPARED','COMPLETED','FAILED','CANCELLED')",
    )
    op.alter_column(
        "change_analysis_task",
        "status",
        existing_type=sa.String(16),
        comment="QUEUED排队/RUNNING准备或分析中/PREPARED待确认批次/COMPLETED完成或部分成果/FAILED失败/CANCELLED取消",
    )
    op.alter_column(
        "change_analysis_task",
        "report",
        existing_type=postgresql.JSONB(),
        comment="校验后的变更分析报告；可为标明未完成批次的部分成果，无成功成果时为空",
    )
    op.alter_column(
        "change_analysis_task",
        "metadata_snapshot",
        existing_type=postgresql.JSONB(),
        comment="创建方式、来源授权、原始选择、固定Skill及分批计划、成果和调用审计；不含凭据",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM change_analysis_task WHERE status='PREPARED')")
    ):
        raise RuntimeError("存在待确认分批计划，禁止回退其状态约束")
    op.drop_constraint("ck_change_analysis_status", "change_analysis_task", type_="check")
    op.create_check_constraint(
        "ck_change_analysis_status",
        "change_analysis_task",
        "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
    )
    op.alter_column(
        "change_analysis_task",
        "status",
        existing_type=sa.String(16),
        comment="QUEUED排队/RUNNING分析中/COMPLETED完成/FAILED失败/CANCELLED取消",
    )
    op.alter_column(
        "change_analysis_task",
        "report",
        existing_type=postgresql.JSONB(),
        comment="校验后的变更分析报告；失败或未完成为空对象",
    )
    op.alter_column(
        "change_analysis_task",
        "metadata_snapshot",
        existing_type=postgresql.JSONB(),
        comment="创建方式、来源授权关联、原始选择及Skill固定内容；不含凭据",
    )
