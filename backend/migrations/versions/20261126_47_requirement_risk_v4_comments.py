"""Document the versioned requirement-risk snapshots and platform-derived coverage."""

from alembic import op

revision = "20261126_47"
down_revision = "20261120_46"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "requirement_risk_report",
        "input",
        comment="当次完整固定输入及契约版本，含文字片段；图片和PDF原件引用项目已有资料",
    )
    op.alter_column(
        "requirement_risk_report",
        "report",
        comment="校验后按契约版本保存的风险报告；v4覆盖及状态由平台计算，人工处理独立保存",
    )
    op.alter_column(
        "requirement_risk_analysis",
        "context",
        comment="当次固定输入、来源绑定、Skill版本及校验记录；排队时可仅有Skill快照，缺省为空对象",
    )


def downgrade():
    op.alter_column(
        "requirement_risk_analysis",
        "context",
        comment="当次v3输入、来源绑定、校正和人工核对提示快照；准备前为空对象",
    )
    op.alter_column(
        "requirement_risk_report",
        "report",
        comment="结构及引用校验通过的Skill v3风险报告；证据与覆盖提示待人工核对，不随处理改写",
    )
    op.alter_column(
        "requirement_risk_report",
        "input",
        comment="Skill v3当次完整输入快照，含文字片段；图片和PDF原件引用项目已有资料",
    )
