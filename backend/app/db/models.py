from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint("login_name ~ '^[a-z0-9][a-z0-9_.-]{2,63}$'", name="ck_user_login_name"),
        CheckConstraint(
            "platform_role IN ('ADMIN', 'TEST', 'DEV', 'PRODUCT', 'MANAGER', 'USER')",
            name="ck_user_role",
        ),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED', 'DELETED')", name="ck_user_status"),
        CheckConstraint("failed_login_count BETWEEN 0 AND 5", name="ck_user_failed_login_count"),
        CheckConstraint("char_length(display_name) BETWEEN 1 AND 80", name="ck_user_name"),
        CheckConstraint("ai_source IN ('PLATFORM', 'PERSONAL')", name="ck_user_ai_source"),
        {"comment": "平台用户账号，包含身份、状态与登录安全信息"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    login_name: Mapped[str] = mapped_column(
        Text, unique=True, comment="登录账号，小写且全局唯一，逻辑删除后不可复用"
    )
    display_name: Mapped[str] = mapped_column(Text, comment="用户显示名称")
    password_hash: Mapped[str] = mapped_column(
        Text, comment="scrypt密码哈希及随机盐，不保存明文密码"
    )
    platform_role: Mapped[str] = mapped_column(
        Text,
        server_default="TEST",
        comment="平台角色：ADMIN管理员、TEST测试、DEV开发、PRODUCT产品、MANAGER经理；USER保留历史普通用户，非ADMIN沿用普通用户权限",
    )
    status: Mapped[str] = mapped_column(
        Text, server_default="ACTIVE", comment="账号状态：ACTIVE启用，DISABLED停用，DELETED逻辑删除"
    )
    ai_source: Mapped[str] = mapped_column(
        Text,
        server_default="PERSONAL",
        comment="历史AI来源字段，PLATFORM平台、PERSONAL个人；现已停用，仅使用用户个人配置",
    )
    ai_source_version: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="历史AI来源版本号，已停用，不参与当前配置选择"
    )
    failed_login_count: Mapped[int] = mapped_column(
        SmallInteger, server_default=text("0"), comment="连续登录失败次数，取值0至5"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="登录锁定截止时间；为空表示未锁定"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="逻辑删除时间；为空表示未删除"
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="创建人用户ID，关联user_account.id"
    )
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="最后修改人用户ID，关联user_account.id"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        comment="最后更新时间，带时区",
    )


class UserSession(Base):
    __tablename__ = "user_session"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_session_expiry"),
        CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_session_token_hash"),
        {"comment": "用户登录会话，保存令牌哈希、有效期与撤销时间"},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), index=True, comment="用户ID，关联user_account.id"
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, comment="会话令牌的SHA-256哈希，不保存原始令牌"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间，带时区"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True, comment="会话到期时间，带时区"
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="会话撤销时间；为空表示未主动撤销"
    )


class AIConnection(Base):
    __tablename__ = "ai_connection"
    __table_args__ = (
        CheckConstraint("id = COALESCE(owner_id, 0)", name="ck_ai_owner"),
        CheckConstraint("version > 0", name="ck_ai_version"),
        CheckConstraint(
            "reasoning_effort IN ('default', 'none', 'minimal', 'low', 'medium', "
            "'high', 'xhigh', 'max', 'ultra')",
            name="ck_ai_reasoning_effort",
        ),
        {"comment": "用户个人AI配置，密钥加密保存；历史平台记录保留但禁止使用"},
    )

    # ID zero is a retained legacy platform record; runtime uses only the authenticated user ID.
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=False,
        comment="配置主键为所属用户ID；0仅为停用的历史平台记录",
    )
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"),
        unique=True,
        comment="所属用户ID；为空仅表示停用的历史平台记录",
    )
    name: Mapped[str] = mapped_column(Text, comment="AI连接配置名称")
    base_url: Mapped[str] = mapped_column(Text, comment="允许访问的AI服务基础地址")
    model: Mapped[str] = mapped_column(Text, comment="模型标识，按配置原样传给上游")
    reasoning_effort: Mapped[str] = mapped_column(
        Text, server_default="default", comment="推理强度：default使用上游默认，其他配置值原样传递"
    )
    encrypted_key: Mapped[str] = mapped_column(Text, comment="AI访问密钥密文，使用后端主密钥加密")
    version: Mapped[int] = mapped_column(Integer, comment="乐观锁版本号，用于防止并发修改覆盖")
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="最后修改人用户ID，关联user_account.id"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        comment="最后更新时间，带时区",
    )


class AICLIConnection(Base):
    __tablename__ = "ai_cli_connection"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_ai_cli_version"),
        CheckConstraint(
            "reasoning_effort IN ('default','none','minimal','low','medium',"
            "'high','xhigh','max','ultra')",
            name="ck_ai_cli_effort",
        ),
        {"comment": "用户独立的Codex CLI配置；不复制API配置或服务器个人登录态"},
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), primary_key=True, comment="所属真实用户ID，每人一份CLI配置"
    )
    name: Mapped[str] = mapped_column(Text, comment="CLI个人配置显示名称")
    base_url: Mapped[str] = mapped_column(Text, comment="用户指定的HTTPS模型服务基础地址")
    model: Mapped[str] = mapped_column(Text, comment="CLI模型标识；不使用API目录推断兼容性")
    reasoning_effort: Mapped[str] = mapped_column(
        Text, server_default="default", comment="推理强度；default沿用CLI默认，其他值需验证支持"
    )
    encrypted_key: Mapped[str] = mapped_column(Text, comment="本人CLI Key密文，沿用平台后端主密钥")
    version: Mapped[int] = mapped_column(Integer, comment="CLI配置修订号，正整数，独立于偏好版本")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        comment="CLI配置最近更新时间，带时区",
    )


class AICallPreference(Base):
    __tablename__ = "ai_call_preference"
    __table_args__ = (
        CheckConstraint("call_mode IN ('RESPONSES_API','CODEX_EXEC')", name="ck_ai_call_mode"),
        CheckConstraint("version > 0", name="ck_ai_preference_version"),
        {"comment": "用户当前AI调用方式；无记录的历史用户按API解释"},
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), primary_key=True, comment="偏好所属真实用户ID"
    )
    call_mode: Mapped[str] = mapped_column(
        String(20), comment="当前方式：RESPONSES_API接口、CODEX_EXEC受控CLI"
    )
    version: Mapped[int] = mapped_column(Integer, comment="偏好修订号；只切方式也递增，与配置独立")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        comment="调用偏好最近更新时间，带时区",
    )


class AICallReservation(Base):
    __tablename__ = "ai_call_reservation"
    __table_args__ = (
        UniqueConstraint("kind", "task_id", "request_id", name="uq_ai_call_attempt"),
        CheckConstraint(
            "state IN ('HELD','RELEASED','INTERRUPTED')", name="ck_ai_reservation_state"
        ),
        Index("ix_ai_reservation_state", "state"),
        {"comment": "API测试与后台任务共用调用预算；不按超时释放状态不明的调用"},
    )
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, comment="本次调用预留UUID，唯一防重放"
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="本次调用用户ID，统一约束本人并发"
    )
    kind: Mapped[str] = mapped_column(String(80), comment="固定任务表标识或CONNECTION_TEST测试类型")
    task_id: Mapped[int | None] = mapped_column(BigInteger, comment="所属任务主键；连接测试为空")
    request_id: Mapped[str] = mapped_column(
        String(100), comment="任务请求标识或测试UUID；保留原请求关联"
    )
    credential_group: Mapped[str] = mapped_column(
        String(64), comment="服务地址和凭据的服务端HMAC摘要，不公开、不保存明文Key"
    )
    scheduler_id: Mapped[str] = mapped_column(
        String(36), comment="持有预留的调度器或API调用归属UUID"
    )
    process_identity: Mapped[str] = mapped_column(
        Text, comment="本机主机名、进程ID及启动标识；只在证明原进程退出后回收"
    )
    state: Mapped[str] = mapped_column(
        String(16),
        server_default="HELD",
        comment="HELD占位、RELEASED调用已结束、INTERRUPTED原执行者已退出",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="预留创建时间，带时区；非释放期限",
    )
    released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="核验调用结束后的释放时间，带时区；空表示尚未释放"
    )


class GitHubConnection(Base):
    __tablename__ = "github_connection"
    __table_args__ = (
        CheckConstraint("kind IN ('personal', 'organization', 'automatic')", name="ck_github_kind"),
        CheckConstraint("version > 0", name="ck_github_version"),
        {"comment": "用户自有GitHub连接及加密访问凭据"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), index=True, comment="连接所属的平台用户ID，仅本人使用凭据"
    )
    name: Mapped[str] = mapped_column(Text, comment="GitHub连接显示名称")
    kind: Mapped[str] = mapped_column(
        Text, comment="范围类型：personal个人、organization组织、automatic自动发现"
    )
    resource_owner: Mapped[str] = mapped_column(
        Text, comment="兼容旧版的资源所属方；自动发现模式记录登录账号，不限制仓库所属方"
    )
    github_login: Mapped[str] = mapped_column(Text, comment="访问凭据对应的GitHub登录账号")
    encrypted_token: Mapped[str] = mapped_column(
        Text, comment="GitHub访问令牌密文，支持已授权的Classic及Fine-grained Token"
    )
    version: Mapped[int] = mapped_column(Integer, comment="乐观锁版本号，用于防止并发修改覆盖")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        comment="最后更新时间，带时区",
    )


class GitHubRepository(Base):
    __tablename__ = "github_repository"
    __table_args__ = {"comment": "GitHub连接下明确选择授权的仓库"}
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("github_connection.id"),
        primary_key=True,
        comment="所属GitHub连接ID，与仓库ID组成联合主键",
    )
    github_id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment="GitHub仓库的远端唯一ID"
    )
    full_name: Mapped[str] = mapped_column(Text, comment="GitHub仓库完整名称，格式为所属方/仓库名")
    default_branch: Mapped[str] = mapped_column(Text, comment="发现授权仓库时记录的默认分支")
    private: Mapped[bool] = mapped_column(Boolean, comment="是否为GitHub私有仓库")
    owner_type: Mapped[str] = mapped_column(
        Text, server_default="User", comment="仓库所属方类型：User个人，Organization组织"
    )


class Project(Base):
    __tablename__ = "project"
    __table_args__ = {"comment": "项目基本信息与负责人"}
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    name: Mapped[str] = mapped_column(Text, comment="项目名称")
    identifier: Mapped[str] = mapped_column(Text, unique=True, comment="项目唯一标识，保存为小写")
    description: Mapped[str] = mapped_column(
        Text, server_default="", comment="项目说明，默认空字符串"
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), index=True, comment="项目负责人用户ID，关联user_account.id"
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="创建人用户ID，关联user_account.id"
    )
    version: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="乐观锁版本号，用于防止并发修改覆盖"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="项目逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除项目的用户ID；空表示未删除"
    )


class ProjectMember(Base):
    __tablename__ = "project_member"
    __table_args__ = {"comment": "项目成员关系，负责人另由项目表记录"}
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), primary_key=True, comment="所属项目ID，关联project.id"
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), primary_key=True, comment="用户ID，关联user_account.id"
    )


class LocalCodeSource(Base):
    __tablename__ = "local_code_source"
    __table_args__ = (
        UniqueConstraint("project_id", "owner_id", "client_id", name="uq_local_code_client"),
        CheckConstraint(
            "kind IN ('BACKEND', 'FLUTTER', 'WEB', 'PROTOTYPE', 'OTHER')",
            name="ck_local_code_kind",
        ),
        CheckConstraint("version > 0", name="ck_local_code_version"),
        {"comment": "用户本机代码目录的项目关联，仅存元数据，不保存代码或磁盘路径"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="关联主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="目录授权所属用户ID"
    )
    client_id: Mapped[str] = mapped_column(
        Text, comment="浏览器生成的稳定关联UUID，用于重复提交去重"
    )
    name: Mapped[str] = mapped_column(Text, comment="本地代码来源显示名称")
    directory_name: Mapped[str] = mapped_column(Text, comment="授权目录的末级名称，不是绝对路径")
    kind: Mapped[str] = mapped_column(
        Text, comment="代码类型：BACKEND后端、FLUTTER应用、WEB前端、PROTOTYPE原型、OTHER其他"
    )
    version: Mapped[int] = mapped_column(Integer, server_default="1", comment="元数据乐观锁版本号")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="关联创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.clock_timestamp(),
        comment="元数据最近更新时间，带时区",
    )


class ProjectRepository(Base):
    __tablename__ = "project_repository"
    __table_args__ = (
        UniqueConstraint("project_id", "github_id", name="uq_project_repository"),
        CheckConstraint(
            "kind IN ('BACKEND', 'FLUTTER', 'WEB', 'PROTOTYPE', 'OTHER')",
            name="ck_project_repo_kind",
        ),
        {"comment": "项目关联的GitHub仓库元数据，不共享个人访问凭据"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID，关联project.id"
    )
    github_id: Mapped[int] = mapped_column(BigInteger, comment="GitHub仓库的远端唯一ID")
    full_name: Mapped[str] = mapped_column(Text, comment="GitHub仓库完整名称，格式为所属方/仓库名")
    kind: Mapped[str] = mapped_column(
        Text, comment="代码类型：BACKEND后端、FLUTTER应用、WEB前端、PROTOTYPE原型、OTHER其他"
    )
    default_branch: Mapped[str] = mapped_column(Text, comment="默认分析分支名称")
    version: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="乐观锁版本号，用于防止并发修改覆盖"
    )
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="最后修改人用户ID，关联user_account.id"
    )


class DocumentLibrary(Base):
    __tablename__ = "document_library"
    __table_args__ = {"comment": "项目资料库并发版本控制"}
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), primary_key=True, comment="所属项目ID，关联project.id"
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="资料库并发修订号，资料整理或上传后递增"
    )


class DocumentGroup(Base):
    __tablename__ = "document_group"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_document_group_project"),
        UniqueConstraint("project_id", "purpose", "name", name="uq_document_group_name"),
        CheckConstraint("purpose IN ('REQUIREMENT','PROTOTYPE')", name="ck_document_group_purpose"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="ck_document_group_name"),
        {"comment": "项目内按需求或原型类别隔离的资料分组，允许空分组"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID，关联project.id"
    )
    purpose: Mapped[str] = mapped_column(
        Text,
        server_default="REQUIREMENT",
        comment="资料类别：REQUIREMENT需求资料、PROTOTYPE原型资料",
    )
    name: Mapped[str] = mapped_column(Text, comment="资料分组名称，同项目及同资料类别内唯一")


class SourceDocument(Base):
    __tablename__ = "source_document"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_source_document_project"),
        ForeignKeyConstraint(
            ["project_id", "group_id"],
            ["document_group.project_id", "document_group.id"],
            name="fk_source_document_group",
        ),
        CheckConstraint("current_version > 0", name="ck_source_document_version"),
        CheckConstraint(
            "purpose IN ('REQUIREMENT','PROTOTYPE')", name="ck_source_document_purpose"
        ),
        CheckConstraint(
            "kind IN ('FILE','DIRECTORY','GITHUB','LINK') "
            "AND (kind = 'FILE' OR purpose = 'PROTOTYPE')",
            name="ck_source_document_kind",
        ),
        {"comment": "需求与原型资料来源；上传文件按版本保存，GitHub及链接记录实时配置"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID，关联project.id"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="资料逻辑删除时间，带时区；空表示未删除，原件和版本引用继续保留",
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除资料的操作用户ID；空表示未删除"
    )
    group_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="所属资料分组ID；为空表示未分组，分组必须属于同项目"
    )
    position: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="组内排序值，按升序展示"
    )
    purpose: Mapped[str] = mapped_column(
        Text,
        server_default="REQUIREMENT",
        comment="资料类别：REQUIREMENT需求资料、PROTOTYPE原型资料",
    )
    kind: Mapped[str] = mapped_column(
        Text,
        server_default="FILE",
        comment="来源类型：FILE上传文件、DIRECTORY上传目录、GITHUB实时仓库、LINK实时链接",
    )
    name: Mapped[str] = mapped_column(
        Text, server_default="", comment="原型资料显示名称；需求文件默认空并使用文件名"
    )
    description: Mapped[str] = mapped_column(
        Text, server_default="", comment="原型页面或交互说明；默认空字符串"
    )
    url: Mapped[str | None] = mapped_column(
        Text, comment="LINK原型的HTTP或HTTPS地址；其他类型为空，不保存页面快照"
    )
    repository_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_repository.id", name="fk_source_document_repository"),
        comment="GITHUB来源的项目仓库关联ID；其他类型为空，不包含凭据",
    )
    branch: Mapped[str | None] = mapped_column(
        Text, comment="GITHUB来源持续跟踪的分支；其他类型为空"
    )
    path: Mapped[str | None] = mapped_column(
        Text, comment="GITHUB原型目录或文件相对路径；空字符串表示整个仓库，非GITHUB为NULL"
    )
    selected_paths: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="用户明确选中的仓库文件路径清单；非GITHUB为空数组，不自动扩大范围",
    )
    latest_commit: Mapped[str | None] = mapped_column(
        String(40), comment="最近成功核实的GitHub提交SHA；未检查或非GITHUB为空"
    )
    file_manifest: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="最近固定提交的所选文件元数据清单：path、sha、size；不保存或执行源码",
    )
    checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="最近成功检查GitHub的时间；未检查或非GITHUB为空"
    )
    current_version: Mapped[int] = mapped_column(
        Integer,
        comment="上传文件当前版本号，关联document_version.number；实时来源固定为1且不生成文件版本",
    )


class DocumentVersion(Base):
    __tablename__ = "document_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "document_id"],
            ["source_document.project_id", "source_document.id"],
            name="fk_document_version_document",
        ),
        UniqueConstraint("document_id", "number", name="uq_document_version_number"),
        UniqueConstraint("project_id", "id", name="uq_document_version_project"),
        UniqueConstraint("project_id", "upload_id", name="uq_document_upload_id"),
        CheckConstraint("size > 0", name="ck_document_size"),
        CheckConstraint("number > 0", name="ck_document_version_number"),
        {"comment": "资料的不可覆盖历史版本及私有原件存储信息"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID，关联project.id"
    )
    document_id: Mapped[int] = mapped_column(BigInteger, comment="所属原始资料ID，必须属于同项目")
    number: Mapped[int] = mapped_column(Integer, comment="资料版本号，同一资料内唯一且大于0")
    filename: Mapped[str] = mapped_column(Text, comment="上传时的原始文件名")
    extension: Mapped[str] = mapped_column(Text, comment="文件扩展名，用于预览类型判断")
    media_type: Mapped[str] = mapped_column(Text, comment="文件MIME类型")
    size: Mapped[int] = mapped_column(BigInteger, comment="原始文件大小，单位字节，必须大于0")
    sha256: Mapped[str] = mapped_column(String(64), comment="原始文件内容的SHA-256摘要")
    storage_key: Mapped[str] = mapped_column(
        String(32), unique=True, comment="私有原件存储键，随机32位标识，不是用户提供的路径"
    )
    upload_id: Mapped[str] = mapped_column(
        String(36), comment="上传请求UUID，用于项目内重复请求识别"
    )
    directory_files: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="DIRECTORY固定版本文件索引：相对path、sha256、size字节、extension及私有storage_key；其他版本为空数组",
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="创建人用户ID，关联user_account.id"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间，带时区"
    )


class DocumentLinkBinding(Base):
    __tablename__ = "document_link_binding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "source_version_id"],
            ["document_version.project_id", "document_version.id"],
            name="fk_link_source_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "target_version_id"],
            ["document_version.project_id", "document_version.id"],
            name="fk_link_target_project",
        ),
        UniqueConstraint(
            "source_version_id", "href_hash", "revision", name="uq_link_binding_revision"
        ),
        CheckConstraint("revision > 0", name="ck_link_binding_revision"),
        {"comment": "Markdown链接的追加式关联历史，固定来源和目标附件版本，不覆盖旧关联"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="关联记录主键，可用于分析快照追溯"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID，来源及目标版本必须同项目"
    )
    source_version_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="来源Markdown的固定版本ID"
    )
    href: Mapped[str] = mapped_column(
        Text, comment="Markdown解析后的链接地址，仅作匹配标识，不用于访问文件或网络"
    )
    href_hash: Mapped[str] = mapped_column(
        String(64), comment="链接地址规范化后SHA256，用于同一来源版本内匹配链接"
    )
    target_version_id: Mapped[int] = mapped_column(
        BigInteger, comment="人工选定的目标附件固定版本ID，不自动跟随新版"
    )
    revision: Mapped[int] = mapped_column(
        Integer, comment="同来源版本及链接的关联修订号，从1递增，修改追加新记录"
    )
    inherited_from_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_link_binding.id"),
        comment="从上一来源版本继承的关联记录ID；为空表示人工选择",
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="建立或继承关联的操作人用户ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="关联建立时间，带时区"
    )


class CaseLibrary(Base):
    __tablename__ = "case_library"
    __table_args__ = (
        CheckConstraint("next_number > 0", name="ck_case_next_number"),
        {"comment": "项目用例库自增编号与并发修订号"},
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), primary_key=True, comment="所属项目ID"
    )
    next_number: Mapped[int] = mapped_column(
        BigInteger, server_default="1", comment="下一个平台用例编号，项目内递增，不采用导入编号"
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="用例库并发修订号，操作时校验防止覆盖"
    )


class CaseCategory(Base):
    __tablename__ = "case_category"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_case_category_project"),
        UniqueConstraint("project_id", "name", name="uq_case_category_name"),
        {"comment": "项目共享用例分类，允许自定义名称和空分类"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="分类主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    name: Mapped[str] = mapped_column(Text, comment="分类名称，同项目唯一")
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="最后维护分类的用户ID"
    )


class CaseImport(Base):
    __tablename__ = "case_import"
    __table_args__ = (
        UniqueConstraint("project_id", "request_id", name="uq_case_import_request"),
        UniqueConstraint("project_id", "id", name="uq_case_import_project"),
        {"comment": "用例导入原件、解析数据和确认批次，确认后只读"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="导入批次主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    filename: Mapped[str] = mapped_column(Text, comment="导入原文件名")
    storage_key: Mapped[str] = mapped_column(
        String(32), unique=True, comment="私有原件随机存储键，不是用户路径"
    )
    sha256: Mapped[str] = mapped_column(String(64), comment="原件SHA256校验值")
    request_id: Mapped[str] = mapped_column(String(36), comment="上传幂等请求UUID")
    raw_data: Mapped[dict] = mapped_column(
        JSONB, comment="已校验的工作表、单元格、公式位置及合并范围快照"
    )
    preview: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="自动校验、重复对比和待确认用例快照"
    )
    preview_revision: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="预览修订号，防止旧预览误确认"
    )
    library_revision: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="预览时用例库修订号，确认时核对"
    )
    committed: Mapped[bool] = mapped_column(
        Boolean, server_default="false", comment="是否已确认入库，重复确认不新增用例"
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("user_account.id"), comment="上传用户ID")
    confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="确认入库用户ID，未确认时为空"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="导入上传时间，带时区"
    )


class ManagedCase(Base):
    __tablename__ = "managed_case"
    lifecycle: Mapped[str] = mapped_column(
        String(16),
        server_default="ACTIVE",
        comment="用例生命周期ACTIVE活动或RETIRED停用；独立于测试结果和逻辑删除",
    )
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_managed_case_project"),
        CheckConstraint("lifecycle IN ('ACTIVE','RETIRED')", name="ck_case_lifecycle"),
        UniqueConstraint("project_id", "number", name="uq_managed_case_number"),
        UniqueConstraint("project_id", "request_id", name="uq_managed_case_request"),
        ForeignKeyConstraint(
            ["project_id", "category_id"],
            ["case_category.project_id", "case_category.id"],
            name="fk_case_category_project",
        ),
        {"comment": "项目用例稳定身份和当前分类，编号永久保留"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="用例内部主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    number: Mapped[int] = mapped_column(
        BigInteger, comment="项目内自增内部顺序号，永久保留；无导入编号时作为展示编号"
    )
    imported_number: Mapped[str | None] = mapped_column(
        Text, comment="导入文件的用例编号原文，保留前导零且允许重复；空表示无原编号，展示内部顺序号"
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="所属分类ID；空为未分类，分类必须同项目"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="逻辑删除时间，带时区；空表示未删除，删除后保留编号及历史"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除操作用户ID；空表示未删除"
    )
    current_version: Mapped[int] = mapped_column(Integer, comment="当前设计版本号，从1开始")
    request_id: Mapped[str] = mapped_column(String(36), comment="创建幂等请求UUID")
    created_by: Mapped[int] = mapped_column(ForeignKey("user_account.id"), comment="用例创建用户ID")
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="最后操作用户ID，包括分类调整"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="用例创建时间，带时区"
    )


class CaseVersion(Base):
    __tablename__ = "case_version"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_case_version_project"),
        UniqueConstraint("case_id", "number", name="uq_case_version_number"),
        ForeignKeyConstraint(
            ["project_id", "case_id"],
            ["managed_case.project_id", "managed_case.id"],
            name="fk_case_version_project",
        ),
        ForeignKeyConstraint(
            ["project_id", "import_id"],
            ["case_import.project_id", "case_import.id"],
            name="fk_case_version_import",
        ),
        {"comment": "用例设计追加版本，修改设计保留旧版"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="设计版本主键"
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), comment="所属项目ID")
    case_id: Mapped[int] = mapped_column(BigInteger, index=True, comment="所属用例ID，必须同项目")
    number: Mapped[int] = mapped_column(Integer, comment="设计版本号，同一用例内递增")
    module: Mapped[str] = mapped_column(Text, server_default="", comment="功能模块")
    structure: Mapped[str] = mapped_column(Text, server_default="", comment="功能结构")
    case_type: Mapped[str] = mapped_column(Text, server_default="", comment="用例类型，空为未提供")
    priority: Mapped[str] = mapped_column(
        Text, server_default="", comment="优先级P0至P4，空为未提供"
    )
    description: Mapped[str] = mapped_column(Text, server_default="", comment="用例描述")
    title: Mapped[str] = mapped_column(Text, server_default="", comment="验证用例子项")
    preconditions: Mapped[str] = mapped_column(
        Text, server_default="", comment="前置条件，保留换行"
    )
    steps: Mapped[str] = mapped_column(Text, server_default="", comment="操作步骤，保留时序和换行")
    expected: Mapped[str] = mapped_column(
        Text, server_default="", comment="场景级预期结果，不要求与步骤行数相等"
    )
    remark: Mapped[str] = mapped_column(Text, server_default="", comment="备注")
    data_requirements: Mapped[str] = mapped_column(
        Text, server_default="", comment="测试数据要求，空为未提供"
    )
    cleanup: Mapped[str] = mapped_column(Text, server_default="", comment="清理要求，空为未提供")
    source_kind: Mapped[str] = mapped_column(
        Text, comment="来源MANUAL人工、IMPORT导入或GENERATION人工采纳生成"
    )
    import_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="来源导入批次ID；非导入版本为空"
    )
    source: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="导入原行编号和结果，或生成记录/候选/应用批次/对话引用；人工为空",
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("user_account.id"), comment="该版本创建人ID")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="版本创建时间，带时区"
    )


class CaseRecord(Base):
    __tablename__ = "case_record"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "version_id"],
            ["case_version.project_id", "case_version.id"],
            name="fk_case_record_version",
        ),
        CheckConstraint("kind IN ('TEST','REVIEW')", name="ck_case_record_kind"),
        {"comment": "用例版本的追加测试及审核记录，旧记录不覆盖"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="记录主键")
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), comment="所属项目ID")
    version_id: Mapped[int] = mapped_column(
        BigInteger, index=True, comment="固定设计版本ID，必须同项目"
    )
    kind: Mapped[str] = mapped_column(Text, comment="记录类型TEST测试结果或REVIEW审核")
    result: Mapped[str] = mapped_column(
        Text, server_default="", comment="未测、通过、失败、阻塞、跳过、废弃或空"
    )
    tester: Mapped[str] = mapped_column(
        Text, server_default="", comment="填写或导入的测试人员名称，空为未提供"
    )
    review_status: Mapped[str] = mapped_column(
        Text, server_default="", comment="待审核、已审核；测试记录中为空"
    )
    source_kind: Mapped[str] = mapped_column(
        Text, comment="记录来源MANUAL人工、IMPORT导入或GENERATION人工采纳生成"
    )
    recorded_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="实际录入用户ID，不等同测试执行人"
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="录入时间，不冒充实际测试执行时间",
    )


class RequirementRiskReport(Base):
    __tablename__ = "requirement_risk_report"
    __table_args__ = (
        UniqueConstraint("project_id", "sha256", name="uq_risk_report_content"),
        CheckConstraint("revision >= 1", name="ck_risk_report_revision"),
        {
            "comment": (
                "项目需求风险报告；保存导入或AI分析的固定输入、结果与来源关联，人工处理独立留痕"
            )
        },
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="风险报告主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID；报告及处理记录仅项目内共享"
    )
    title: Mapped[str] = mapped_column(String(200), comment="用户填写的报告名称")
    input_filename: Mapped[str] = mapped_column(
        String(200), comment="导入输入JSON文件名，不包含本机目录"
    )
    report_filename: Mapped[str] = mapped_column(
        String(200), comment="导入结果JSON文件名，不包含本机目录"
    )
    sha256: Mapped[str] = mapped_column(
        String(64), comment="规范化输入与结果内容SHA256；同项目相同内容幂等，不覆盖原报告"
    )
    input: Mapped[dict] = mapped_column(
        JSONB, comment="Skill v3当次完整输入快照，含文字片段；图片和PDF原件引用项目已有资料"
    )
    report: Mapped[dict] = mapped_column(
        JSONB,
        comment="结构及引用校验通过的Skill v3风险报告；证据与覆盖提示待人工核对，不随处理改写",
    )
    bindings: Mapped[list] = mapped_column(
        JSONB, comment="输入来源ID到系统资料及固定版本的人工关联快照；不证明模型实际读取了原件"
    )
    handling: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="风险key对应人工处理状态、结论和历史；未出现的风险默认PENDING待确认",
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="报告处理并发修订号，每次有效处理变更递增"
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("user_account.id"), comment="导入者账号ID")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="报告导入时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近人工处理时间，带时区"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="分析记录逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除本分析记录的用户ID；空表示未删除"
    )


class RequirementRiskAnalysis(Base):
    __tablename__ = "requirement_risk_analysis"
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "request_id", name="uq_risk_analysis_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_risk_analysis_status",
        ),
        {"comment": "需求风险首次AI分析任务；固定用户选择和执行结果，不替代风险报告"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="分析任务主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID；任务及结果仅项目内共享"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="任务发起人ID，仅使用此人个人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="客户端提交UUID，同项目同用户幂等防止重复计费"
    )
    retry_of: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_risk_analysis.id"), comment="人工重试的原任务ID；首次分析为空"
    )
    title: Mapped[str] = mapped_column(String(200), comment="用户填写的分析记录名称")
    focus: Mapped[str] = mapped_column(
        Text, server_default="", comment="本次补充关注范围；空表示所选资料"
    )
    selections: Mapped[list] = mapped_column(
        JSONB, comment="发起时选择的资料和固定版本清单；不包含密钥或资料正文"
    )
    context: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="当次v3输入、来源绑定、校正和人工核对提示快照；准备前为空对象",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队/RUNNING分析中/COMPLETED完成/FAILED失败/CANCELLED停止",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码；无错误为空，不保存上游原始错误"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_risk_report.id"), comment="校验并入库后的风险报告ID；未完成时为空"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="任务创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="任务最近状态更新时间，带时区"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="分析记录逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除本分析记录的用户ID；空表示未删除"
    )


class CodeAnalysisTask(Base):
    __tablename__ = "code_analysis_task"
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "request_id", name="uq_code_analysis_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_code_analysis_status",
        ),
        {"comment": "代码分析任务；保存固定代码输入、结构化发现和独立对话入口"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="代码分析任务主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID；任务和结果仅项目内共享"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="发起人账号ID；仅使用此人的个人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="客户端请求UUID；同项目同用户幂等防止重复计费"
    )
    retry_of: Mapped[int | None] = mapped_column(
        ForeignKey("code_analysis_task.id"), comment="人工重试的原任务ID；首次分析为空"
    )
    title: Mapped[str] = mapped_column(String(200), comment="用户填写的代码分析记录名称")
    focus: Mapped[str] = mapped_column(Text, server_default="", comment="本次代码检查关注点")
    targets: Mapped[list] = mapped_column(JSONB, comment="代码检查目标枚举列表")
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB, comment="固定代码、需求/原型文字和来源版本快照；不包含密钥"
    )
    report: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="校验后的代码分析报告；失败或未完成为空对象"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队/RUNNING分析中/COMPLETED完成/FAILED失败/CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码；不保存上游原始错误"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    revision: Mapped[int] = mapped_column(Integer, server_default="1", comment="人工处理并发修订号")
    metadata_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="创建方式、来源授权关联、原始选择及Skill固定内容；不含凭据",
    )
    handling: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="按发现key保存独立人工处理和审计历史；不修改原报告"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="任务创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="任务最近状态更新时间，带时区"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="分析记录逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除本分析记录的用户ID；空表示未删除"
    )


class CodeAnalysisChatTurn(Base):
    __tablename__ = "code_analysis_chat_turn"
    __table_args__ = (
        UniqueConstraint("task_id", "request_id", name="uq_code_chat_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_code_chat_status",
        ),
        Index(
            "uq_code_chat_active",
            "task_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        {"comment": "代码分析独立对话轮次；仅包含本分析固定输入、发现与历史，使用提问者个人AI"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="代码分析对话轮次主键"
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("code_analysis_task.id"), index=True, comment="所属代码分析记录ID"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="本轮发起人ID；使用其个人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="本轮请求UUID；同分析内幂等防重复计费"
    )
    finding_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="本轮引用发现key；未引用为空"
    )
    question: Mapped[str] = mapped_column(Text, comment="本轮用户提问")
    answer: Mapped[str] = mapped_column(
        Text, server_default="", comment="完整AI回答；未成功完成为空"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队/RUNNING回答中/COMPLETED完成/FAILED失败/CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全错误码；不保存上游原始错误"
    )
    context: Mapped[dict] = mapped_column(
        JSONB, comment="本轮固定代码报告、处理状态和已完成对话历史快照"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="对话创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="对话状态更新时间，带时区"
    )


class ChangeAnalysisTask(Base):
    __tablename__ = "change_analysis_task"
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "request_id", name="uq_change_analysis_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','PREPARED','COMPLETED','FAILED','CANCELLED')",
            name="ck_change_analysis_status",
        ),
        {"comment": "变更分析任务；保存固定双侧内容输入、结构化发现和独立对话入口"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="变更分析任务主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID；任务和结果仅项目内共享"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="发起人账号ID；仅使用此人的个人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="客户端请求UUID；同项目同用户幂等防止重复计费"
    )
    retry_of: Mapped[int | None] = mapped_column(
        ForeignKey("change_analysis_task.id"), comment="人工重试的原任务ID；首次分析为空"
    )
    title: Mapped[str] = mapped_column(String(200), comment="用户填写的变更分析记录名称")
    mode: Mapped[str] = mapped_column(
        String(32), comment="主变更方式：需求、代码或原型；枚举固定于输入"
    )
    focus: Mapped[str] = mapped_column(Text, server_default="", comment="本次变更检查关注点")
    targets: Mapped[list] = mapped_column(JSONB, comment="变更检查目标枚举列表")
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB, comment="固定双侧内容、需求/原型文字和来源版本快照；不包含密钥"
    )
    report: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="校验后的变更分析报告；可为标明未完成批次的部分成果，无成功成果时为空",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队/RUNNING准备或分析中/PREPARED待确认批次/COMPLETED完成或部分成果/FAILED失败/CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码；不保存上游原始错误"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    revision: Mapped[int] = mapped_column(Integer, server_default="1", comment="人工处理并发修订号")
    metadata_snapshot: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="创建方式、来源授权、原始选择、固定Skill及分批计划、成果和调用审计；不含凭据",
    )
    handling: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="按发现key保存独立人工处理和审计历史；不修改原报告"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="任务创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="任务最近状态更新时间，带时区"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="分析记录逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除本分析记录的用户ID；空表示未删除"
    )


class ChangeAnalysisChatTurn(Base):
    __tablename__ = "change_analysis_chat_turn"
    __table_args__ = (
        UniqueConstraint("task_id", "request_id", name="uq_change_chat_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')",
            name="ck_change_chat_status",
        ),
        Index(
            "uq_change_chat_active",
            "task_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        {"comment": "变更分析独立对话轮次；仅包含本分析固定输入、发现与历史，使用提问者个人AI"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="变更分析对话轮次主键"
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("change_analysis_task.id"), index=True, comment="所属变更分析记录ID"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="本轮发起人ID；使用其个人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="本轮请求UUID；同分析内幂等防重复计费"
    )
    finding_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="本轮引用发现key；未引用为空"
    )
    question: Mapped[str] = mapped_column(Text, comment="本轮用户提问")
    answer: Mapped[str] = mapped_column(
        Text, server_default="", comment="完整AI回答；未成功完成为空"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队/RUNNING回答中/COMPLETED完成/FAILED失败/CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全错误码；不保存上游原始错误"
    )
    context: Mapped[dict] = mapped_column(
        JSONB, comment="本轮固定双侧内容报告、处理状态和已完成对话历史快照"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="对话创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="对话状态更新时间，带时区"
    )


class RequirementChatTurn(Base):
    __tablename__ = "requirement_chat_turn"
    __table_args__ = (
        UniqueConstraint("report_id", "request_id", name="uq_chat_request"),
        CheckConstraint(
            "status IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED')", name="ck_chat_status"
        ),
        Index(
            "uq_chat_active",
            "report_id",
            "function_key",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        {"comment": "需求分析对话轮次；按分析结果共享历史，独立Worker调用本人AI，不修改风险"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="对话轮次主键及顺序"
    )
    report_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_risk_report.id"),
        index=True,
        comment="关联的固定需求分析结果ID，也是需求分析对话归属",
    )
    function_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="对话归属功能key；空字符串表示需求分析对话"
    )
    risk_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="本轮明确引用的风险key；无风险引用为空字符串"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="本轮发起人ID，仅使用此人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="客户端提交UUID，同一分析内幂等防重复计费"
    )
    question: Mapped[str] = mapped_column(Text, comment="用户本轮提问正文")
    answer: Mapped[str] = mapped_column(
        Text, server_default="", comment="完整AI回复；未完成或失败为空，不将部分回复标记成功"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队/RUNNING回答中/COMPLETED完成/FAILED失败/CANCELLED停止",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码；无错误为空，不保存上游原始错误"
    )
    context: Mapped[dict] = mapped_column(
        JSONB, comment="本轮固定资料、风险、人工核对提示、处理与已完成消息快照；不含密钥"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="轮次提交时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="轮次最近状态更新时间，带时区"
    )


class RequirementManualRisk(Base):
    __tablename__ = "requirement_manual_risk"
    __table_args__ = (
        UniqueConstraint("report_id", "request_id", name="uq_manual_risk_request"),
        CheckConstraint("severity IN ('HIGH','MEDIUM','LOW')", name="ck_manual_risk_severity"),
        CheckConstraint(
            "status IN ('PENDING','NEEDS_INFO','RESOLVED','NOT_APPLICABLE')",
            name="ck_manual_risk_status",
        ),
        CheckConstraint("revision >= 1", name="ck_manual_risk_revision"),
        {"comment": "从需求分析对话人工确认新增的风险；独立于AI原始报告并参与累计清单"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="人工风险主键"
    )
    report_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_risk_report.id"), index=True, comment="所属固定分析报告ID"
    )
    function_key: Mapped[str] = mapped_column(String(200), comment="所属报告内功能key")
    message_turn_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_chat_turn.id"), comment="来源AI回复轮次ID，用于返回对话追溯"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="客户端提交UUID，同一报告内幂等")
    title: Mapped[str] = mapped_column(String(500), comment="人工确认的风险标题")
    severity: Mapped[str] = mapped_column(String(16), comment="风险等级HIGH高/MEDIUM中/LOW低")
    risk_type: Mapped[str] = mapped_column(String(32), comment="风险类型，沿用需求风险报告枚举")
    description: Mapped[str] = mapped_column(Text, comment="人工确认的问题描述")
    evidence: Mapped[list] = mapped_column(
        JSONB, comment="人工核对的固定原文来源、位置、摘录和观察"
    )
    impact: Mapped[str] = mapped_column(Text, comment="可能造成的业务、实现或验收影响")
    questions: Mapped[list] = mapped_column(JSONB, comment="待产品确认问题清单")
    improvement: Mapped[dict] = mapped_column(JSONB, comment="完善建议、理由及取舍，仍需人工确认")
    status: Mapped[str] = mapped_column(
        String(20), server_default="PENDING", comment="当前处理状态"
    )
    note: Mapped[str] = mapped_column(
        Text, server_default="", comment="当前人工处理结论；待确认时可为空"
    )
    history: Mapped[list] = mapped_column(
        JSONB, server_default="[]", comment="人工处理状态与结论的追加历史"
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="并发修订号，每次有效处理递增"
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="新增风险的操作人ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="风险确认入库时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近人工处理时间，带时区"
    )


class RequirementAnalysis(Base):
    __tablename__ = "requirement_analysis"
    diagnostics: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="分析阶段、耗时、读取计数及安全上游诊断；不含原文、思考内容或密钥，空对象为历史未记录",
    )
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "request_id", name="uq_analysis_request"),
        CheckConstraint(
            "status IN ('QUEUED','PREPARING','RUNNING','COMPLETE','PARTIAL','FAILED','CANCELLED')",
            name="ck_analysis_status",
        ),
        {"comment": "项目共享需求分析任务、固定输入证据及人工采纳记录；不记录执行通过"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="需求分析任务主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="发起人ID，仅使用本人AI配置"
    )
    request_id: Mapped[str] = mapped_column(
        String(36), comment="发起请求UUID，同项目同用户重复请求返回原任务"
    )
    retry_of: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_analysis.id"), comment="人工重试的原任务ID；首次为空"
    )
    status: Mapped[str] = mapped_column(
        Text,
        index=True,
        comment="任务状态QUEUED排队、PREPARING准备、RUNNING分析、COMPLETE完成、PARTIAL部分完成、FAILED失败、CANCELLED取消",
    )
    error: Mapped[str] = mapped_column(
        Text, server_default="", comment="安全错误码；空表示无执行错误，不保存上游正文"
    )
    request: Mapped[dict] = mapped_column(
        JSONB, comment="固定发起选择、用途、个人配置版本和关注点；不含密钥"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    skill: Mapped[dict] = mapped_column(JSONB, comment="实际Skill及契约文本、版本和SHA256摘要快照")
    context: Mapped[dict] = mapped_column(
        JSONB, comment="固定分析输入、资料内容及位置、GitHub提交证据；二进制仅引用私有原件"
    )
    result: Mapped[dict | None] = mapped_column(
        JSONB, comment="校验通过的Skill v2结果；未完成或失败为空"
    )
    adoptions: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="人工采纳请求、操作者、时间及功能候选到正式记录的固定映射",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态更新或领取时间，带时区"
    )


class RequirementLibrary(Base):
    __tablename__ = "requirement_library"
    __table_args__ = ({"comment": "项目验收点库编号及并发修订号"},)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), primary_key=True, comment="所属项目ID"
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="页面并发修订号，每次写入递增"
    )
    next_number: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="下一个项目内验收点编号"
    )


class RequirementCategory(Base):
    __tablename__ = "requirement_category"
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_requirement_category_project"),
        ForeignKeyConstraint(
            ["project_id", "parent_id"],
            ["requirement_category.project_id", "requirement_category.id"],
            name="fk_requirement_category_parent",
        ),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_requirement_category_self"
        ),
        Index(
            "uq_requirement_category_name",
            "project_id",
            func.coalesce(text("parent_id"), 0),
            "name",
            unique=True,
        ),
        {"comment": "项目功能模块与功能点，空分类永久保留；父级为空表示模块"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="分类主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="所属模块ID；为空表示顶层模块，仅允许两级"
    )
    name: Mapped[str] = mapped_column(Text, comment="分类名称，1至80字，同级唯一")
    position: Mapped[int] = mapped_column(Integer, comment="同级展示顺序，按数值升序")


class RequirementRule(Base):
    __tablename__ = "requirement_rule"
    analysis_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_analysis.id"),
        comment="生成来源需求分析任务ID；空为人工创建，任务证据永久保留",
    )
    analysis_candidate_key: Mapped[str | None] = mapped_column(
        Text, comment="来源任务内候选标识；空为人工创建，不随人工修订改变"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="逻辑删除时间，带时区；为空表示可用，非空表示随功能分类一起删除，历史与来源保留",
    )
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_requirement_rule_project"),
        UniqueConstraint("project_id", "number", name="uq_requirement_rule_number"),
        UniqueConstraint("project_id", "request_id", name="uq_requirement_rule_request"),
        ForeignKeyConstraint(
            ["project_id", "category_id"],
            ["requirement_category.project_id", "requirement_category.id"],
            name="fk_requirement_rule_category",
        ),
        CheckConstraint(
            "status IN ('NEEDS_INFO','REVIEW','CONFIRMED')", name="ck_requirement_rule_status"
        ),
        {"comment": "项目共享验收点当前业务内容；分类变更不改变业务版本和审核状态"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="验收点主键")
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    number: Mapped[int] = mapped_column(Integer, comment="项目内永久递增展示编号")
    request_id: Mapped[str] = mapped_column(String(36), comment="新建请求UUID，用于防止重复创建")
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="功能点或模块ID；为空表示待归类"
    )
    version: Mapped[int] = mapped_column(
        Integer, comment="业务及审核版本号，从1递增；分类操作不递增"
    )
    title: Mapped[str] = mapped_column(Text, comment="验收点名称")
    role: Mapped[str] = mapped_column(Text, comment="适用业务角色；空字符串表示未填写")
    preconditions: Mapped[str] = mapped_column(Text, comment="业务前置条件；空字符串表示未填写")
    action: Mapped[str] = mapped_column(Text, comment="业务操作步骤")
    expected: Mapped[str] = mapped_column(Text, comment="场景预期结果")
    question: Mapped[str] = mapped_column(Text, comment="需要补充的问题；空字符串表示无问题")
    resolution: Mapped[str] = mapped_column(
        Text, comment="问题处理结论或人工确认说明；空字符串表示未填写"
    )
    status: Mapped[str] = mapped_column(
        Text, comment="审核状态：NEEDS_INFO待补充、REVIEW待审核、CONFIRMED已确认"
    )
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="最后修改或审核的用户ID"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最后业务修改或审核时间，带时区"
    )


class RequirementHistory(Base):
    __tablename__ = "requirement_history"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["requirement_rule.project_id", "requirement_rule.id"],
            name="fk_requirement_history_rule",
        ),
        UniqueConstraint("rule_id", "version", name="uq_requirement_history_version"),
        {"comment": "不可覆盖的验收点业务和审核版本快照，含固定资料来源"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="历史记录主键"
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), comment="所属项目ID")
    rule_id: Mapped[int] = mapped_column(BigInteger, comment="所属验收点ID")
    version: Mapped[int] = mapped_column(Integer, comment="本次业务审核版本号")
    snapshot: Mapped[dict] = mapped_column(
        JSONB, comment="完整业务内容、确认状态及来源版本快照，不随当前修改"
    )
    actor_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), comment="本次操作用户ID")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="版本创建时间，带时区"
    )


class RequirementSource(Base):
    __tablename__ = "requirement_source"
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "rule_id"],
            ["requirement_rule.project_id", "requirement_rule.id"],
            name="fk_requirement_source_rule",
        ),
        ForeignKeyConstraint(
            ["project_id", "document_version_id"],
            ["document_version.project_id", "document_version.id"],
            name="fk_requirement_source_document",
        ),
        CheckConstraint("role IN ('DOCUMENT','PROTOTYPE')", name="ck_requirement_source_role"),
        UniqueConstraint("rule_id", "document_version_id", name="uq_requirement_source_version"),
        {"comment": "验收点当前固定文档或原型图版本来源；历史来源保留在验收点版本中"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="来源记录主键"
    )
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id"), comment="所属项目ID")
    rule_id: Mapped[int] = mapped_column(BigInteger, comment="关联验收点ID")
    document_version_id: Mapped[int] = mapped_column(
        BigInteger, comment="固定资料版本ID，不自动切换新版"
    )
    role: Mapped[str] = mapped_column(Text, comment="资料用途：DOCUMENT需求文档、PROTOTYPE原型图")
    location: Mapped[str] = mapped_column(
        Text, comment="人工填写的章节、单元格或页面位置；空字符串表示整份资料"
    )
    excerpt: Mapped[str] = mapped_column(Text, comment="人工摘录或对照说明；不代表机器验证的原文")


class RequirementClassification(Base):
    __tablename__ = "requirement_classification"
    __table_args__ = ({"comment": "分类新增、改名、移动及撤销的审计记录，仅保存分类字段"},)
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="分类操作主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    actor_id: Mapped[int] = mapped_column(ForeignKey("user_account.id"), comment="操作用户ID")
    before: Mapped[dict] = mapped_column(
        JSONB, comment="操作前涉及分类及验收点归属；新增分类时对应项为空"
    )
    after: Mapped[dict] = mapped_column(JSONB, comment="操作后分类及验收点归属，用于撤销冲突检查")
    undone: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), comment="是否已撤销，真表示不能再次撤销"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="分类操作时间，带时区"
    )


class AnalysisAcceptance(Base):
    __tablename__ = "analysis_acceptance"
    __table_args__ = (
        UniqueConstraint("project_id", "module", "record_id", name="uq_analysis_acceptance_record"),
        CheckConstraint("revision >= 1", name="ck_analysis_acceptance_revision"),
        {"comment": "五类AI分析的独立人工验收；不改变原报告与业务处理"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="验收记录主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    module: Mapped[str] = mapped_column(
        String(20), comment="分析模块：requirements/generate/coverage/code/changes"
    )
    record_id: Mapped[int] = mapped_column(
        BigInteger, comment="原分析记录ID；需求模块为风险报告ID，其他为任务或run ID"
    )
    source_token: Mapped[str] = mapped_column(
        String(64), comment="固定原始报告内容标识；原报告变化时验收失效且不冒用旧结论"
    )
    state: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="逐条有效性与依据核验、回归可用性、人工遗漏与基准清单及范围结论",
    )
    history: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="每次人工保存的完整验收状态、操作者及时间审计；原件不覆盖",
    )
    revision: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="验收并发修订号；从1开始"
    )
    updated_by: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="最近保存验收的项目成员ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="首次人工验收保存时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近人工验收保存时间；带时区"
    )


class CaseGenerationRun(Base):
    __tablename__ = "case_generation_run"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "actor_id", "request_id", name="uq_case_generation_run_request"
        ),
        {"comment": "用例生成记录及固定准备输入、分批计划、独立人工处理"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="发起人ID；使用本人AI"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="准备请求UUID；同项目同用户幂等")
    title: Mapped[str] = mapped_column(String(200), comment="生成记录名称")
    mode: Mapped[str] = mapped_column(String(16), comment="INITIAL首次生成或UPDATE维护")
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="PREPARED",
        comment="PREPARED待确认、QUEUED排队、RUNNING处理中、COMPLETED完成、FAILED失败、CANCELLED取消",
    )
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="完整固定生成输入；不含凭据"
    )
    metadata_snapshot: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="固定Skill、来源绑定和请求摘要；不含密钥"
    )
    handling: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="候选人工草稿、澄清、应用映射及审计；原报告不改写"
    )
    revision: Mapped[int] = mapped_column(Integer, server_default="1", comment="人工操作并发修订号")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="分析记录逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除本分析记录的用户ID；空表示未删除"
    )


class CaseGenerationBatch(Base):
    __tablename__ = "case_generation_batch"
    __table_args__ = (
        UniqueConstraint("run_id", "batch_ref", name="uq_case_generation_batch_request"),
        {"comment": "用例生成固定批次及原始报告；失败只人工重试"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("case_generation_run.id"), index=True, comment="所属生成记录ID"
    )
    batch_ref: Mapped[str] = mapped_column(String(200), comment="固定计划批次标识；重试沿用")
    request_id: Mapped[str] = mapped_column(String(36), comment="实际本次模型调用请求UUID")
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="本次调用人ID；重试使用重试者AI"
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="PREPARED",
        comment="PREPARED未发起、QUEUED排队、RUNNING处理中、COMPLETED完成、FAILED失败、CANCELLED取消",
    )
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="本批固定输入；重试仅更换请求身份"
    )
    report: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="严格校验后的原始本批报告；未成功为空"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    attempts: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="每次调用的候选标识、状态、开始/进度时间及安全诊断；人工重试保留历史，不含密钥或上游原文",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败码；无原始上游错误"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )


class CaseGenerationApplication(Base):
    __tablename__ = "case_generation_application"
    __table_args__ = (
        UniqueConstraint("run_id", "request_id", name="uq_case_generation_application_request"),
        {"comment": "人工确认用例直接入库的结果审计；逐条事务，历史后台批次保留"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("case_generation_run.id"), index=True, comment="所属生成记录ID"
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), comment="所属项目ID"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="统一确认人ID；本次设计审核人"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="应用请求UUID；幂等防重复写入")
    fingerprint: Mapped[str] = mapped_column(String(64), comment="确认集合及草稿版本摘要")
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="FAILED",
        comment="COMPLETED本次处理完成；FAILED提交中或未完成，已成功项保留；QUEUED和RUNNING仅历史后台记录",
    )
    items: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="固定条目操作、版本、草稿、状态、失败原因和成功映射；每条独立事务",
    )
    error_code: Mapped[str] = mapped_column(
        String(100),
        server_default="",
        comment="本次提交未完成原因；generation_submission_interrupted表示尚有未完成项，空表示处理完结；条目错误见items",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )


class CaseGenerationChatTurn(Base):
    __tablename__ = "case_generation_chat_turn"
    __table_args__ = (
        UniqueConstraint("run_id", "request_id", name="uq_case_generation_chat_turn_request"),
        Index(
            "uq_generation_chat_active",
            "run_id",
            "function_key",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        {"comment": "用例生成记录及功能隔离的本人AI对话轮次"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("case_generation_run.id"), index=True, comment="所属生成记录ID"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="本轮提问者ID；只使用其个人AI"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="对话请求UUID；记录内幂等")
    function_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="固定功能ref；整体对话为空"
    )
    finding_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="引用候选或问题key；无引用为空"
    )
    question: Mapped[str] = mapped_column(Text, comment="本轮人工提问")
    answer: Mapped[str] = mapped_column(Text, server_default="", comment="完整模型回答；未完成为空")
    context: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="本记录本功能固定输入、报告、人工处理与已完成历史"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队、RUNNING回答中、COMPLETED完成、FAILED失败、CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )


class CaseLifecycleRecord(Base):
    __tablename__ = "case_lifecycle_record"
    __table_args__ = ({"comment": "用例人工启停历史；不改变设计版本和旧测试结果"},)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), comment="所属项目ID"
    )
    case_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("managed_case.id"), comment="所属用例ID"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="人工启停操作者ID"
    )
    lifecycle: Mapped[str] = mapped_column(String(16), comment="ACTIVE活动或RETIRED停用")
    reason: Mapped[str] = mapped_column(Text, comment="人工启停理由")
    basis: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="来源生成记录及候选、或人工操作依据"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )


class CaseAnalysisRun(Base):
    __tablename__ = "case_analysis_run"
    __table_args__ = (
        UniqueConstraint("project_id", "actor_id", "request_id", name="uq_case_analysis_request"),
        {"comment": "用例分析记录；固定输入、原报告与独立人工处理"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="分析记录主键"
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id"), index=True, comment="所属项目ID"
    )
    actor_id: Mapped[int] = mapped_column(
        ForeignKey("user_account.id"), comment="本次执行发起人；只用本人AI"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="项目内本人请求UUID；幂等")
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_analysis_run.id"), comment="复核或重试来源ID；首次为空"
    )
    title: Mapped[str] = mapped_column(String(200), comment="分析名称")
    mode: Mapped[str] = mapped_column(String(16), comment="COMPARE对照需求或QUALITY仅质量")
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="PREPARED",
        comment="PREPARED待开始/QUEUED排队/RUNNING分析/COMPLETED完成/FAILED失败/CANCELLED取消",
    )
    input_snapshot: Mapped[dict] = mapped_column(
        JSONB, comment="完整固定资料、批注、用例内部ID和设计版本；无密钥"
    )
    metadata_snapshot: Mapped[dict] = mapped_column(
        JSONB, comment="资料授权绑定、Skill指令版本哈希、准备请求摘要"
    )
    report: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="校验后的原始报告；未完成为空对象"
    )
    handling: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="人工问题处理、草案和应用审计；原报告不变"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    attempts: Mapped[list] = mapped_column(
        JSONB, server_default="[]", comment="每次固定输入执行的原始响应及安全诊断，失败仍保留"
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码；空表示无错误"
    )
    revision: Mapped[int] = mapped_column(Integer, server_default="1", comment="并发人工修订号")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间，带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="状态或处理更新时间，带时区"
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="分析记录逻辑删除时间，带时区；空表示未删除"
    )
    deleted_by: Mapped[int | None] = mapped_column(
        ForeignKey("user_account.id"), comment="删除本分析记录的用户ID；空表示未删除"
    )


class CaseAnalysisApplication(Base):
    __tablename__ = "case_analysis_application"
    __table_args__ = (
        UniqueConstraint("run_id", "request_id", name="uq_case_analysis_application_request"),
        {"comment": "人工统一确认的候选应用批次；逐条事务并保留成功和失败"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("case_analysis_run.id"), index=True, comment="所属分析记录ID"
    )
    project_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("project.id"), comment="所属项目ID"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="统一确认人ID；本次设计审核人"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="应用请求UUID；幂等防重复写入")
    fingerprint: Mapped[str] = mapped_column(String(64), comment="确认集合及草稿版本摘要")
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队、RUNNING逐条处理中、COMPLETED处理完成、FAILED暂停",
    )
    items: Mapped[list] = mapped_column(
        JSONB,
        server_default="[]",
        comment="固定条目操作、版本、草稿、状态、失败原因和成功映射；每条独立事务",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="任务级失败码；撤权或失败审计不可保存时暂停"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )


class SkillChatTurn(Base):
    __tablename__ = "skill_chat_turn"
    __table_args__ = (
        UniqueConstraint("actor_id", "skill_key", "request_id", name="uq_skill_chat_request"),
        Index(
            "uq_skill_chat_active",
            "actor_id",
            "skill_key",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        {"comment": "按管理员账号和Skill隔离的辅助修改对话；建议不直接写文件"},
    )
    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True, comment="对话轮次主键"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="提问管理员ID；仅使用其本人AI配置"
    )
    skill_key: Mapped[str] = mapped_column(String(80), comment="固定白名单中的Skill标识")
    request_id: Mapped[str] = mapped_column(String(36), comment="本人本Skill内请求UUID；防重复收费")
    fingerprint: Mapped[str] = mapped_column(
        String(64), comment="本轮问题、草稿、固定内容标识和引用的请求哈希"
    )
    question: Mapped[str] = mapped_column(Text, comment="本轮管理员修改要求")
    answer: Mapped[str] = mapped_column(
        Text, server_default="", comment="模型返回的修改说明；未完成为空"
    )
    candidate_body: Mapped[str] = mapped_column(
        Text, server_default="", comment="待人工对照的完整建议正文；不包含文件元信息；未完成为空"
    )
    raw_response: Mapped[str] = mapped_column(
        Text, server_default="", comment="本轮完整模型原始响应；失败保留；未接收为空"
    )
    context: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="固定Skill正文、契约、所选参考、内容标识及已完成对话；不包含密钥",
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队、RUNNING回答中、COMPLETED完成、FAILED失败、CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码；空表示无错误"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="提问创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态变化时间；带时区"
    )


class CaseAnalysisChatTurn(Base):
    __tablename__ = "case_analysis_chat_turn"
    __table_args__ = (
        UniqueConstraint("run_id", "request_id", name="uq_case_analysis_chat_turn_request"),
        Index(
            "uq_case_analysis_chat_active",
            "run_id",
            "function_key",
            unique=True,
            postgresql_where=text("status IN ('QUEUED','RUNNING')"),
        ),
        {"comment": "用例分析记录及功能隔离的本人AI对话轮次"},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, comment="主键")
    run_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("case_analysis_run.id"), index=True, comment="所属分析记录ID"
    )
    actor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user_account.id"), comment="本轮提问者ID；只使用其个人AI"
    )
    request_id: Mapped[str] = mapped_column(String(36), comment="对话请求UUID；记录内幂等")
    function_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="固定功能ref；整体对话为空"
    )
    finding_key: Mapped[str] = mapped_column(
        String(200), server_default="", comment="引用候选或问题key；无引用为空"
    )
    question: Mapped[str] = mapped_column(Text, comment="本轮人工提问")
    answer: Mapped[str] = mapped_column(Text, server_default="", comment="完整模型回答；未完成为空")
    context: Mapped[dict] = mapped_column(
        JSONB, server_default="{}", comment="本记录本功能固定输入、报告、人工处理与已完成历史"
    )
    ai_config: Mapped[dict] = mapped_column(
        JSONB,
        server_default="{}",
        comment="固定AI方式、本人配置名称/模型/强度/修订号及客户端版本；历史缺方式按API，不含密钥",
    )
    status: Mapped[str] = mapped_column(
        String(16),
        server_default="QUEUED",
        comment="QUEUED排队、RUNNING回答中、COMPLETED完成、FAILED失败、CANCELLED取消",
    )
    error_code: Mapped[str] = mapped_column(
        String(100), server_default="", comment="安全失败原因码"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="创建时间；带时区"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), comment="最近状态时间；带时区"
    )
