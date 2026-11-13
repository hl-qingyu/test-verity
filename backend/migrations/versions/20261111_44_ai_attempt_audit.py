"""AI attempt uniqueness and explicit immutable transport snapshot comments."""

from alembic import op

revision = "20261111_44"
down_revision = "20261111_43"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint(
        "uq_ai_call_attempt", "ai_call_reservation", ["kind", "task_id", "request_id"]
    )
    op.execute(
        "COMMENT ON COLUMN requirement_risk_"
        "analysis.ai_config IS '固定AI方式、本人配置名"
        "称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN code_analysis_tas"
        "k.ai_config IS '固定AI方式、本人配置名称/模型/强度"
        "/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN code_analysis_cha"
        "t_turn.ai_config IS '固定AI方式、本人配置名称/"
        "模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN change_analysis_t"
        "ask.ai_config IS '固定AI方式、本人配置名称/模型/"
        "强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN change_analysis_c"
        "hat_turn.ai_config IS '固定AI方式、本人配置名"
        "称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN requirement_chat_"
        "turn.ai_config IS '固定AI方式、本人配置名称/模型"
        "/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN requirement_analy"
        "sis.ai_config IS '固定AI方式、本人配置名称/模型/"
        "强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_b"
        "atch.ai_config IS '固定AI方式、本人配置名称/模型"
        "/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN case_generation_c"
        "hat_turn.ai_config IS '固定AI方式、本人配置名"
        "称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN case_analysis_run"
        ".ai_config IS '固定AI方式、本人配置名称/模型/强度/"
        "修订号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN skill_chat_turn.a"
        "i_config IS '固定AI方式、本人配置名称/模型/强度/修订"
        "号及客户端版本；历史缺方式按API，不含密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN case_analysis_cha"
        "t_turn.ai_config IS '固定AI方式、本人配置名称/"
        "模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥'"
    )


def downgrade():
    raise RuntimeError("调用审计降级需人工审查")
