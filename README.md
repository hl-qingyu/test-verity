# Test Verity · 质序

面向测试、产品和开发人员的内部软件质量分析平台。将需求、原型、代码和测试用例放到同一项目中，完成五类分析，再由人工核对和处理结果。

前端使用 React、TypeScript 和 Vite，后端使用 Python、FastAPI 和 SQLAlchemy，数据库为 PostgreSQL。AI任务由独立后台进程执行，上传文件和原始结果保存在后端私有目录。

## 当前功能

| 功能 | 已有能力 |
| --- | --- |
| 项目概览 | 资料与用例统计、五类分析入口、近期记录、待处理事项和详情跳转 |
| 需求资料 | 文件上传、分组排序、历史版本、原件下载、Markdown附件关联、删除影响预览 |
| 原型资料 | 图片、网页、原型链接、GitHub原型代码、本地目录；支持预览、文件选择和固定版本 |
| 用例管理 | 默认14列、分类、组合筛选、跨页选择、单条和批量编辑、Excel/CSV导入、导出、设计版本、测试记录、停用恢复 |
| 需求分析 | 从资料生成风险报告，查看功能、依据、影响和建议；支持累计清单、人工处理、对话、人工添加风险和导入导出 |
| 用例生成 | 首次生成或维护已有用例，选择资料和用例范围，人工修订、业务澄清、重复处理、单条或批量审核入库 |
| 用例分析 | 对照需求检查或只检查用例质量，处理问题、保存草稿、应用修订和关联复核 |
| 代码分析 | 读取GitHub固定提交或本地文件，检查缺陷、需求偏差和前后端不一致，保存处理记录和对话 |
| 变更分析 | 比较需求、原型或代码的新旧版本，查看变化、影响、风险和回归建议，支持历史问题对照和完整导出 |
| 问题结果修订 | 保留未通过检查的原始结果和冲突值，人工修改后重新检查，不另调AI |
| 分析规则管理 | 查看五类本地规则包；管理员可编辑主说明、保留备份，并用本人AI辅助修改 |
| AI结果验收 | 管理员查看全部项目或单项目的处理与采纳情况；各记录可补遗漏和人工基准 |
| 项目设置 | 基本信息、成员、GitHub仓库关联、本地代码目录 |
| 平台设置 | 个人AI服务、个人GitHub连接、管理员账号管理 |

正式页面由 `frontend/src/App.tsx` 装配，后端接口由 `backend/app/api/router.py` 装配。详细规则见[文档目录](docs/README.md)。

## 分析和审核

需求、代码和变更分析提交后进入后台队列。用例生成和用例分析先读取并保存本次资料，再由用户确认开始调用AI。

每次任务保留所选资料、版本、文件范围、分析规则和调用配置。后续上传资料或修改规则，不会改写已有任务的输入。AI结果、人工处理和用例入库分别记录。

- **用例生成入库**：确认后在当前请求中逐条保存，一条失败不影响其他成功项。
- **用例分析应用修订**：由后台任务处理，提交后需查看实际结果。
- **问题候选**：原文和人工修订均保留，通过检查后继续相应审核。用例生成的问题建议单独处理，其他有效建议可继续审阅。
- **取消和重试**：按模块权限与状态执行。关闭页面不停止后台任务；平台不自动新建收费重试任务。

AI分析不运行项目代码或执行测试。保存报告、人工认可和测试通过是不同状态；生成用例默认未测。

## 权限

| 身份 | 权限 |
| --- | --- |
| 平台管理员 | 管理账号、访问项目、管理项目配置、查看AI验收汇总、编辑分析规则 |
| 项目负责人 | 管理所负责项目的信息、成员和仓库，使用项目内业务功能 |
| 项目成员 | 使用已加入项目的资料、用例、分析和人工处理功能；不能管理成员或项目配置 |

测试、开发、产品、经理等平台角色不自动获得项目管理权，项目负责人单独指定。普通用户可创建由本人负责的项目。

AI和GitHub配置归个人所有，分析和对话使用操作者本人配置。报告按项目权限共享，原始失败候选另受发起人权限限制。

账号由管理员创建，不提供公开注册或找回密码页面。首个管理员通过本机命令创建。

## 运行环境

| 组件 | 要求 |
| --- | --- |
| Python | 3.12–3.14，依赖固定在 `backend/pyproject.toml` |
| Node.js | 前端建议22或24；CLI标准文件服务需要24以上，按各package-lock.json安装依赖 |
| PostgreSQL | 推荐17，根目录提供可选数据库容器配置 |
| 浏览器 | 支持Web Crypto；本地目录功能还需支持目录选择并授予只读权限 |
| Codex命令行 | 可选，在后端Windows环境运行，当前固定版本0.166.0 |

启动脚本面向Windows。当前使用一个API进程和一个后台调度进程；调度进程内按配置并发执行任务。不要通过增加API或后台进程数扩容。

## 启动已有环境

依赖已安装且 `backend/.env` 已配置时，在项目根目录运行：

```powershell
.\start-dev.ps1
```

| 入口 | 地址 |
| --- | --- |
| 前端 | [http://127.0.0.1:5173](http://127.0.0.1:5173) |
| 接口文档 | [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| API存活检查 | [http://127.0.0.1:8000/api/health/live](http://127.0.0.1:8000/api/health/live) |
| 数据库就绪检查 | [http://127.0.0.1:8000/api/health/ready](http://127.0.0.1:8000/api/health/ready) |

前端将 `/api` 请求代理到本机8000端口。就绪检查实际查询数据库，不可用时返回503。

单项启停和全部停止：

```powershell
.\start-dev.ps1 -Service api
.\start-dev.ps1 -Service worker
.\start-dev.ps1 -Service frontend

.\stop-dev.ps1 -Service frontend
.\stop-dev.ps1 -Service api
.\stop-dev.ps1 -Service worker
.\stop-dev.ps1
```

脚本识别本项目已有进程，其他程序占用8000或5173时拒绝启动。不安装依赖、不运行迁移、不启动数据库。PowerShell 7下会自动交给Windows PowerShell执行网络和进程检查。

停止后台进程可能中断AI任务，已发送请求仍可能计费。重启前先查看活动任务。

## 安装新环境

已有环境沿用原数据库、配置和加密密钥。下列步骤仅用于新环境。

### 1. 安装依赖

在项目根目录执行：

```powershell
python -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -e "./backend[dev]"
Set-Location frontend
npm ci
Set-Location ..
npm ci --prefix backend/mcp --ignore-scripts
```

### 2. 配置后端和数据库

```powershell
if (-not (Test-Path backend/.env)) {
    Copy-Item backend/.env.example backend/.env
}
```

填写 `backend/.env`，程序固定读取这个文件：

| 配置项 | 用途 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL连接地址，使用 `postgresql+psycopg://` 格式 |
| `AUTH_ALLOWED_ORIGINS` | 允许发起写请求的前端来源列表，包含准确的协议、主机和端口 |
| `AUTH_COOKIE_SECURE` | HTTPS环境为 `true`，本机HTTP开发为 `false` |
| `AI_ENCRYPTION_KEY` | 加密AI密钥和GitHub访问令牌的Fernet主密钥，已有环境须保留原值 |
| `AI_MAX_CONCURRENT` | AI调用并发总数，默认2 |
| `AI_MAX_PER_USER` | 每用户同时调用数，默认1 |
| `AI_MAX_PER_CREDENTIAL` | 同一服务密钥同时调用数，默认1，与连接测试共享预算 |
| `AI_CLI_EXECUTABLE` | 可选，固定版本Codex程序的绝对路径，须为Windows可执行文件 |
| `AI_CLI_WORK_PATH` | 可选，Codex任务私有工作目录 |
| `AI_CLI_NODE_EXECUTABLE` | 可选，后端Node.js 24以上可执行文件路径；默认从PATH查找node |

新环境生成主密钥后，手动填入配置。已有环境不要重新生成替换：

```powershell
backend/.venv/Scripts/python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

个人AI地址、模型、密钥和GitHub连接在登录后的平台设置中填写，不写入前端配置。

可使用已有PostgreSQL。若新建本地容器，先从根目录 `.env.example` 创建根目录 `.env` 并填写数据库密码，再运行：

```powershell
docker compose up -d db
```

根目录 `.env` 供容器读取，`backend/.env` 供应用读取，需分别填写。已有数据库无需另建容器，也不要执行删除数据库卷的清理命令。

### 3. 迁移和初始账号

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m app.init_admin
Set-Location ..
```

当前仓库迁移头为 `20261111_44`。已有环境升级前先审查迁移并备份数据库。

初始化命令在交互终端隐藏输入密码，创建登录名为 `admin` 的首个管理员。已有管理员时拒绝重建，不会重置密码。完成后可使用启动脚本。

### 前台调试

在三个终端分别启动。前两个终端在 `backend/` 中运行：

```powershell
# 终端一：API
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

# 终端二：分析和对话后台进程
.\.venv\Scripts\python.exe -m app.chat_worker
```

第三个终端在 `frontend/` 中运行：

```powershell
npm run dev
```

`app.chat_worker` 处理五类分析、对话和规则助手，不要启动旧的需求分析专用进程。

## AI服务和使用限制

| 方式 | 当前支持 |
| --- | --- |
| API | Responses协议，接收完整结果；支持文字及相应模块提供的图片、PDF输入 |
| Codex命令行 | 后端Windows机器运行固定版本，使用个人独立配置；支持文字、图片及大输入文件读取，PDF需用API |

两套配置独立保存。保存不调用模型；连接测试可能计费，但不保存或启用配置。CLI程序未配置或版本不符时，可保存配置，不能启用运行任务。

API分析和对话不设置平台总时长或读写等待上限；资料读取、模型列表和固定文字连接测试保留有限等待。上游仍可能拒绝、断开或超时，平台会记录失败，不自动换方式重发。

Codex命令行允许原生多轮请求、内部重试和上下文压缩。大输入使用独立任务文件和受限只读工具，工具只读取该任务保存的输入。

Claude和DeepSeek独立入口未接入。平台不自动执行测试、修复代码或写回远端仓库。原型链接采集仅支持已适配站点，不是任意网站抓取工具。

需求对话的会话附件和补充系统资料尚未接入；原型中的对应入口不代表正式功能已可用。通用目录按需读取仍是方案，当前Codex工具只读本次保存的输入文件。

## 数据和日志

数据库保存账号、项目、资料元数据、版本、任务、报告、对话和人工处理。私有文件默认位于 `backend/storage/`：

| 目录 | 内容 |
| --- | --- |
| `documents/` | 上传原件和目录版本 |
| `requirement-analysis-results/`、`code-analysis-results/`、`change-analysis-results/`、`case-generation-results/` | 相应模块原始结果和候选文件 |
| `candidate-reviews/` | 人工修订记录 |
| `skill-backups/` | 规则编辑备份 |
| `ai-response-errors/` | 脱去实际密钥后加密保存的上游错误 |
| `codex-exec/` | Codex任务私有目录 |

迁移环境时需同时保存数据库、私有文件和原加密主密钥。只备份数据库不能恢复全部附件和原始结果。资料、项目和分析记录的删除保留相应历史依据，已入库用例不会随报告删除撤回。

应用日志位于 `log/api.log`、`log/chat-worker.log`，按大小轮转，不写密钥、完整提示词、公司原文或上游原始错误正文。详见[日志说明](docs/LOGGING.md)。

## 检查命令

前端，在 `frontend/` 中执行：

```powershell
npm run check
npm test
npm run build
```

后端，在 `backend/` 中执行：

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests migrations
.\.venv\Scripts\python.exe -m ruff format --check app tests migrations
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

数据库测试默认跳过。准备好已迁移的测试数据库后，显式启用：

```powershell
$env:RUN_AUTH_DB_TESTS = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
Remove-Item Env:RUN_AUTH_DB_TESTS
```

数据库测试通常通过事务回滚隔离；外部AI和GitHub使用模拟响应，测试通过不代表真实服务已验证。部分CLI进程测试仅在Windows运行。

后端模块改动需运行 `tests/test_architecture.py`。数据库结构改动还需检查 `tests/test_database_comments.py`，核对真实库中文注释及迁移：

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic check
```

界面改动还需对照原型验收布局、弹窗、窄屏、键盘和焦点。

## 项目目录

```text
frontend/                 页面、主题组件、业务请求和前端测试
backend/
  app/
    main.py               API应用、异常处理和健康检查
    chat_worker.py        分析和对话调度进程
    api/                  接口装配、身份依赖、请求加密适配
    core/                 配置、错误类型和日志
    db/                   数据库连接和模型
    security/             密码、会话、凭据和来源内容检查
    integrations/         AI、GitHub和原型读取等外部协议
    modules/              业务路由、数据校验和服务
  migrations/             Alembic迁移
  tests/                  回归、架构和数据库检查
  storage/                私有运行数据，不提交
skill/                    业务分析规则、结果契约和引用文件
docs/                     工程规则、模块说明和历史资料
tests/                    启动脚本检查
log/                      运行日志，不提交
outputs/                  原型检查、备份和临时交付文件
```

## 文档和开发约定

- 开发先读 [AGENTS.md](AGENTS.md)、[架构说明](docs/ARCHITECTURE.md)和[代码规范](docs/CODE_STANDARDS.md)；界面任务另读[界面规范](docs/UI_STANDARDS.md)。
- [文档目录](docs/README.md)列出当前模块说明；[整理清单](docs/DOCUMENT_REVIEW.md)说明哪些仍有效、哪些只作历史参考。
- [会话交接](docs/SESSION_CONTEXT.md)按任务检索，不必每次通读；进程、版本和验证结果只代表记录时状态。
- 界面以根目录的 [verity-prototype.html](verity-prototype.html) 为准，后续原型修改直接在此文件进行。[业务说明](docs/prototypes/verity-business-rules/README.md)介绍说明栏的维护方式，原型不执行真实分析。
- 平台Git集成只读，不提供远端推送、修改文件、创建或合并请求、评论等写操作。本仓库也不在未经授权时推送或部署。

局域网临时试用使用 `start-lan.ps1`，会调整允许来源和Cookie配置，并开放前端局域网监听。跨机器访问还有浏览器安全上下文要求，使用前阅读[局域网试用说明](docs/LAN_TRIAL.md)。正式访问需另行配置HTTPS和部署环境。
