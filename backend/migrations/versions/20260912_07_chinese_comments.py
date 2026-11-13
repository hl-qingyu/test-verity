"""Add Chinese database comments only; preserve all data and constraints."""

from alembic import op

revision = "20260912_07"
down_revision = "20260912_06"
branch_labels = None
depends_on = None

# Frozen migration data; never import mutable application models here.
COMMENTS = {
    "user_account": {
        "table": "平台用户账号，包含身份、状态与登录安全信息",
        "columns": {
            "id": "记录主键",
            "login_name": "登录账号，小写且全局唯一，逻辑删除后不可复用",
            "display_name": "用户显示名称",
            "password_hash": "scrypt密码哈希及随机盐，不保存明文密码",
            "platform_role": "平台角色：ADMIN管理员，USER普通用户",
            "status": "账号状态：ACTIVE启用，DISABLED停用，DELETED逻辑删除",
            "ai_source": "当前AI使用来源：PLATFORM平台统一，PERSONAL个人配置",
            "ai_source_version": "AI使用来源的乐观锁版本号",
            "failed_login_count": "连续登录失败次数，取值0至5",
            "locked_until": "登录锁定截止时间；为空表示未锁定",
            "deleted_at": "逻辑删除时间；为空表示未删除",
            "created_by": "创建人用户ID，关联user_account.id",
            "updated_by": "最后修改人用户ID，关联user_account.id",
            "created_at": "创建时间，带时区",
            "updated_at": "最后更新时间，带时区",
        },
    },
    "ai_connection": {
        "table": "个人或平台统一的AI服务配置，密钥以密文保存",
        "columns": {
            "id": "配置主键：0为平台统一配置，其他值为所属用户ID",
            "owner_id": "所属用户ID；平台统一配置为空",
            "name": "AI连接配置名称",
            "base_url": "允许访问的AI服务基础地址",
            "model": "模型标识，按配置原样传给上游",
            "reasoning_effort": "推理强度：default使用上游默认，其他配置值原样传递",
            "encrypted_key": "AI访问密钥密文，使用后端主密钥加密",
            "version": "乐观锁版本号，用于防止并发修改覆盖",
            "updated_by": "最后修改人用户ID，关联user_account.id",
            "updated_at": "最后更新时间，带时区",
        },
    },
    "github_connection": {
        "table": "用户自有GitHub连接及加密访问凭据",
        "columns": {
            "id": "记录主键",
            "owner_id": "连接所属的平台用户ID，仅本人使用凭据",
            "name": "GitHub连接显示名称",
            "kind": "范围类型：personal个人、organization组织、automatic自动发现",
            "resource_owner": "兼容旧版的资源所属方；自动发现模式记录登录账号，不限制仓库所属方",
            "github_login": "访问凭据对应的GitHub登录账号",
            "encrypted_token": "GitHub访问令牌密文，支持已授权的Classic及Fine-grained Token",
            "version": "乐观锁版本号，用于防止并发修改覆盖",
            "updated_at": "最后更新时间，带时区",
        },
    },
    "project": {
        "table": "项目基本信息与负责人",
        "columns": {
            "id": "记录主键",
            "name": "项目名称",
            "identifier": "项目唯一标识，保存为小写",
            "description": "项目说明，默认空字符串",
            "owner_id": "项目负责人用户ID，关联user_account.id",
            "created_by": "创建人用户ID，关联user_account.id",
            "version": "乐观锁版本号，用于防止并发修改覆盖",
        },
    },
    "user_session": {
        "table": "用户登录会话，保存令牌哈希、有效期与撤销时间",
        "columns": {
            "id": "记录主键",
            "user_id": "用户ID，关联user_account.id",
            "token_hash": "会话令牌的SHA-256哈希，不保存原始令牌",
            "created_at": "创建时间，带时区",
            "expires_at": "会话到期时间，带时区",
            "revoked_at": "会话撤销时间；为空表示未主动撤销",
        },
    },
    "document_group": {
        "table": "项目内的原始资料分组，允许空分组",
        "columns": {
            "id": "记录主键",
            "project_id": "所属项目ID，关联project.id",
            "name": "资料分组名称，同项目内唯一",
        },
    },
    "document_library": {
        "table": "项目资料库并发版本控制",
        "columns": {
            "project_id": "所属项目ID，关联project.id",
            "revision": "资料库并发修订号，资料整理或上传后递增",
        },
    },
    "github_repository": {
        "table": "GitHub连接下明确选择授权的仓库",
        "columns": {
            "connection_id": "所属GitHub连接ID，与仓库ID组成联合主键",
            "github_id": "GitHub仓库的远端唯一ID",
            "full_name": "GitHub仓库完整名称，格式为所属方/仓库名",
            "default_branch": "发现授权仓库时记录的默认分支",
            "private": "是否为GitHub私有仓库",
            "owner_type": "仓库所属方类型：User个人，Organization组织",
        },
    },
    "project_member": {
        "table": "项目成员关系，负责人另由项目表记录",
        "columns": {
            "project_id": "所属项目ID，关联project.id",
            "user_id": "用户ID，关联user_account.id",
        },
    },
    "project_repository": {
        "table": "项目关联的GitHub仓库元数据，不共享个人访问凭据",
        "columns": {
            "id": "记录主键",
            "project_id": "所属项目ID，关联project.id",
            "github_id": "GitHub仓库的远端唯一ID",
            "full_name": "GitHub仓库完整名称，格式为所属方/仓库名",
            "kind": "代码类型：BACKEND后端、FLUTTER应用、WEB前端、OTHER其他",
            "default_branch": "默认分析分支名称",
            "version": "乐观锁版本号，用于防止并发修改覆盖",
            "updated_by": "最后修改人用户ID，关联user_account.id",
        },
    },
    "source_document": {
        "table": "原始资料逻辑记录，保存分组、排序与当前版本",
        "columns": {
            "id": "记录主键",
            "project_id": "所属项目ID，关联project.id",
            "group_id": "所属资料分组ID；为空表示未分组，分组必须属于同项目",
            "position": "组内排序值，按升序展示",
            "current_version": "当前资料版本号，关联同一资料的document_version.number",
        },
    },
    "document_version": {
        "table": "资料的不可覆盖历史版本及私有原件存储信息",
        "columns": {
            "id": "记录主键",
            "project_id": "所属项目ID，关联project.id",
            "document_id": "所属原始资料ID，必须属于同项目",
            "number": "资料版本号，同一资料内唯一且大于0",
            "filename": "上传时的原始文件名",
            "extension": "文件扩展名，用于预览类型判断",
            "media_type": "文件MIME类型",
            "size": "原始文件大小，单位字节，必须大于0",
            "sha256": "原始文件内容的SHA-256摘要",
            "storage_key": "私有原件存储键，随机32位标识，不是用户提供的路径",
            "upload_id": "上传请求UUID，用于项目内重复请求识别",
            "created_by": "创建人用户ID，关联user_account.id",
            "created_at": "创建时间，带时区",
        },
    },
    "alembic_version": {
        "table": "数据库迁移版本记录，由Alembic维护",
        "columns": {"version_num": "当前已执行的Alembic迁移版本号"},
    },
}


def upgrade() -> None:
    for table, comments in COMMENTS.items():
        op.create_table_comment(table, comments["table"], existing_comment=None)
        for column, comment in comments["columns"].items():
            op.alter_column(table, column, comment=comment, existing_comment=None)


def downgrade() -> None:
    # All targets had no comments before this revision; only remove these comments.
    for table, comments in COMMENTS.items():
        for column, comment in comments["columns"].items():
            op.alter_column(table, column, comment=None, existing_comment=comment)
        op.drop_table_comment(table, existing_comment=comments["table"])
