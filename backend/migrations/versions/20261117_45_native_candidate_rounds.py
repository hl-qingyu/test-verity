"""Describe native result rounds stored under the original generation record."""

from alembic import op

revision = "20261117_45"
down_revision = "20261111_44"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "COMMENT ON TABLE case_generation_ba"
        "tch IS '用例生成固定批次及同对话原生候选轮次；保留各次报告和审"
        "阅'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.batch_ref IS '固定计划或原生候选轮次标识；同生"
        "成记录内唯一'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.request_id IS 'AI调用或原生候选轮次保存请求"
        "UUID；按来源幂等'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.actor_id IS '本次AI调用或候选保存人ID；AI"
        "重试用本人配置'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.input_snapshot IS '本批或本轮固定校验输入"
        "；候选轮次保留业务原"
        "文并独立分配请求和建议命名空间'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.report IS '本批或本轮通过结构和引用校验的候选报告"
        "；根结构不可用时为空"
        "，局部问题另存待处理'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.attempts IS 'AI调用或原生候选保存的来源、状态"
        "、时间、安全诊断与审"
        "计；历史保留，不含密钥或上游原文'"
    )


def downgrade():
    op.execute(
        "COMMENT ON TABLE case_generation_batch IS '用例生成固定批次及原始报告；失败只人工重试'"
    )
    op.execute("COMMENT ON COLUMN case_generation_batch.batch_ref IS '固定计划批次标识；重试沿用'")
    op.execute("COMMENT ON COLUMN case_generation_batch.request_id IS '实际本次模型调用请求UUID'")
    op.execute(
        "COMMENT ON COLUMN case_generation_batch.actor_id IS '本次调用人ID；重试使用重试者AI'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.input_snapshot IS '本批固定输入；重试仅更"
        "换请求身份'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_batch.report IS '严格校验后的原始本批报告；未成功为空'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.attempts IS '每次调用的候选标识、状态、开始/进"
        "度时间及安全诊断；人"
        "工重试保留历史，不含密钥或上游原文'"
    )
