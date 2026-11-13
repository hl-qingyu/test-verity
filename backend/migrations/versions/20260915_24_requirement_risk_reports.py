"""Local Skill v3 input/result reports, independent human risk handling."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260915_24"
down_revision = "20260915_23"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requirement_risk_report",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True, comment="风险报告主键"),
        sa.Column(
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("project.id"),
            nullable=False,
            comment="所属项目ID；报告及处理记录仅项目内共享",
        ),
        sa.Column("title", sa.String(200), nullable=False, comment="用户填写的报告名称"),
        sa.Column(
            "input_filename",
            sa.String(200),
            nullable=False,
            comment="导入输入JSON文件名，不包含本机目录",
        ),
        sa.Column(
            "report_filename",
            sa.String(200),
            nullable=False,
            comment="导入结果JSON文件名，不包含本机目录",
        ),
        sa.Column(
            "sha256",
            sa.String(64),
            nullable=False,
            comment="规范化输入与结果内容SHA256；同项目相同内容幂等，不覆盖原报告",
        ),
        sa.Column(
            "input",
            postgresql.JSONB(),
            nullable=False,
            comment="Skill v3当次完整输入快照，含文字片段；图片和PDF原件引用项目已有资料",
        ),
        sa.Column(
            "report",
            postgresql.JSONB(),
            nullable=False,
            comment="校验通过的Skill v3风险报告；固定保存，不随人工处理改写",
        ),
        sa.Column(
            "bindings",
            postgresql.JSONB(),
            nullable=False,
            comment="输入来源ID到系统资料及固定版本的人工关联快照；不证明模型实际读取了原件",
        ),
        sa.Column(
            "handling",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
            comment="风险key对应人工处理状态、结论和历史；未出现的风险默认PENDING待确认",
        ),
        sa.Column(
            "revision",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="报告处理并发修订号，每次有效处理变更递增",
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("user_account.id"),
            nullable=False,
            comment="导入者账号ID",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="报告导入时间，带时区",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            comment="最近人工处理时间，带时区",
        ),
        sa.UniqueConstraint("project_id", "sha256", name="uq_risk_report_content"),
        sa.CheckConstraint("revision >= 1", name="ck_risk_report_revision"),
        comment="项目需求风险报告；保存本地导入的固定输入、结果与来源关联，人工处理独立留痕",
    )
    op.create_index(
        "ix_requirement_risk_report_project_id", "requirement_risk_report", ["project_id"]
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM requirement_risk_report)")):
        raise RuntimeError("风险报告存在，禁止降级丢失报告及处理记录")
    op.drop_table("requirement_risk_report")
