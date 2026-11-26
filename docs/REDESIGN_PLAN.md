# 重构与重设计实施方案

2026-11-25 整理，方向已确认。工作区实施进度及验证范围见 [会话交接](SESSION_CONTEXT.md#2026-11-26重构与重设计实施)。需求风险 v4 覆盖原型已确认并在工作区接入。已实施行为以各模块说明为准，下文保留任务包的设计依据。

本文取代 [AI_OPTIMIZATION_PLAN.md](AI_OPTIMIZATION_PLAN.md) 中尚未实施的安排：T1、T2 并入 O1、O2；T6 简化后并入 O1；T3、T4 等 O1 有用量数据后再决定；T5、T7、T8、T9、T10–T13 取消或暂缓（理由见第二节决策 8）。

---

## 一、问题与证据（摘要）

结论：主要问题不在代码风格，而在于把“证明模型读完、做全”的责任交给了模型本身，导致大输入在输入侧和输出侧都必然失败；之后大量会话花在传输层和失败后的手工恢复上。代码重复和历史兼容是第二层问题。

| 问题 | 证据 | 任务包 |
| --- | --- | --- |
| 契约要求模型逐片段输出覆盖台账，并自算总体结论 | 变更分析每侧每个文件一条 coverage，每个片段一条 segment_review（`change_analysis/contract.py:875-890`）；代码分析每个片段 × 3 个目标（`code_analysis/contract.py:566-588`）；需求风险每份资料每个片段（`requirements/risk_schemas.py:393-410`）。413 号任务两侧各 3327 个文件，仅 coverage 就超过 6654 条，远超 32000 输出上限 | N2、N3、N5 |
| 小瑕疵导致整单作废，靠一次性脚本恢复 | #95 `invalid_coverage`；640 证据段号错位；1423 运行 456 秒因摘录少一字被拒（用户：“这校验没必要，太严格了”）；漏 title 整批失败；重复 priority 手工恢复 63 条 | N2、N3、N5 |
| 变更分析发送两侧整仓快照 | 发给模型的 diff 只有行号区间（`change_analysis/sources.py:736-755`），没有变化文本；392 号单个 input_text 3684 万字符、请求 49.6MB；400、413、504、WebSocket 无可用账号先后出现；无变化也调用模型（`execution.py:163` 的跳过只对旧模式生效） | N2 |
| CLI 阅读目录按 4096 字符切 JSON 文本 | `cli_reading.py:208-230` 把整条消息切成 `text-NNNNNN.txt`，结构和路径会被切断；指引要求顺序读完全部（`:25-40`）；原生终端每次分析都走这条路（`codex_terminal.py:162-190`、`:525-528`）；11-17 真实会话 155 条候选 complete=false | N1–N4 |
| 两个确定的缺陷 | 用例分析后台应用可让 Worker 崩溃循环（`case_analysis/apply.py:215-245`）；API 方式下用例生成对话必然 TypeError（`case_generation/execution.py:451-460` → `responses.py:153`） | A1、A2 |
| 全量测试长期不绿 | 3 处 409 断言与 `projects/service.py:171` 自动生成标识矛盾；最新提交说明 4 项失败“改动前即复现” | A3 |
| 退役功能仍有写接口 | `requirements/router.py:198-252` 的旧验收点接口，前端已无调用 | A4 |
| 用量与输入规模不可见 | `responses.py:497-502` 算了 usage，`safe_snapshot` 未放行；需求风险、代码分析不传 diagnostics；变更分析只在失败时保存 | O1 |
| 模块间大面积复制 | `code_analysis/execution.py` 275 行中 235 行原样出现在 `change_analysis/execution.py`；`chat.py` 91/122、`candidate_review.py` 61/67 行相同；recover/失败处理/进度检查等 6–10 处复制；用例生成另有 843 行原生终端实现 | S1、S2 |
| 历史兼容与死代码 | 变更分批约 750 行无入口；`legacy_contract.py` 名不副实；WebSocket 诊断残留；前端十余个无调用函数 | C1–C4 |
| 前端重复与空转请求 | 22 个文件各写校验原语且语义不一致；8 个页面空闲时仍每 2.5–4 秒轮询；两个对话页 diff 仅 39 行；约 80 条源码正则断言 | F1–F4 |
| 文档是只追加日志，前后矛盾 | `AI_CODEX_CLI_IMPLEMENTATION.md` 同时写“不能激活”和“已可用”；`AI_SERVICE.md` 仍描述已删除的平台配置接口；两份原型 1.7MB / 1.1MB 已分叉 | W1 |

证据来源：代码、文档（含 SESSION_CONTEXT）和 6 次提交；仓库内无运行数据和依赖环境，上述缺陷为读代码确认，未执行复现。

---

## 二、已确认决策与默认取舍

用户确认“都按你说的来”。下列取舍按此执行；第 3–6 项是原判断中留给用户选择、现按建议默认的项，若需改变，在对应任务包开工前提出即可，均可逆。

| # | 决策 | 依据 | 影响任务 |
| --- | --- | --- | --- |
| 1 | 需求、代码、变更三类出新契约版本：覆盖情况和总体结论由平台计算，模型不再输出覆盖台账；旧任务按旧契约不变 | 第一节前两行 | N2、N3、N5 |
| 2 | 修改 `CODE_STANDARDS.md:61`：新建变更分析改为“差异优先”输入，完整根输入照常保存，CLI 另以只读文件提供两侧完整快照；无变化不调用模型 | 第一节第三行 | N2 |
| 3 | 变更旧分批：删除无入口的规划和执行代码；保留查看、导出和免费重新校验，冻结为只读适配器 | 免费恢复能力符合“不追加收费调用”；重新校验不调用模型 | C1 |
| 4 | 用例生成 v2：旧记录照常查看、审核、入库；v2 失败批次重试和 v2 包导入改为明确拒绝，提示新建生成 | 改走 v3 会替换原批次 Skill 快照，违反“不静默覆盖”；v2 与 v3 同日出现，旧记录极少 | C2 |
| 5 | 旧验收点：移除 11 个接口（含只读接口），保留表、迁移和资料删除时的引用计数 | 前端自 9 月起无调用 | A4 |
| 6 | 项目标识按现行实现：平台自动生成、允许同名；修改 3 处过期断言和 `GITHUB_PROJECTS.md:78` | 前端只读展示标识，服务每次生成 `proj-uuid` | A3 |
| 7 | 不改动：调用预约、凭据 HMAC 分组、加密结果文件、加密日志 | 均为此前确认的安全与防重复收费决策，改动收益不确定 | — |
| 8 | 取消或暂缓原优化方案的 T5、T7、T8、T9、T10–T13 | T5 前提不成立：快照带版本校验，配置一改任务即 409，不会用错强度。T7/T10–T13 需新表、五模块 PARTIAL 状态、五套契约与合并逻辑和 TUI 自动键入，而输出超限的根因由 N2/N3/N5 消除，部分失败已有候选审核隔离；N 系列完成后若 O1 数据仍显示常撞上限，再只对用例生成试点，并优先评估经 app-server 协议提交轮次而非模拟键盘。T8 被 N2 取代。T9 价值低 | — |
| 9 | 审阅副本 `docs/prototypes/verity-requirement-risk-review.html` 停止同步，页首标注冻结；只维护根目录总原型 | 两份已分叉，双份维护成本高 | W1 |

---

## 三、总体原则（所有任务包共用）

1. 不增加自动收费重试，不回退平台密钥，只用本人配置；实施者不发起真实模型调用、不推送、不部署，上游一律模拟。真实调用验收见第八节，须用户单独授权。
2. 固定输入、Skill 快照、原始响应、人工处理和历史结果不改写。新契约用新版本号，旧任务按原版本读取、校验、重试。
3. 保持分层：`integrations` 不导入 `app.db`、`app.modules`；router 不写 SQL、不调 integrations；service 不导入 HTTP 层。以 `tests/test_architecture.py` 为准。
4. 已落库并在前端有映射的错误码字符串逐字保留；新增错误码同步前端中文文案。
5. 本方案预计不需要数据库迁移（契约版本无库约束，新数据写入现有 JSONB）。若实施中发现需要，按 AGENTS.md 走 Alembic、中文 COMMENT 和一致性检查，最新迁移为 `20261120_46_analysis_terminal_resume.py`。
6. 涉及界面变化的（N5、C2 的错误文案）先改根目录 `verity-prototype.html` 及其业务说明，经用户确认再改正式页面。纯重构（F 系列）不改 DOM 结构、class 和文案。
7. 每个任务包单独分支、单独提交；A3 完成后，全量后端与前端测试通过是每个任务包的合入条件。
8. 删除代码前用 grep 和调用链确认无引用；涉及历史记录状态的删除先在真实库执行只读 SQL 核对。

---

## 四、任务总览与顺序

| 编号 | 名称 | 对应判断 | 依赖 | 原型 | 规模 |
| --- | --- | --- | --- | --- | --- |
| A1 | 修复用例分析后台应用崩溃循环 | B1 | — | 否 | 小 |
| A2 | 修复 API 方式用例生成对话 | B2 | — | 否 | 小 |
| A3 | 测试基线转绿 | B3 | A1、A2 | 否 | 小–中 |
| A4 | 移除旧验收点接口 | B4 | A3 | 否 | 小 |
| O1 | 用量、输入规模与诊断落库 | T1、T6 | A3 | 否 | 小 |
| O2 | 按模块配置输出上限 | T2 | A3 | 否 | 小 |
| C1 | 变更旧分批收缩为只读适配器 | R5 | A3 | 否 | 中 |
| C2 | 用例生成 v2 冻结 | R5 | A3 | 文案 | 小 |
| C3 | 删除死代码与实验残留 | R5 | A3 | 否 | 小 |
| C4 | 合并两套 CLI 配置构造 | R5 | A3 | 否 | 小，需真实 exe |
| N1 | 结构化 CLI 阅读目录框架 + 用例生成接入 | R3 | A3 | 否 | 中，需真实 exe |
| N2 | 变更分析 v3：差异优先输入 + 平台计算覆盖 | R1、R2、R3 | N1、C1、O1 | 否 | 大 |
| N3 | 代码分析 v3：平台计算覆盖 + 阅读布局 | R1、R3 | N1、O1 | 否 | 中–大 |
| N4 | 需求风险、用例分析接入阅读布局 | R3 | N1 | 否 | 小–中 |
| N5 | 需求风险 v4：覆盖由平台反推 | R1 | N4 | 是 | 中 |
| S1 | 后端任务流程样板合并 | R4 | N3 | 否 | 中 |
| S2 | 用例生成原生终端并入 analysis_terminal | R4 | S1 | 否 | 中 |
| S3 | 调度轮询与应用执行调整 | R4 | A1 | 否 | 小 |
| F1 | 前端测试改为行为测试 | R6 | A3 | 否 | 中 |
| F2 | 前端校验工厂 `createGuards` | R6 | F1 | 否 | 小 |
| F3 | `usePolling`：有活动任务且页面可见才轮询 | R6 | F1 | 否 | 中 |
| F4 | 合并代码、变更分析对话页 | R6 | F1 | 否 | 小 |
| W1 | 模块文档重写为现行规则 | R7 | 各包完成后 | 否 | 中 |

建议顺序：

1. A1、A2 → A3 → A4。
2. O1、O2。
3. C1、C3、C4 并行；C2。
4. N1 → N2 → N3 → N4 → N5（N 系列是核心收益，优先投入）。
5. S3 可随时做；S1 → S2 在 N3 之后（N2/N3 改动的是输入构造和校验，S1 合并的是流程样板，错开以减少冲突）。
6. F1 → F2、F3、F4，与后端并行。
7. W1：每个包同步自己的文档；全部完成后统一整理一次。

---

## 五、执行方式

- 一个任务包对应一个会话和一个本地分支，命名如 `redesign/A1-apply-crash`。
- 涉及原型的（N5、C2 文案）分两步：先只改原型并由用户确认，再开发正式页面。
- 每包完成后：交付 diff、测试输出和更新后的文档 → 审核（可用 `/code-review`）→ 本地合并，中文提交说明写清改动和验证 → 不推送 → 在 `docs/SESSION_CONTEXT.md` 追加一条：已完成、未验证、待决。

提示词模板：

```text
你在 test-verity 仓库工作，先读 AGENTS.md、docs/ARCHITECTURE.md、docs/CODE_STANDARDS.md。
本次只做 docs/REDESIGN_PLAN.md 中的任务包 <A1>，范围以该章节为准。
1. 先读该章节“涉及文件”，确认与描述一致；不一致时先停下列出差异，不自行扩大范围。
2. 遵守第三节总体原则；不发起真实模型调用，不推送，不改写历史快照或数据。
3. 按“设计”实现，按“测试”补充测试并运行“验证命令”，贴出完整结果。
4. 同步“文档”中列出的文档。
5. 输出：改动文件清单、设计偏离说明、测试结果、未验证事项。不要提交。
```

验证命令（Windows，在 `backend/`、`frontend/` 下运行）：

```powershell
# 后端
.\.venv\Scripts\python.exe -m ruff check app tests migrations
.\.venv\Scripts\python.exe -m ruff format --check app tests migrations
.\.venv\Scripts\python.exe -m unittest tests.test_architecture -v
.\.venv\Scripts\python.exe -m unittest <相关测试模块> -v
.\.venv\Scripts\python.exe -m unittest discover -s tests      # A3 之后每包必跑
# 前端（有改动时）
npm run check; npm test; npm run build
# 原型（有改动时）
node ..\docs\prototypes\check-<对应模块>.cjs
```

审核要点（每包都查）：没有新增自动重试；错误码字符串未变；旧版本任务行为不变且有测试；`safe_snapshot` 没有放行任意上游文本；CLI 分支没有收到 API 专用参数；删除的代码确无引用。

---

## 六、任务包详细设计

### A1 修复用例分析后台应用崩溃循环

**证据**：`case_analysis/apply.py:215` 的 `service.own` 在 `index` 赋值（`:216`）之前抛出非 401/403 的 AppError（如项目访问返回 404）时，except 分支 `data[index]`（`:245`）抛 UnboundLocalError。该函数在调度循环内同步执行（`chat_worker.py:286-297`），外层只捕获数据库异常，Worker 进程退出；`recover` 把 RUNNING 应用重新排队（`case_analysis/execution.py:36-40`），重启后再次崩溃。若非首轮出错，`index` 为上一轮的值：已成功项被改写为 FAILED，且应用仍为 RUNNING，调度线程死循环。

**设计**：
1. `execute` 每轮循环开始设 `index = None`。except 中：`index is None`、非 AppError、或 401/403 时整单 `FAILED`（`error_code` 为原码）；否则仅该条目 FAILED（原逻辑）。
2. `chat_worker._schedule` 中同步执行 `claim_application → execute` 处增加保护：非数据库异常记录 `analysis_application_failed type=<类型名>` 后继续调度；数据库异常仍走原分支。
3. 不改 `recover` 的重新排队规则，不改 case_generation 的对应逻辑。

**涉及文件**：`backend/app/modules/case_analysis/apply.py`、`backend/app/chat_worker.py`，测试 `backend/tests/test_case_analysis.py`。

**测试**：
- 操作者失去项目权限后执行排队应用 → 应用 FAILED、错误码为访问检查原码、函数正常返回。
- 第 1 条成功后失去权限 → 第 1 条保持 SUCCESS，应用 FAILED，循环在有限次内结束（用调用计数断言）。
- 调度单步：应用执行抛 RuntimeError → 调度继续（把单步逻辑提成函数后测试）。

**文档**：`CASE_ANALYSIS.md` 应用失败规则一句话。

---

### A2 修复 API 方式用例生成对话

**证据**：`case_generation/execution.py:451-460` 经 `ai_client.converse` 传 `diagnostics=`；API 分支调用 `responses.converse`（`responses.py:153`），该函数没有此参数，TypeError。非原生轮次都会走到这里（`native_results.py:403-409`）。测试用 MagicMock 替换了 converse（`test_case_generation.py:2019`、`:2113`），未暴露。

**设计**：
1. `responses.converse` 增加关键字参数 `diagnostics: dict | None = None`，透传 `_model_response`，与 `analyze` 一致。
2. 新增 `tests/test_ai_client_contract.py`：用 `inspect.signature` 断言业务层传给 `ai_client.analyze/converse` 的每个关键字（`diagnostics`、`on_progress`、`instruction_messages`、`terminal_spec` 等）在 API 与 CLI 两个分支的目标函数都被接受，或在 `ai_client` 中被显式丢弃。后续 O2、N1 新增参数时同步此测试。
3. `test_case_generation.py` 增加一个不替换 `responses.converse` 的用例，只模拟 HTTP 层，走 API 方式完成一次生成对话并检查诊断落库。

**涉及文件**：`backend/app/integrations/responses.py`，测试如上。

**文档**：`CASE_GENERATION.md` 对话一节一句话。

---

### A3 测试基线转绿

**设计**：
1. 在真实 PostgreSQL 上运行后端全量测试、前端 `npm test` 和全部原型检查脚本，记录失败清单。
2. 已知 3 项（`test_github_projects.py:226-228`、`:521-523`，`test_project_deletion.py:157-163`）按决策 6 改为：重复提交返回 201 且标识不同；已删除项目的同名项目可再创建。`GITHUB_PROJECTS.md:78` 改为“唯一标识由平台自动生成”。`ProjectInput.identifier`（`projects/schemas.py:36`）保留为兼容字段，文档注明被忽略。
3. 第 4 项失败、`docs/prototypes/check-change-analysis.cjs` 的 7!=5 计数断言：逐项定位。过期断言直接修；属于真实缺陷的单独列出，停下汇报，不顺手改行为。
4. 交付全量通过结果；若有经用户确认暂缓的失败，写入 SESSION_CONTEXT。

---

### A4 移除旧验收点接口

**范围**：`requirements/router.py:198-252` 中的 `GET ""`、`GET /classification-history`、`POST /categories`、`PATCH /categories/{id}`、`POST /move`、`POST /categories/{id}/delete`、`POST /assign`、`POST /undo/{event_id}`、`GET /rules/{id}`、`POST /rules`、`PATCH /rules/{id}`。紧随其后的 `/risk-reports/{report_id}/deletion` 等风险报告接口**保留**。

**设计**：删除上述路由；删除只被它们调用的 `requirements/service.py`、`requirements/schemas.py` 中的函数和模型类（逐个 grep 确认）；保留 ORM 模型、表、迁移，以及 `documents/service.py:592-614` 的引用计数。

**测试**：删除对应测试；新增断言这些路径不再存在；对比改前改后 OpenAPI 路由清单，只少这 11 个。

**文档**：`REQUIREMENTS.md` 页首状态补“旧接口已于本次移除，表保留”。提交说明写明：若有外部脚本调用这些接口将失效。

---

### O1 用量、输入规模与诊断落库

**设计**：
1. 用量：按原方案 T1。`responses.py` 新增纯函数 `usage_metrics(usage)`，读取 `input_tokens`、`input_tokens_details.cached_tokens`、`output_tokens`、`output_tokens_details.reasoning_tokens`、`total_tokens`，只保留 `0 <= v < 1e12` 的 int；`send_response`（`:497`）改用它；完成日志追加五个数，缺失写 `-`；`safe_snapshot` 按这五个固定键放行。CLI 不伪造用量。
2. 诊断落库统一：需求风险（`risk_analysis_execution.py:287`）和代码分析（`code_analysis/execution.py:166`）调用时传 `diagnostics`；成功和失败都经 `safe_snapshot` 写入任务 `metadata_snapshot["ai_diagnostics"]`。变更分析目前只在失败时写（`change_analysis/execution.py:89-91`），改为成功也写。用例生成、用例分析保持现状。
3. 输入规模：新增 `integrations/input_estimate.py`，纯函数 `estimate(instructions, messages) -> {characters, bytes, approx_tokens, images}`（CJK 每字约 1 token，其余每 4 字节约 1 token，键名或文档注明为估算）。`responses._model_response` 与 CLI 的 analyze 在发送前写 `stats["input_estimate"]`；`safe_snapshot` 放行固定数值键。
4. 本包不改界面。数据用于评估 N 系列效果，以及将来是否需要发起前提示。

**涉及文件**：`integrations/responses.py`、`response_diagnostics.py`、新 `input_estimate.py`、`codex_exec.py`、`codex_terminal.py`、`requirements/risk_analysis_execution.py`、`code_analysis/execution.py`、`change_analysis/execution.py`；测试 `test_responses_stream.py`、`test_response_errors.py`、各模块执行测试。

**测试**：完成事件带 usage 时输出五个数；缺失、负数、字符串、嵌套非法被忽略；估算函数边界（纯中文、纯英文、图片、空）；三模块成功执行后诊断含 usage 和 input_estimate；旧任务无诊断时读取不报错。

**文档**：`AI_SERVICE.md` 现行规则一节。

---

### O2 按模块配置输出上限

**设计**：按原方案 T2。`Settings.ai_analysis_max_output_tokens: dict[str, int] = {}`，键限五类模块名，值 1024–200000，非法时启动失败；默认常量 32000 保持现状。`responses.analyze` 新增 `output_profile`；`ai_client` 在 CLI 分支丢弃该参数；六处 `analyze` 调用传各自模块名。`.env.example` 加注释示例，并注明须确认模型支持该上限。

**测试**：未配置时 32000；只影响所配模块；非法值启动失败；CLI 分支收不到 `output_profile`（并入 A2 的签名测试）。

**文档**：`AI_SERVICE.md`。

---

### C1 变更旧分批收缩为只读适配器

**设计**：
1. 合入前在真实库执行只读 SQL：`execution_mode` 以 `BATCHED` 开头且状态为 `PREPARED/QUEUED/RUNNING` 的任务数必须为 0；否则停下汇报。
2. 以入口为根求可达集：列表与详情投影（`service.py:120-198`、`:241-276`）、导出（`export.py`）、免费重新校验（`service.py:433-449` → `batch_execution.revalidate`）。不可达部分删除，预计包括：`batch_planning.py` 的图规划（`:50-295`、`:352-535`）、`batching.plan/legacy_plan`（`:155-292`）、`batch_execution.run`（`:163-338`）、`execution.py:211-260` 的分批执行分支、`service.start` 与 `/start` 路由、`can_start`。
3. 保留的读取和重新校验代码合并为 `change_analysis/legacy_batches.py`，模块注释写明“只读兼容，不产生模型调用”。
4. `comparison.py` 保留：N2 的“无变化不调用模型”复用 `has_changes` 和 `unchanged_report`。
5. 前端移除只服务 `/start` 的调用和错误文案（如有）；“历史分批进度”展示保留。

**测试**：删除被删函数的测试；重新校验、展示、导出测试保留并通过。

**文档**：`CHANGE_ANALYSIS_BATCHES.md` 前部改为现行说明（只读查看、导出、免费重新校验），历史段落保留；`ARCHITECTURE.md` 变更分析一段同步。

---

### C2 用例生成 v2 冻结

**设计**：
1. 拆分：`legacy_contract.py:1-336` 的公共校验（`require/read/digest/shape/index/refs/validate_input`）移到 `case_generation/contract_base.py`，`compact.py` 等改为导入新名；`legacy_contract.py` 只保留 v2 的 `normalize_ai_report`、`validate_report`，模块注释写明冻结。
2. `service.retry`：批次固定输入 `contract_version == 2` 时返回 `409 generation_legacy_contract_retry_unsupported`，不发起调用。
3. `imports.py`：v2 包返回 `422 generation_legacy_contract_import_unsupported`。
4. v2 旧记录的查看、审核、入库不变。
5. 前端错误表加两条中文文案（“旧版契约批次不支持重试，请新建生成”等）；原型业务说明中的重试与导入规则同步一句话。不改布局。

**测试**：v2 重试与导入被拒且无调用；v2 旧批次展示、审核、入库仍可用；v3 不受影响。

**文档**：`CASE_GENERATION.md`。

---

### C3 删除死代码与实验残留

逐项 grep 确认后删除代码及只服务它的测试：

- 后端：`codex_exec.text_input`（`:173-188`）；`response_input.py:105-107` 的 `prompt_cache_breakpoint`（无产生方；T3 暂缓）；`response_diagnostics.py` 中 WebSocket 残留字段 `websocket_*`、`ping_interval_seconds`、`transport`、`generation_sent`（全仓无写入方）；`codex_terminal.directory` 永不触发的 getattr 回退（`:47-49`）；`code_analysis/sources.py:29` 的 `ROOT`；`analysis_terminal/execution.py:89-90` 恒传的 `instructions=""`、`fixed_input={}` 参数。
- 前端：`FormSelect.tsx:286 ActionMenu`、`generationApi.ts:370 generationList`、`skillApi.ts:242 skillFile`、`nativeTerminalApi.ts:97 readNative`，以及只被测试引用的 `parseGenerationPreview`、`generationPreview`、`parseChangePreview`、`changeMarkdown`、`RiskReports.tsx:2743 reportMarkdown`。每个删除前确认导出按钮等真实入口不依赖。
- 保留：`response_errors.read`（本地可信诊断工具，见 `AI_SERVICE.md`）；`verity_input` 迁移说明（服务撤下自定义 MCP 前的旧会话恢复）；`model_calls` 字段若前端有展示则保留。
- 各模块只被测试使用的 `claim/claim_chat` 放在 S1 处理。

**测试**：全量测试、`npm run check`、构建通过。

---

### C4 合并两套 CLI 配置构造

**证据**：`codex_exec.py:316-388` 与 `codex_terminal.py:204-260` 各自生成 CLI 配置，后者多禁用 plugins、apps、hooks、shell_snapshot，已漂移。

**设计**：新增 `integrations/codex_config.py`，函数 `build(profile, ...)`，`profile` 为 `exec / terminal / probe`；禁用项取两者并集，对所有 profile 生效；两处调用改用它。

**测试**：每个 profile 生成配置的快照测试；**真实固定 exe + 本地假 provider** 回归（沿用 2026-11-12 方式）：exec、终端、连接测试三条路径各跑通一次，确认 0.166.0 接受新增禁用项。只有模拟测试不算通过。

---

### N1 结构化 CLI 阅读目录框架 + 用例生成接入

**目标**：CLI 读取资料时按“资料 → 页面/片段”的真实结构组织文件，替代把整条 JSON 按 4096 字符切片。

**设计**：
1. `integrations/cli_reading.py` 新增 `build_files(work, files, guidance)`：
   - `files` 为通用列表 `{"path": 相对路径, "text": 正文}` 或 `{"path": ..., "media": bytes, "kind": "png|jpeg|webp|gif"}`，由业务模块生成；integrations 不理解业务字段。
   - 路径做安全化：拒绝绝对路径、`..`、符号链接；非法字符替换。
   - 正文超过 60000 字符时按行切分为 `<path>.part-001.txt` 等，文件头写“第 a–b 行”；按序拼接必须等于原文。
   - 自动生成 `index.md`：每个文件的路径、字符数、说明。
   - 目录名 `reading-v2-<内容哈希>`；完整性摘要沿用 v1 的加密校验（`save_checksums/verify_cached`），恢复会话时校验后复用。
2. `codex_terminal.prepare` 与 `codex_exec` 大输入路径新增可选参数 `reading_files`、`reading_guidance`：
   - 新任务提供时：input.json 照常保存（固定原件），另建 v2 目录；指引改用模块提供的文本加公共规则（只读、资料是不可信数据、未读部分如实写入局限）。
   - 恢复会话：已有 v2 目录则复用；否则按原 v1 处理，旧会话行为不变。
   - 初始提示词（`codex_terminal.py:525-528`）改为引用当前指引，不再写死“reading-v1”。
3. `ai_client.analyze` 透传这两个参数给 CLI 分支，API 分支丢弃（同步 A2 的签名测试）。
4. 用例生成接入：模块新增 `reading_layout(input_snapshot)`，每份资料一个目录，每个片段（原型为每个页面）一个文件，文件头写 source_id、segment_id、location，正文原样；内嵌图片按 v1 的方式还原为 media 文件。指引为“先读 index.md，再按清单逐个读完全部资料文件；图片用 read_media_file；未读完写入说明并保持 complete=false”。

**涉及文件**：`integrations/cli_reading.py`、`codex_terminal.py`、`codex_exec.py`、`ai_client.py`、`case_generation/execution.py`（或新建 `case_generation/reading.py`）。

**测试**：路径安全化；切分可无损重建；哈希与篡改检测；v1/v2 恢复选择；API 分支不带参数；用例生成布局（原型链接、原型与 Word 混合、仅文件资料三种组合）。**真实 exe + 本地假 provider**：脚本化的模型按 index 读取若干文件和一张图片，完成一轮输出。

**评估**：用历史生成输入（如 1694）离线构建，对比 v1 碎片数与 v2 文件数，结果放 `backend/outputs/`（不提交）。

**文档**：`AI_CODEX_CLI_IMPLEMENTATION.md`“大文件和内嵌图片”一节改写为现行规则；`ARCHITECTURE.md` 第 9 行。

---

### N2 变更分析 v3：差异优先输入 + 平台计算覆盖

**目标**：请求大小与变更量成正比；模型只输出判断，不输出覆盖台账；无变化不调用模型。

**输入（模型视图）**：根输入 `input_snapshot` 保持 v2 结构、照常完整保存，`sources.prepare` 不变。新增 `change_analysis/model_view.py`，纯函数 `build(root_input, mode) -> view`：

- `contract_version: 3`，新增 `view: {"kind": "DIFF_FIRST", "omitted_unit_count", "note"}`。
- CODE 快照：属于有变化映射的单元（有 text_diff 或存在状态变化）保留两侧完整片段；其余单元保留 `unit_id/path/presence/read_state/content_sha256`，`segments` 置空，增加 `content_provided: "OMITTED_UNCHANGED"`（比较对）或 `"OMITTED_CONTEXT"`（上下文快照）。
- 需求、原型、资料类快照保持全文（体量小，且影响判断依赖上下文）。
- `text_diffs` 增加 `hunks`：`difflib.unified_diff` 生成、3 行上下文、头部带真实行号与路径的统一差异文本；原 `note` 保留图片等说明。
- `unit_mappings` 只保留有变化的映射，增加 `unchanged_mapping_count`。
- API 方式在 `input_limitations` 追加：“未变化代码文件 N 个、上下文代码文件 M 个仅列清单，未发送正文；需要据此判断的部分按局限处理。完整核对可使用 CLI 方式。”
- CLI 方式：stdin 传同一模型视图；另经 N1 提供阅读布局：`index.md`、`diffs/<pair>/<n>.diff`、`before/<pair>/<path>`、`after/<pair>/<path>`、`context/<ref>/<path>`、`cases.json`、`history.json`。指引为“先读 index.md 与 diffs，再按影响追踪需要读取其余文件”。
- 所有比较对都无变化（`comparison.has_changes` 为假）：不调用模型，平台按 v3 结构生成报告并标明“无文本变化，未调用模型”。

**输出（report v3）**：在 v2 基础上：
- 删除 `coverage` 与 `outcome`。
- `limitations` 每项可带 `unit_refs: [{snapshot_ref, unit_id}]`，并增加 kind `NOT_ASSESSED`，用于模型声明未能评估的单元。
- TEXT 类证据（代码与资料）的 `segment_id`、`start_line`、`end_line` 可为 null；`unit_id` 与 `excerpt` 必填。

**平台计算（保存时）**：
- 证据定位：扩展 `change_analysis/evidence.py` 的确定性定位——缺段号或行号时，在**完整根输入**的同一单元内按摘录唯一匹配补全，并记录校正；找不到唯一匹配仍按现行规则拒绝（摘录宽松化不在本期）。引用被省略单元的证据合法，只要摘录在完整根输入中匹配。
- `platform_coverage`（写入报告新键）：每个比较对的变化/未变化/新增/删除单元数，不可读单元清单，API 方式未发送正文的单元数，模型声明 `NOT_ASSESSED` 的单元。
- `outcome`：全部目标 BLOCKED 且无变化和风险 → BLOCKED；全部目标 COMPLETE、无不可读的变化单元、无 `NOT_ASSESSED` → COMPLETE；其余 PARTIAL。

**校验**：把 `contract.validate_report` 拆成可复用的部分；v2 = 公共部分 + 覆盖 + outcome 检查（行为不变）；v3 = 公共部分 + 平台计算。离线双 JSON 导入同时接受 v2 与 v3。

**版本与兼容**：Skill `change-impact` 升到 2.0.0，`contract.md` 写 v3（删除 coverage 与 segment_reviews 要求，说明模型视图和 CLI 文件），`evaluation.md` 与 examples 同步；`skills/files.py` 的 `REGISTRY` 契约版本改为 3。新建任务用 v3；v2 任务的查看、重新校验、人工重试保持原 Skill 和 FULL_INPUT 路径不变。导出（`export.py:115`）对 v3 输出 `platform_coverage` 摘要。

**界面**：代码与变更页面不展示 coverage（已核对），`outcome` 字段保留，不需要原型变更。

**规范同步**：`CODE_STANDARDS.md:61` 改为：“新建变更分析使用差异优先输入：完整固定根输入照常保存；请求包含变化文件全文、带上下文的统一差异和未变化文件清单；CLI 另以只读文件提供两侧完整快照供按需读取；API 在局限中写明未发送正文的范围。不按静态关联筛选，不拆成多次独立调用。v2 任务及其重试按原方式。”同步 `ARCHITECTURE.md:97`、`CHANGE_ANALYSIS.md`，`CHANGE_ANALYSIS_FULL_INPUT.md` 页首标注被本规则替代。

**测试**：
- 模型视图：未变化 CODE 单元只留清单和哈希；变化单元两侧全文；hunks 含真实变化行和正确行号；非代码快照全文；上下文代码省略。
- 规模：合成 3000 文件、3 个变化文件的仓库，请求字节数只与变化文件相关。
- 无变化：不调用 `ai_client`，平台报告保存成功。
- v3 校验：无 coverage 通过；outcome 计算正确；缺段号证据被补全；引用省略单元且摘录匹配时通过；摘录不匹配时拒绝。
- 兼容：现有 v2 测试全部不改并通过；v2 任务重试仍走 FULL_INPUT。

**评估**：用历史 413、371 的固定输入（用户本机 storage）离线生成 v3 模型视图，记录字节数和 approx_tokens，放 `backend/outputs/`。

---

### N3 代码分析 v3：平台计算覆盖 + 阅读布局

**输出（report v3）**：在 v2 基础上删除 `coverage` 与 `outcome`；`limitations` 可带 `file_refs: [{source_id, file_id}]` 与 kind `NOT_ASSESSED`；CODE 证据 `segment_id`、`start_line`、`end_line` 可为 null，平台在同一文件全部片段内按“完整行唯一匹配”补全（扩展 `code_analysis/contract.py:388` 附近的现有校正）。

**平台计算**：`platform_coverage`：每个来源的文件总数、可读/部分/不可读数、不可读与部分文件清单、模型声明 `NOT_ASSESSED` 的文件。`outcome`：全部目标 COMPLETE 且无不可读/部分文件、无 `NOT_ASSESSED` → COMPLETE；全部目标 BLOCKED → BLOCKED；其余 PARTIAL。目标状态保持模型判断，不由平台改写。

**阅读布局（CLI）**：`sources/<来源名>/<文件路径>` 还原完整文件（可读片段按原行号拼接）、`materials/<资料名>/<片段>.md`、`index.md`；指引为“按清单逐个读完所选代码与资料文件”。

**版本与兼容**：Skill `code-review` 新版本，`contract.md` 写 v3，`examples`、`evaluation.md`、`scripts/check_examples.py` 同步；`REGISTRY` 改为 3；v2 任务不变。代码分析页面不展示 coverage，无需原型变更。

**测试**：无 coverage 通过；outcome 计算；缺行号证据补全；摘录不匹配拒绝；一致性目标的两端代码门槛不变；v2 测试不改并通过；阅读布局还原文件与原文一致。

**文档**：`CODE_ANALYSIS.md`。

---

### N4 需求风险、用例分析接入阅读布局

按 N1 框架为两个模块各写 `reading_layout`：每份资料一个目录、每个片段一个文件、图片还原为 media；用例分析另有 `cases/<模块或目录>/<用例编号>.md`。指引均为“先读 index.md，再按清单读完全部文件”。契约不变。

**测试**：布局生成与原文一致；旧会话仍用 v1。**文档**：两模块说明各一句。

---

### N5 需求风险 v4：覆盖由平台反推

**设计**：
- 契约 v4：删除模型输出的 `coverage` 与 `outcome`；`limitations` 增加 kind `NOT_PROCESSED`（带 `source_ids`），表示模型未处理的资料。
- 平台反推每份资料、每个片段的 `function_keys`（证据引用该片段的功能）和 `risk_keys`（证据引用该片段的风险），处理状态改为“被引用 / 未被引用（不代表未读）”；不可读资料的说明取 `read_note`。现有 `invalid_coverage`（片段功能与风险标签不相交）等提示随之消失。
- `outcome`：无可读资料 → BLOCKED；存在不可读、部分可读资料或 `NOT_PROCESSED` → PARTIAL；否则 COMPLETE。
- Skill `requirement-analysis` 新版本；`REGISTRY` 改为 4；v3 旧报告展示不变。

**界面（先改原型）**：风险报告“覆盖情况”区块（`RiskReports.tsx:1550-1576`）和导出（`:2770-2789`）的处理状态文案由“已审查/范围外/未处理”改为“被引用/未被引用”，v4 报告不显示逐片段理由。先改 `verity-prototype.html` 的该区块和业务说明，用户确认后再改正式页面；v3 报告沿用旧展示。

**测试**：反推结果与证据一致；outcome 计算；v3 报告解析和展示不变；前端解析与展示两种版本。

**文档**：`REQUIREMENT_RISK_REPORTS.md`。

---

### S1 后端任务流程样板合并

**设计**：新增 `modules/ai/task_lifecycle.py`，只放流程样板，不放业务规则：
- `mark_interrupted(db, models, code, requeue=())`：替代 8 处 `recover()` 的样板。
- `mark_failed(factory, model, key, exc, fallback, extra=None)`：内部先调用 `propagate_database_outage`，保证 CLI 结果重投机制不变。
- `throttled(fn, seconds)`：进度回调节流。
- `conversation_messages(context, question, prefix)`、`run_conversation(...)`：供代码、变更、需求对话执行使用；权限复核、指令文本、错误码作参数传入。
- `core/files.atomic_write(path, data, error_code)`：替代 4 处原子写。
- `json_object(text, error_code)` 从 `requirements/risk_service.py:35-65` 移到中立位置；代码分析、用例分析、变更候选审核改传本模块错误码（**新记录**的错误码改变，前端映射同步；已落库旧码保留映射）。
- 需求、代码、变更各自只保留一个校验函数，供执行、重新校验、候选审核共用。
- 删除各模块只被测试使用的 `claim/claim_chat`（如 `case_generation/execution.py:117-149`、`code_analysis/execution.py:35-58`），测试改走 `ai/scheduling.claim`。

**保留在各模块**：`own`、`sources.recheck`、契约、正式报告保存、attempts/batch 逻辑、全部错误码字符串、case_generation 先锁父记录再锁子记录的顺序。

**行为差异逐项决定（不在合并中悄悄统一）**：对话上下文大小上限只有部分模块有；变更的原始候选下载限发起人，代码与需求不限；候选文件缺失时 503/404 不一；用例分析取消检测 5 秒、其他 1 秒，且最终提交不复核来源与配置。本包只合并样板、保持各自行为，并把这些差异列在 PR 说明中，由用户逐条决定是否统一。

**测试**：现有模块测试全部通过；新增 `task_lifecycle` 单测；架构测试。

---

### S2 用例生成原生终端并入 analysis_terminal

**设计**：`analysis_terminal` 增加 `kind="generation"`、“取最新批次绑定”和“轮次完成”钩子；用例生成的恢复改为按原生线程 ID 恢复（现为 `resume --last`，`codex_terminal.py:263`），并去掉每次恢复时对全部批次输入与报告的 deepcopy（`native_terminal.py:218-224`，input.json 已存在时不会再写）。旧 ChatTurn 原生行按兼容逻辑读取。前端 URL 同步。

**测试**：恢复、续聊、自动保存完成轮次、旧记录读取；真实 exe + 假 provider 恢复后发送第二轮。

---

### S3 调度轮询与应用执行调整

**设计**：`ai/scheduling.claim` 的 QUEUED 查询加 `ORDER BY id LIMIT` 适当上限（`scheduling.py:14-23` 现无 LIMIT）；空闲时轮询间隔由 1 秒退避到最长 5 秒，有新任务时恢复；不调用模型的应用任务不再受 AI 槽位占满的限制（`chat_worker.py:286`）。单 Worker、咨询锁、预约规则不变。

**测试**：调度单步测试；预约与并发预算测试不变并通过。

---

### F1 前端测试改为行为测试

**设计**：抽共享加载器 `frontend/tests/helpers/load.cjs`，替换 44 个文件中各自复制的转译加载代码；把约 80 条匹配源码或 CSS 文本的断言（如 `case-analysis.test.cjs:216`、`chat.test.cjs:137-164`、`case-generation.test.cjs:406-414`）改为 `renderToStaticMarkup` 输出断言；按 hook 调用顺序打桩的测试（如 `generation-loading.test.cjs:22-23`）改为驱动公开行为。原型尺寸类 CSS 断言和 `ui-controls.test.cjs` 的规范扫描保留。

**验收**：测试数量不减少；F2–F4 重构时不需要改测试断言内容。

---

### F2 前端校验工厂 `createGuards`

**设计**：新增 `src/api/guards.ts`，`createGuards(errorCode)` 返回 `obj、str、int(min)、bool、list(parse, max)、nullable、choice、hash64`；22 个 `*Api.ts` 替换各自的原语定义。错误码由调用方传入。整数下限等语义差异（risk ≥1、code ≥0、change >0）逐处保留原值，不顺手统一。

**测试**：现有解析测试全部通过；`guards` 单测。

---

### F3 `usePolling`

**设计**：以 `ProjectOverview.tsx:95-118` 为范本，抽 `usePolling({load, active, interval})`：封装 AbortController、在途标记、页面可见性、active 门控和获得焦点时刷新。先改四个对话页（`CodeAnalysisChat`、`ChangeAnalysisChat`、`GenerationChat`、`RequirementChat`），再改四个记录页。`CaseGeneration.tsx:153-157` 改为只轮询第 1 页并合并，内容未变时返回原对象（参照 `ChangeAnalysis.tsx:281-310`）。

**行为变化（需在说明中写明）**：空闲时不再定时刷新，他人新建的记录改为在页面重新可见或获得焦点时出现。

**测试**：有活动任务时轮询、无活动任务时停止、页面隐藏时停止、恢复可见时刷新。

---

### F4 合并代码、变更分析对话页

**设计**：`CodeAnalysisChat.tsx` 与 `ChangeAnalysisChat.tsx`（diff 39 行）合并为 `AnalysisChat`，接口地址、错误映射、文案和权限作为参数；DOM 与 class 不变。

**测试**：两个页面的现有测试通过；SSR 输出与改前一致。

---

### W1 模块文档重写为现行规则

**设计**：
- 每个现行模块文档（`DOCUMENT_REVIEW.md` 列出的 26 份）前部重写为一页“现行规则”，历史段落移到 `docs/archive/<名称>_HISTORY.md`，保留链接。
- 已知矛盾优先处理：`AI_CODEX_CLI_IMPLEMENTATION.md` 的“CLI启用门槛”“本轮验收与未完成项”等过时段落；`AI_SERVICE.md` 已删除的平台配置接口与旧接口表。
- 审阅副本按决策 9 标注冻结；`docs/README.md`、`ARCHITECTURE.md:118` 和要求同步副本的文档相应修改。
- `AI_OPTIMIZATION_PLAN.md` 保留为历史，页首指向本文。
- 本包只改文档，不改代码。

---

## 七、不在本方案范围

- 摘录校验宽松化（找不到唯一匹配时降为条目级“待核对”而不是整单拒绝）：N2、N3 只消除段号与行号错误；摘录本身有误仍拒绝。若之后要放宽，需要代码与变更页面增加条目级提示，届时先改原型。
- 调用预约、HMAC、加密结果文件与加密日志的简化（决策 7）。
- 迁移合并为基线、`ai_config` 中两个终端绑定键名统一（需迁移旧 JSON）、`metadata_snapshot` 的类型化读取模型：价值有限，暂缓。
- 分段协议、按模块推理强度、聚焦模式、结构化输出试点（决策 8）。
- T3/T4 缓存 key：O1 上线后看 `cached_tokens` 再定。

## 八、人工真实调用验收（须用户单独授权）

实施者不发起真实调用。以下验收建议在对应任务包合入并重启 API 与 Worker 后，由用户本人在页面发起，或用户逐次明确授权次数后执行；失败即停，不追加：

| 时机 | 验收内容 |
| --- | --- |
| N1 之后 | CLI 方式一次用例生成（中等规模、含原型页面与图片），看是否从 index 读取、complete 是否为 true、O1 记录的输入规模 |
| N2 之后 | 中等规模代码变更：CLI 一次、API 一次；看请求规模、是否完成、报告引用是否通过校验 |
| N3 之后 | 代码分析 CLI 一次 |
| N5 之后 | 需求风险 CLI 一次，并核对新的覆盖展示 |

结论写入对应模块文档与 SESSION_CONTEXT。
