"""Clarify that AI risk reports may contain human-review warnings."""

from alembic import op

revision = "20260924_29"
down_revision = "20260921_28"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "COMMENT ON TABLE requirement_risk_report IS "
        "'项目需求风险报告；保存导入或AI分析的固定输入、结果与来源关联，人工处理独立留痕'"
    )
    op.alter_column(
        "requirement_risk_report",
        "report",
        comment="结构及引用校验通过的Skill v3风险报告；证据与覆盖提示待人工核对，不随处理改写",
    )
    op.alter_column(
        "requirement_risk_analysis",
        "context",
        comment="当次v3输入、来源绑定、校正和人工核对提示快照；准备前为空对象",
    )
    op.alter_column(
        "requirement_chat_turn",
        "context",
        comment="本轮固定资料、风险、人工核对提示、处理与已完成消息快照；不含密钥",
    )


def downgrade():
    op.alter_column(
        "requirement_chat_turn",
        "context",
        comment="本轮固定资料、风险、处理与已完成历史消息快照；不含密钥",
    )
    op.alter_column(
        "requirement_risk_analysis",
        "context",
        comment="实际发送的v3输入和来源绑定快照；准备前为空对象",
    )
    op.alter_column(
        "requirement_risk_report",
        "report",
        comment="校验通过的Skill v3风险报告；固定保存，不随人工处理改写",
    )
    op.execute(
        "COMMENT ON TABLE requirement_risk_report IS "
        "'项目需求风险报告；保存本地导入的固定输入、结果与来源关联，人工处理独立留痕'"
    )
