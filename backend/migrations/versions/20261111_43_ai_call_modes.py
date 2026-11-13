"""Independent personal CLI settings, preference and shared call reservations."""

from alembic import op

revision = "20261111_43"
down_revision = "20261022_42"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "\nCREATE TABLE ai_cli_connection (\n\t"
        "owner_id BIGINT NOT NULL, \n\tname TE"
        "XT NOT NULL, \n\tbase_url TEXT NOT NU"
        "LL, \n\tmodel TEXT NOT NULL, \n\treason"
        "ing_effort TEXT DEFAULT 'default' N"
        "OT NULL, \n\tencrypted_key TEXT NOT N"
        "ULL, \n\tversion INTEGER NOT NULL, \n\t"
        "updated_at TIMESTAMP WITH TIME ZONE"
        " DEFAULT now() NOT NULL, \n\tPRIMARY "
        "KEY (owner_id), \n\tCONSTRAINT ck_ai_"
        "cli_version CHECK (version > 0), \n\t"
        "CONSTRAINT ck_ai_cli_effort CHECK ("
        "reasoning_effort IN ('default','non"
        "e','minimal','low','medium','high',"
        "'xhigh','max','ultra')), \n\tFOREIGN "
        "KEY(owner_id) REFERENCES user_accou"
        "nt (id)\n)\n\n"
    )
    op.execute(
        "COMMENT ON TABLE ai_cli_connection "
        "IS '用户独立的Codex CLI配置；不复制API配置或服务器个人"
        "登录态'"
    )
    op.execute("COMMENT ON COLUMN ai_cli_connection.owner_id IS '所属真实用户ID，每人一份CLI配置'")
    op.execute("COMMENT ON COLUMN ai_cli_connection.name IS 'CLI个人配置显示名称'")
    op.execute("COMMENT ON COLUMN ai_cli_connection.base_url IS '用户指定的HTTPS模型服务基础地址'")
    op.execute(
        "COMMENT ON COLUMN ai_cli_connection.model IS 'CLI模型标识；不使用API目录推断兼容性'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_cli_connection"
        ".reasoning_effort IS '推理强度；default沿"
        "用CLI默认，其他值需验证支持'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_cli_connection.encrypted_key IS '本人CLI Key密文，沿用平台后端主密钥'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_cli_connection.version IS 'CLI配置修订号，正整数，独立于偏好版本'"
    )
    op.execute("COMMENT ON COLUMN ai_cli_connection.updated_at IS 'CLI配置最近更新时间，带时区'")
    op.execute(
        "\nCREATE TABLE ai_call_preference (\n"
        "\towner_id BIGINT NOT NULL, \n\tcall_m"
        "ode VARCHAR(20) NOT NULL, \n\tversion"
        " INTEGER NOT NULL, \n\tupdated_at TIM"
        "ESTAMP WITH TIME ZONE DEFAULT now()"
        " NOT NULL, \n\tPRIMARY KEY (owner_id)"
        ", \n\tCONSTRAINT ck_ai_call_mode CHEC"
        "K (call_mode IN ('RESPONSES_API','C"
        "ODEX_EXEC')), \n\tCONSTRAINT ck_ai_pr"
        "eference_version CHECK (version > 0"
        "), \n\tFOREIGN KEY(owner_id) REFERENC"
        "ES user_account (id)\n)\n\n"
    )
    op.execute(
        "COMMENT ON TABLE ai_call_preference IS '用户当前AI调用方式；无记录的历史用户按API解释'"
    )
    op.execute("COMMENT ON COLUMN ai_call_preference.owner_id IS '偏好所属真实用户ID'")
    op.execute(
        "COMMENT ON COLUMN ai_call_preferenc"
        "e.call_mode IS '当前方式：RESPONSES_API接"
        "口、CODEX_EXEC受控CLI'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_preference.version IS '偏好修订号；只切方式也递增，与配置独立'"
    )
    op.execute("COMMENT ON COLUMN ai_call_preference.updated_at IS '调用偏好最近更新时间，带时区'")
    op.execute(
        "\nCREATE TABLE ai_call_reservation ("
        "\n\tid VARCHAR(36) NOT NULL, \n\towner_"
        "id BIGINT NOT NULL, \n\tkind VARCHAR("
        "80) NOT NULL, \n\ttask_id BIGINT, \n\tr"
        "equest_id VARCHAR(100) NOT NULL, \n\t"
        "credential_group VARCHAR(64) NOT NU"
        "LL, \n\tscheduler_id VARCHAR(36) NOT "
        "NULL, \n\tprocess_identity TEXT NOT N"
        "ULL, \n\tstate VARCHAR(16) DEFAULT 'H"
        "ELD' NOT NULL, \n\tcreated_at TIMESTA"
        "MP WITH TIME ZONE DEFAULT now() NOT"
        " NULL, \n\treleased_at TIMESTAMP WITH"
        " TIME ZONE, \n\tPRIMARY KEY (id), \n\tC"
        "ONSTRAINT ck_ai_reservation_state C"
        "HECK (state IN ('HELD','RELEASED','"
        "INTERRUPTED')), \n\tFOREIGN KEY(owner"
        "_id) REFERENCES user_account (id)\n)"
        "\n\n"
    )
    op.execute(
        "COMMENT ON TABLE ai_call_reservatio"
        "n IS 'API测试与后台任务共用调用预算；不按超时释放状态不明的调"
        "用'"
    )
    op.execute("COMMENT ON COLUMN ai_call_reservation.id IS '本次调用预留UUID，唯一防重放'")
    op.execute(
        "COMMENT ON COLUMN ai_call_reservation.owner_id IS '本次调用用户ID，统一约束本人并发'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservation.kind IS '固定任务表标识或CONNECTION_TEST测试类型'"
    )
    op.execute("COMMENT ON COLUMN ai_call_reservation.task_id IS '所属任务主键；连接测试为空'")
    op.execute(
        "COMMENT ON COLUMN ai_call_reservati"
        "on.request_id IS '任务请求标识或测试UUID；保留原"
        "请求关联'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservati"
        "on.credential_group IS '服务地址和凭据的服务端"
        "HMAC摘要，不公开、不保存明文Key'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservation.scheduler_id IS '持有预留的调度器或API调用归属UUID'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservati"
        "on.process_identity IS '本机主机名、进程ID及"
        "启动标识；只在证明原进程退出后回收'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservati"
        "on.state IS 'HELD占位、RELEASED调用已结束、I"
        "NTERRUPTED原执行者已退出'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservation.created_at IS '预留创建时间，带时区；非释放期限'"
    )
    op.execute(
        "COMMENT ON COLUMN ai_call_reservati"
        "on.released_at IS '核验调用结束后的释放时间，带时区"
        "；空表示尚未释放'"
    )
    op.execute("CREATE INDEX ix_ai_reservation_state ON ai_call_reservation (state)")


def downgrade():
    raise RuntimeError("AI配置和调用归属包含审计数据，降级需先人工审查导出与保留策略")
