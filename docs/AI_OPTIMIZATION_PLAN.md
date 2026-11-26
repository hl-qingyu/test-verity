# AI 调用优化方案与 Codex 任务包

> **2026-11-25 后续：未实施部分已由 [REDESIGN_PLAN.md](REDESIGN_PLAN.md) 取代。** T1、T2 并入其 O1、O2，T6 简化后并入 O1；T3、T4 等 O1 有用量数据后再定；T5、T7、T8、T9、T10–T13 取消或暂缓（理由见该文第二节决策 8）。本文保留作历史记录，不再作为实施依据。

2026-11-25 整理。状态：**方案已确认，尚未实施，代码未改**。本文件按 AGENTS.md 要求说明设计差异，并拆成可以逐个交给 Codex 执行的任务包。现行行为仍以 [AI_SERVICE.md](AI_SERVICE.md)、[AI_CODEX_CLI_IMPLEMENTATION.md](AI_CODEX_CLI_IMPLEMENTATION.md) 和各模块文档为准；任务包完成后再同步相应文档。

---

## 一、背景与目标

| 问题 | 证据（代码位置） | 对应任务 |
| --- | --- | --- |
| 看不到 token 用量和缓存命中 | `send_response` 已把 input/output/total 写入 `stats["usage"]`（`integrations/responses.py:497`），但 `safe_snapshot`（`integrations/response_diagnostics.py:246`）没有放行 `usage`，不落库也不写日志；代码分析（`code_analysis/execution.py:166`）和变更整体分析（`change_analysis/execution.py:262`）调用时没传 `diagnostics` | T1 |
| 输出上限写死 | `analyze` 固定 `max_output_tokens=32000`（`responses.py:146`），推理 token 也算在内；用例生成历史输出约 7.2 万字符，已接近上限 | T2 |
| 缓存不可控 | 请求里没有 `prompt_cache_key`；OpenAI 对 1024 token 以上的相同前缀会自动缓存，但平台没记录命中数，无法判断 | T1、T3、T4 |
| 推理强度不分模块 | 个人配置只有一个 `reasoning_effort`；Worker 运行时从当前配置读强度，没有用快照里的值（如 `case_analysis/execution.py:87-89`） | T5 |
| 发起前不知道输入有多大 | 风险、代码、变更三类的输入在 Worker 里才组装；用例生成和用例分析在 prepare 阶段就已固定输入 | T6 |
| 所有分析中途失败都全部作废 | 五类分析都是一次调用、一次性输出完整 JSON；API 的 `read_stream` 只在 `response.completed` 时返回（`responses.py:259-266`），CLI 的 `TerminalResult` 只取第一轮最后一条消息（`terminal_result.py:50-68`）；用例生成的建议 key 按输出顺序编号（`compact.py:187`） | T7、T10 到 T13 |
| 变更分析请求过大 | FULL_INPUT 约 49.6MB，出现过 400 和 504；`batch_planning.py` 中已有依赖图和闭包逻辑可以复用 | T8、T13 |
| JSON 格式失败要整单重跑 | 没有 `text.format`，校验失败就整单 422；分段协议实施后只需重做失败的那一段 | T7、T9 |
| API 与 CLI 差异没有分开设计 | CLI 由原生 Codex 自管请求、重试和压缩，平台只能控制模型、推理强度和输入；API 的请求参数和中转站限制完全不同 | 第二节 |

**总体原则（所有任务包共用，Codex 必须遵守）：**

1. 不增加自动收费重试，不回退平台密钥，只使用本人配置。
2. 已有的任务快照、Skill 快照、原始响应和历史结果不改写；新契约使用新版本号，旧任务继续按原版本处理。
3. 保持分层：`integrations` 不得导入 `app.db` 或 `app.modules`；router 不写 SQL，也不调用 integrations；service 不导入 HTTP 层。以 `tests/test_architecture.py` 为准。
4. 新增或修改数据库字段时，使用 Alembic 迁移，并在模型 comment 和数据库 COMMENT 中写中文说明。最新迁移是 `20261120_46_analysis_terminal_resume.py`。
5. 涉及界面的改动，先改根目录的 `verity-prototype.html`，并按 `docs/CHANGE_ANALYSIS_PROTOTYPE.md` 同步审阅副本，经用户确认后再开发正式页面。
6. CLI 方式不受 API 层新增参数影响：`ai_client` 走 CLI 分支时，必须先丢弃这些参数。
7. Codex 不得发起真实模型调用、不得推送、不得部署，上游一律用模拟。

---

## 二、API 与 CLI 双通道总体设计

用户要求：**所有 AI 分析在 API 和 CLI 两种方式下都要好用，两种方式分开设计**。CLI 是主要使用方式；API 限制较多（中转站的请求大小和时长、单次输出上限、PDF 以外的大输入），作为次要路径。

### 2.1 两种方式的根本差别

| 方面 | API（Responses） | CLI（原生 Codex 会话） |
| --- | --- | --- |
| 一次分析的形态 | 一次 HTTP 请求，一次流式响应 | 一个原生会话，可以有多轮 |
| 资料怎么给 | 全部放进同一请求（去重引用、超长字段拆片） | 90 万字符以上写入任务目录，模型用只读文件工具按需读取 |
| 输出上限 | `max_output_tokens`，推理也计入 | 每轮各自计算，多轮就能绕开单次上限 |
| 中途失败 | 已输出内容全部作废（现状） | 已完成的轮次留在会话里，可以恢复会话继续 |
| 重试代价 | 重发全部资料 | 恢复会话，资料已在上下文中 |
| 平台可控参数 | 输出上限、缓存 key、结构化输出、推理强度 | 只有模型、推理强度、指令和输入；请求、重试、压缩、缓存都由 CLI 自管 |
| 用量可见 | 响应自带 usage | 目前不采集（T1-CLI 调研） |
| PDF | 支持 | 不支持，提示改用 API |

### 2.2 统一的分段协议（五类分析共用）

五类分析都改为同一种“规划 → 分段 → 汇总”输出协议，每一部分是一行独立 JSON：

```text
{"type":"plan", ...}      规划：按本模块的天然单元列出段落
{"type":"segment", ...}   段落：一段的局部结果（可以有多行）
{"type":"summary", ...}   汇总：只能在看完所有段落之后给出的整体结论
{"type":"end"}            结束（仅 API 一次性输出时使用）
```

- **两种方式读资料都是整体阅读**：分段的只是**输出**，不是**阅读**。API 在同一请求里看完全部资料再逐段输出；CLI 在同一会话里读完资料，再逐轮输出。这一点和过去变更分析“分批请求、各看一部分”的做法不同，用户担心的“分批分析会有问题”不适用于这里。
- **平台合并**：各段保存后，平台按规划顺序合并成该模块现有格式的完整报告，再用**现有的整体校验**（如 `contract.validate_report`）检查。合并后通过校验的才算正式报告；校验前各段以“分段草稿”展示，并明确标注“尚未完成整体校验”。
- **key 唯一**：段内所有 key（风险、发现、证据、调用链等）必须以 `段号-` 开头，保存时检查全局唯一，合并时不需要重新编号。
- **规划校验**：段号格式合法且不重复，引用的资料或单元真实存在；需要“恰好覆盖”的模块（例如用例分析的用例、代码和变更分析的 coverage 单元），平台检查规划是否不重不漏。
- **规划提示**：平台可以提供本模块的结构参考，例如原型页面目录、变更依赖簇，只作参考，不强制。

### 2.3 两种方式各自怎么跑

**CLI（主路径）：平台逐轮驱动，每轮一部分，每轮完成即保存**

1. 第 1 轮：读完资料，只输出 plan。
2. 第 2 到 N+1 轮：平台在同一会话里自动发“请输出段 X”，每轮输出一个 segment。
3. 最后一轮：平台发“请输出汇总”，输出 summary。
4. 平台合并并做整体校验。

- 某一轮失败（轮次失败或中断、格式不合格、进程退出）：立即停止，已保存部分保留，任务为 `PARTIAL`，**不自动重试**。
- 用户点击“继续”后，恢复原会话，从第一个未完成的部分接着做；会话无法恢复时开新会话，附上已保存的规划和完成情况。
- 每轮的提示词由平台按固定模板生成，只含段号、标题、范围和输出要求，不含资料正文。

**API（次要路径）：同一请求流式输出，边接收边按行保存**

1. 一次请求输出 plan、全部 segment、summary、end，平台每收到完整的一行就校验保存。
2. 断流时已保存的行保留，任务为 `PARTIAL`。
3. 用户补发时，重新发送完整资料、原 Skill 快照、已保存的规划和待补部分，只输出缺的段和汇总。
4. 不做“每段一次请求”：每次都要重发全部资料，代价太高。

**两种方式的其他差异**

| 方面 | API | CLI |
| --- | --- | --- |
| 输出上限 | 按模块配置（T2） | 每轮短输出，不需要 |
| 缓存 | `prompt_cache_key` 开关（T3、T4） | CLI 自管 |
| 结构化输出 | 分段协议是多行 NDJSON，`json_schema` 只能约束单个 JSON 对象，**分析类不适用**；T9 改为在 Skill 助手试点 | 不适用 |
| 推理强度 | 按模块（T5） | 按模块（T5），通过 `model_reasoning_effort` 传入 |
| 输入规模提示 | 超阈值时建议改用 CLI、缩小范围或使用聚焦模式（T6） | 只显示规模，说明大输入会改为文件读取 |
| 大输入 | 变更分析可选聚焦模式（T8）；其他模块提示改用 CLI | 同样可以用聚焦模式，但通常不需要 |
| 用量 | T1 | T1-CLI 调研 |
| PDF | 支持 | 提示改用 API |

**不分段的 AI 调用**：分析后的续聊、独立对话、Skill 助手输出都很短，不需要分段。API 沿用 `converse`（8192）；CLI 沿用原生会话续接。

### 2.4 五类分析的分段单元

| 分析 | 现有输出（契约） | plan 的单元 | segment 内容 | summary 内容 | 规划提示 |
| --- | --- | --- | --- | --- | --- |
| 用例生成 | `cases / notes / complete`（契约 3） | 业务功能点，AI 规划 | 该功能点的 cases、notes | 整体 complete、全局 notes | 原型页面目录 |
| 需求风险 | `outcome / summary / functions / risks / optional_suggestions / coverage / limitations`（v3） | 功能（与报告中的 `functions` 一一对应） | 该功能的 function 对象、risks、optional_suggestions | outcome、summary（含 priority_risk_keys）、coverage、limitations | 原型页面目录 |
| 用例分析 | `findings / notes / checked_case_ids / complete` | 用例分组，所有输入用例恰好分到一组 | 该组的 findings、notes、checked_case_ids | complete、全局 notes | 按用例模块或目录分组 |
| 代码分析 | `outcome / summary / target_results / findings / evidence / chains / coverage / limitations`（v2） | 文件组，所有 coverage 单元恰好分到一组 | 该组的 findings、evidence、chains、coverage | outcome、summary、target_results（checks 可以引用各段的 finding）、limitations | 代码依赖簇（复用 `batch_planning` 的依赖图） |
| 变更分析 | `changes / function_impacts / code_impacts / case_impacts / risks / historical_reviews / regression_scope / evidence / chains / coverage / target_results / limitations` | 变更簇，所有 coverage 单元恰好分到一组 | 该簇的 changes、各类 impacts、risks、historical_reviews、evidence、chains、coverage | outcome、summary、target_results、regression_scope、limitations | 变更依赖簇；可与聚焦模式（T8）叠加 |

---

## 三、任务总览与依赖

| 编号 | 名称 | 阶段 | 依赖 | 迁移 | 原型 | 规模 |
| --- | --- | --- | --- | --- | --- | --- |
| T1 | token 用量落库与日志 | 1 | — | 否 | 否 | 小 |
| T2 | 按模块配置输出上限 | 1 | — | 否 | 否 | 小 |
| T3 | `prompt_cache_key` 部署开关 | 1 | T1 | 否 | 否 | 小 |
| T4 | 真实调用验证缓存（人工执行，不交给 Codex） | 1 | T1、T3 | 否 | 否 | — |
| T5 | 按模块推理强度 | 2 | — | 是 | 是 | 中 |
| T6 | 发起前输入规模提示 | 2 | T1 | 否 | 是 | 中 |
| T7a | 公共分段协议与持久化（`segment_protocol`、`analysis_segment` 表） | 3 | — | 是 | 否 | 中 |
| T7b | CLI 逐轮驱动（主路径） | 3 | — | 否 | 否 | 中，需真实 exe 加假 provider 验收 |
| T7c | API 流式按行回调（次要路径） | 3 | — | 否 | 否 | 小 |
| T7d | 用例生成接入（契约 4、页面目录提示、补段） | 3 | T7a、T7b、T7c | 是 | 否 | 大 |
| T7e | 分段进度界面（公共组件 + 用例生成） | 3 | T7d | 否 | 是 | 中 |
| T8a | 聚焦模式规则与原型 | 3 | — | 否 | 是 | 小 |
| T8b | 聚焦模式后端 | 3 | T8a | 否 | 否 | 中 |
| T8c | 聚焦模式前端 | 3 | T8b | 否 | 是 | 小 |
| T9 | 结构化输出试点（Skill 助手，仅 API） | 4 | T1 | 否 | 否 | 小 |
| T10 | 需求风险接入分段协议 | 4 | T7d、T7e | 是 | 否（复用 T7e 组件） | 中 |
| T11 | 用例分析接入分段协议 | 4 | T7d、T7e | 是 | 否（复用 T7e 组件） | 中 |
| T12 | 代码分析接入分段协议 | 4 | T7d、T7e、T8b | 是 | 否（复用 T7e 组件） | 大 |
| T13 | 变更分析接入分段协议 | 4 | T7d、T7e、T8b | 是 | 否（复用 T7e 组件） | 大 |

建议顺序：T1 → T2 / T3 → T4（人工）→ T5 / T6 并行 → T7a / T7b / T7c / T8a 并行 → T7d → T7e、T8b → T8c → T10 / T11 → T12 → T13 → T9。

- 每接入一个模块，API 和 CLI 两条路径都要通过验收，不允许只做一条。
- 用户以 CLI 方式为主，T7b 的真实 exe 验收是整个分段方案的关键前提，应尽早完成；验收不通过时，先暂停 T10 到 T13。
- 人力有限时，可以先做 T1 → T7 → T8 → T5，再逐个接入 T10 到 T13。

---

## 四、如何交给 Codex

### 4.1 工作方式

- **一个任务包对应一个 Codex 会话和一个本地分支**，分支命名为 `ai-opt/T1-usage` 这种格式。不要把多个任务包放进同一个会话，否则 diff 太大，不好审核。
- Codex 会自动读取仓库根目录的 `AGENTS.md`。提示词只需写清楚任务包编号，并要求它先读本文件对应章节和其中列出的文件。
- 涉及原型的任务包（T5、T6、T7e、T8a）分两步走：先让 Codex 只改原型，由你确认；确认后再开新会话开发正式页面。
- 每个任务包完成后的流程：
  1. Codex 交付 diff、测试输出，以及更新后的模块文档。
  2. 你（或 Claude Code 的 `/code-review`）审核 diff，对照本文件的验收清单逐条检查。
  3. 本地合并到 main。按 AGENTS.md，用中文提交说明，写清改动和验证情况；不推送。
  4. 在 `docs/SESSION_CONTEXT.md` 追加一条交接：已完成、未验证、待决。

### 4.2 提示词模板（复制后替换 `<>` 部分）

```text
你在 test-verity 仓库工作，先读 AGENTS.md、docs/ARCHITECTURE.md、docs/CODE_STANDARDS.md。
本次只做 docs/AI_OPTIMIZATION_PLAN.md 中的任务包 <T1>，范围以该章节为准，不做其他任务包的内容。
要求：
1. 先读该章节“涉及文件”中列出的文件，确认与描述一致；如有不一致，先停下并列出差异，不要自行扩大范围。
2. 严格遵守该文件第一节的“总体原则”和第二节的“API 与 CLI 双通道总体设计”；分段相关任务的 API 和 CLI 两条路径都要实现并测试；不发起真实模型调用，不推送，不改写历史快照或数据。
3. 按“设计”实现，按“测试”补充或修改测试，并运行“验证命令”，贴出完整结果。
4. 同步“文档更新”中列出的文档。
5. 最后输出：改动文件清单、设计偏离说明（如有）、测试结果、未验证事项。不要提交。
```

### 4.3 验证命令（Windows，在 `backend/` 和 `frontend/` 下运行）

```powershell
# 后端
.\.venv\Scripts\python.exe -m ruff check app tests migrations
.\.venv\Scripts\python.exe -m ruff format --check app tests migrations
.\.venv\Scripts\python.exe -m unittest tests.test_architecture -v
.\.venv\Scripts\python.exe -m unittest <相关测试模块> -v
# 有迁移时追加
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic check
.\.venv\Scripts\python.exe -m unittest tests.test_database_comments -v
# 前端（有改动时）
npm run check; npm test; npm run build
```

### 4.4 审核要点（每个任务包都检查）

- 没有新增对上游的自动重试，失败路径没有变化。
- `safe_snapshot` 没有放行任意上游文本。
- CLI 分支没有收到 API 层的新参数。
- 旧任务（快照里缺新字段）的行为保持不变，并有对应测试。
- 如有迁移：中文 COMMENT 齐全，提供 downgrade，`alembic check` 无差异。

---

## 五、任务包详细设计

### T1 token 用量落库与日志

**目标**：每次 API 方式调用后，诊断里保存输入、缓存命中、输出、推理、总计五个 token 数，并写入完成日志。

**涉及文件**：`backend/app/integrations/responses.py`、`backend/app/integrations/response_diagnostics.py`、`backend/app/modules/code_analysis/execution.py`、`backend/app/modules/change_analysis/execution.py`，测试 `backend/tests/test_responses_stream.py`、`test_response_errors.py`。

**设计**：
- `responses.py` 新增纯函数 `usage_metrics(usage) -> dict`：
  - 读取 `input_tokens`、`output_tokens`、`total_tokens`，以及 `input_tokens_details.cached_tokens`、`output_tokens_details.reasoning_tokens`。
  - 只保留 `0 <= v < 1e12` 的 int，输出键名为 `input_tokens / cached_tokens / output_tokens / reasoning_tokens / total_tokens`。
- `send_response` 第 497 行改为 `stats["usage"] = usage_metrics(result.get("usage"))`；完成日志追加这五个数，缺失时输出 `-`。
- `safe_snapshot` 新增：当 `stats["usage"]` 是 dict 时，按上面五个固定键过滤成 int 后写入 `result["usage"]`。
- 代码分析和变更整体分析调用 `responses.analyze` 时传入 `diagnostics`。存储位置参照用例分析（`case_analysis/execution.py:153`）：写进任务 `metadata_snapshot` 现有的 `ai_diagnostics`，用 `safe_snapshot` 过滤；如果该模块还没有这个键，就新增 `metadata_snapshot["ai_diagnostics"]`。不新增列。
- CLI 方式不变：`safe_snapshot` 对 CODEX_EXEC 已经固定 `model_calls=None`，不伪造用量。

**测试**：
- 完成事件带 usage（含两个 details）时，`safe_snapshot` 输出五个数。
- usage 缺失、为负数、为字符串或嵌套非法时被忽略。
- 代码分析和变更分析执行后，诊断里有 usage（上游用模拟）。

**文档更新**：`docs/AI_SERVICE.md` 顶部追加一条简短记录。

**验收**：不新增表或列；日志不输出正文或密钥；旧任务的诊断读取不报错。

---

### T2 按模块配置输出上限

**目标**：分析类输出上限改为按模块在部署配置里设置，默认值仍为 32000，保持现有行为。

**涉及文件**：`backend/app/core/config.py`、`backend/.env.example`、`backend/app/integrations/responses.py`、`backend/app/integrations/ai_client.py`，以及六处 `responses.analyze` 调用：`requirements/risk_analysis_execution.py:287`、`case_generation/execution.py:275`、`case_analysis/execution.py:144`、`code_analysis/execution.py:166`、`change_analysis/execution.py:262`、`change_analysis/batch_execution.py:291`。

**设计**：
- `Settings` 新增 `ai_analysis_max_output_tokens: dict[str, int] = {}`。用 validator 限制每个值在 1024 到 200000 之间，键只能是 `requirement_analysis / case_generation / case_analysis / code_analysis / change_analysis`。
- `core/config.py` 新增常量 `DEFAULT_ANALYSIS_OUTPUT_TOKENS = 32000`。
- `responses.analyze` 新增关键字参数 `output_profile: str | None = None`，通过 `Settings().ai_analysis_max_output_tokens.get(output_profile, DEFAULT)` 取值。`converse` 不变。
- `ai_client.analyze` 在走 CODEX_EXEC 分支前执行 `kwargs.pop("output_profile", None)`。
- 六个调用点分别传入自己的模块名。
- `.env.example` 加注释示例：`# AI_ANALYSIS_MAX_OUTPUT_TOKENS={"case_generation":64000}`，并注明：须确认所用模型支持该上限，否则会返回 `ai_output_limit`。

**测试**：
- 未配置时请求体为 32000。
- 配置了某模块时只影响该模块。
- 配置非法值时启动失败。
- CLI 分支收不到 `output_profile`。

**文档更新**：`docs/AI_SERVICE.md`。

---

### T3 `prompt_cache_key` 部署开关

**目标**：可以选择在请求中加入 `prompt_cache_key`，提高相同 Skill 前缀的缓存命中率。默认关闭，因为中转站可能拒绝不认识的参数。

**涉及文件**：`core/config.py`、`.env.example`、`integrations/responses.py`、`integrations/response_diagnostics.py`、`integrations/response_input.py`（只做核对）。

**设计**：
- `Settings.ai_prompt_cache_key: bool = False`。
- `responses.py` 新增纯函数 `prompt_cache_key(instructions, messages) -> str`：对 instructions 以及所有 system/developer 消息（JSON 排序后）做 SHA-256，取 `"verity-" + 前32位hex`。不包含 user 资料和用户 ID。
- `_model_response` 在开关为真时写入 `payload["prompt_cache_key"]`，并设置 `stats["prompt_cache_key_sent"] = True/False`；`safe_snapshot` 放行这个 bool。
- 中转站因参数被拒时，`error_metadata` 已把它归为 `parameters` 类；在 `PARAMETERS` 白名单里加入 `prompt_cache_key`，便于诊断。不自动去掉参数后重发。
- 核对 `response_input.py:107` 的 `prompt_cache_breakpoint`：确认目前没有生产者写入它。如果没有，保留现状，不扩展。

**测试**：
- 开关关闭时请求体没有该字段。
- 开关打开时字段稳定：同一 Skill 和规则的 key 相同；资料改变时 key 不变；Skill 改变时 key 改变。
- 400 错误中 parameter 为 `prompt_cache_key` 时能被识别。

**文档更新**：`docs/AI_SERVICE.md`，写明打开前要先用 T4 验证中转站兼容。

---

### T4 真实调用验证缓存（人工执行，不交给 Codex）

用户已授权一次，用本人配置，用完不追加。

单次调用只能证明中转站是否接受这个参数；能否命中缓存，要靠后续正常业务调用的用量数据判断，不另外发起收费调用。

1. **先上线 T1，观察一段时间**（不额外收费）：从正常业务调用的诊断中统计 `usage.cached_tokens`。如果同一 Skill 的连续任务已经有命中，说明自动缓存已经生效，T3 的收益有限。
2. **用唯一一次授权验证参数兼容**：T3 合并并重启 API 和 Worker 后，临时打开开关，在测试项目上用小份资料发起一次用例分析。
   - 正常完成：中转站接受该参数。
   - 400 且 parameter 为 `prompt_cache_key`：中转站不兼容，关闭开关，结束。
3. **兼容时**：开关保持打开，继续看后续正常业务调用的 `cached_tokens` 是否高于第 1 步的基线。
   - 明显提升：保留开关。
   - 始终为 0：中转站可能不透传缓存，联系服务方。
4. 结论写入 `docs/AI_SERVICE.md`。授权用完后不再追加调用。

---

### T5 按模块推理强度

**目标**：个人配置可以为五类分析分别设置推理强度，留空时沿用全局档位。任务快照固定实际使用的档位。

**现状差异**：Worker 目前在运行时从当前连接读取强度。本任务改为从快照读取；旧快照没有该字段时，继续从当前连接读取，保持旧行为。

**涉及文件**：`db/models.py`（`AIConnection` :117、`AICLIConnection` :161）、新迁移、`modules/ai/{schemas,service}.py`、五个模块的 enqueue/start 和 execution、`frontend/src/AIService.tsx`、`aiConfiguration.ts`、`verity-prototype.html`。

**设计**：
- **数据库**：两张表各新增 `module_efforts JSONB NOT NULL DEFAULT '{}'`，中文 COMMENT 写“按分析模块覆盖推理强度，键为模块名，值为推理档位，空对象表示全部沿用 reasoning_effort”。键和值的合法性在应用层校验，与 `ck_ai_reasoning_effort` 的取值一致。迁移命名 `2026xxxx_47_ai_module_efforts.py`。
- **Schema**：`ConnectionInput` 新增 `module_efforts: dict[ModuleKey, ReasoningEffort] = {}`，`extra="forbid"` 保持。`save_and_select` 把这个字段纳入“是否变更”的判断（第 227 行附近），变更时版本号递增。
- **快照**：`configuration_snapshot(config, module=None)` 增加 `effective_effort`，取 `module_efforts.get(module)`，没有就用 `reasoning_effort`。五个模块的 enqueue/start 传入自己的模块名。
- **Worker**：各模块 execution 取强度时，有 `snapshot.get("effective_effort")` 就用它，否则用现有的连接值。建议在 `modules/ai/service.py` 提供 `effort_for(snapshot, metadata)`，各模块统一调用，避免六处各写一遍。
- **前端**：在 AI 服务表单的推理强度下方，加一个可折叠的“按模块覆盖”区，五行 `Select`，第一项为“沿用全局”。必须先改原型并确认。
- 手动重试保留原快照的 `effective_effort`，与“保留原方式”的现有规则一致。

**测试**：
- 保存和读取覆盖值，版本冲突返回 409。
- 快照中的 `effective_effort` 正确。
- 旧快照没有该字段时走原逻辑。
- 重试保留原值。
- 前端：解析与提交，原型 UI 规范检查通过。

**文档更新**：`docs/AI_SERVICE.md`；五个模块文档中关于 AI 配置的一句话。

---

### T6 发起前输入规模提示

**目标**：用户发起分析前或刚发起时，能看到输入规模估算；超过阈值时提示改用 CLI 或缩小范围。只提示，不筛减资料，也不阻止发起。

**设计**：
- 新增 `integrations/input_estimate.py`，纯函数 `estimate(instructions, content) -> {bytes, characters, approx_tokens, images}`。`approx_tokens` 用保守公式：CJK 字符按 1 token/字，其他按 4 字节/token。界面写明“估算值”。
- 阈值放到 Settings：`ai_input_warn_tokens`，默认 200000。
- **用例生成和用例分析**：这两类的输入在 prepare 阶段已经固定，在 prepare 响应里附带 `input_estimate`，在现有确认弹窗中显示。
- **风险、代码、变更三类**：输入在 Worker 中组装，同步预估代价太高。第一期改为在 Worker 组装完输入、请求发出前，把估算写入诊断，并在任务详情显示“本次输入约 N token”。超阈值且为 API 方式时，任务详情显示建议。不新增阻塞确认。
- 估算值用 `safe_snapshot` 放行的固定数值键保存，不新增列。

**测试**：估算函数的边界（纯中文、纯英文、图片、空输入）；prepare 响应带估算；Worker 诊断带估算。

**原型**：两个确认弹窗增加一行“输入规模（估算）”，超阈值时显示一行提示文字。须先确认。

---

### T7 分段协议公共框架 + 用例生成首个接入

协议和两种方式的跑法见第二节。T7 先做公共框架，再以用例生成作为第一个接入模块；其余四类分析在 T10 到 T13 中接入。

#### T7a 公共分段协议与持久化

- **新增 `integrations/segment_protocol.py`**（纯函数，不依赖 db 或 modules）：
  - `parse_line(text) -> (kind, obj)`：去掉 `\r`，拒绝代码围栏、空行、非对象、重复键（复用 `json_object` 的严格解析规则）；`kind` 只能是 `plan / segment / summary / end`。
  - `check_plan_shape(obj, *, min_segments, max_segments)`：段号格式为 `^[a-z0-9][a-z0-9-]{0,47}$`，不重复，数量在范围内。
  - `check_key_prefix(obj, segment_id, key_paths)`：段内 key 必须以 `段号-` 开头。
- **新增公共模块 `modules/analysis_segments/`**（`service.py`、`schemas.py`，不需要 router）：
  - 新表 `analysis_segment`：
    - 列：`id`、`analysis_type`（CHECK 五类）、`task_id`（各模块任务或批次主键）、`request_id`（产生该部分的尝试）、`part`（`PLAN / SEGMENT / SUMMARY`）、`segment_id`（PLAN、SUMMARY 为空）、`turn_index`（CLI 轮次，API 为空）、`status`（`SAVED / REJECTED`）、`payload` JSONB、`issues` JSONB、`raw_sha256`、`created_at`。
    - 部分唯一约束：`(analysis_type, task_id, part, coalesce(segment_id,'')) WHERE status='SAVED'`，保证每个部分只保存一次。
    - 全部列写中文 COMMENT。
    - 不同模块任务表不同，所以 `task_id` 不建外键；删除由各模块现有的删除服务（`analysis_deletion` 等）一并清理，并补测试。
  - 服务函数：`save_part(...)`（短事务，冲突时记 REJECTED）、`saved_parts(analysis_type, task_id)`、`missing(plan, parts)`（返回待补段号以及是否缺 summary）。
  - 每个模块提供一个规则对象 `SegmentRules`，公共服务只调用它，不了解业务字段：
    - `validate_plan(plan, input_data)`：业务范围检查，例如覆盖是否不重不漏。
    - `validate_segment(segment, plan, input_data)`：复用模块现有的单项校验。
    - `validate_summary(summary, plan, segments, input_data)`。
    - `merge(plan, segments, summary) -> report`：合并成现有报告格式，再调用模块现有的整体校验。
    - `prompt(part, segment_id, plan) -> str`：CLI 每轮的固定提示词模板。
- **任务状态**：各模块任务表的 status CHECK 增加 `PARTIAL`，在各模块的接入任务里分别迁移。

#### T7b CLI 逐轮驱动（integrations，主路径）

- **新增 `integrations/terminal_segments.py`**：类 `SegmentDriver`，接口兼容 `TerminalResult`（`request` / `receive`）。
  - 跟踪同一线程的每一轮：`turn/started`、`item/completed`（agentMessage）、`turn/completed`。
  - 每轮正常完成后，取该轮最后一条 agentMessage，调用 `on_turn(index, text) -> next_prompt | None`。返回提示词则继续，返回 None 则全部完成，抛异常则立即停止。
  - 轮次失败或中断时停止，不提交下一轮。
  - 沿用 `bound_generation_thread` 规则，拒绝提交到其他线程。
  - 不导入 db 或 modules。
- **`codex_terminal.run`**：
  - 新增可选参数 `driver`。driver 给出下一轮提示词时，通过与人工输入相同的通道写入 TUI（现有 `process.write`），并处理多行粘贴和回车。
  - 全部完成后按现有 `capture.done` 的方式等待重绘，然后结束进程。
  - 不传 driver 时行为不变。
- **`codex_terminal.analyze`**：新增可选参数 `on_turn`，传入时创建 `SegmentDriver`，`initial_prompt` 改为规划轮的提示词。`ai_client` 原样透传给 CLI 原生终端分支；API 分支丢弃该参数。
- **续接**：复用现有原生线程恢复（`resume_thread`、`analysis_terminal_resume`），首个提示词指向第一个未完成部分，不重新规划。
- **旧 `codex exec` 路径**（未绑定原生终端的旧任务）：不逐轮驱动，输出完后按 NDJSON 逐行校验保存。新任务一律使用原生终端。
- **验收风险**：自动向 TUI 写入提示词，必须用“真实固定 exe + 本地假 provider”验证（沿用 2026-11-12 的方式），覆盖多行、中文、连续多轮、某轮失败即停止、恢复会话后继续。只有模拟测试不能算通过。

#### T7c API 流式按行回调（integrations，次要路径）

- `read_stream` 新增可选参数 `on_text_line: Callable[[str], None] | None`。
  - 累计 `response.output_text.delta`，每遇到 `\n` 回调一整行（去掉 `\r`，跳过空行）。
  - 回调抛异常时请求终止。
  - `response.completed` 后，缓冲区里没有换行的尾部内容**不回调**，交给最终文本处理。
- 在 `send_response`、`_model_response`、`analyze` 上逐层透传；`ai_client` 的 CLI 分支丢弃该参数。默认 None，现有行为不变。
- 模块层把每行交给 `segment_protocol.parse_line`，再按 part 分发给 `SegmentRules`，最后调用 `analysis_segments.save_part`。
- 测试（`test_responses_stream.py`）：多个 delta 拼成一行、一个 delta 含多行、断流时最后半行不回调、回调抛异常时请求终止。

#### T7d 用例生成接入

- **契约 4，Skill 2.2.0**：按第二节协议写入 plan、segment、summary 三种行。
  - plan 按业务功能点划分，不按文件或页数机械划分，跨资料的同一功能归入一段；限 3 到 20 段，输入很少时允许 1 段。
  - segment 内字段沿用契约 3。
  - summary 包含 `complete` 和全局 notes。
  - 写明两种输出节奏：CLI 每轮只输出指定的一行；API 一次输出全部行并以 end 结尾。
  - 写明 `outline_hint` 只是参考，不是证据。
  - 同步修订 `segmented-output-draft.md`，并更新 REGISTRY 契约版本（`skills/files.py:21`）。旧快照仍是 3，按原逻辑处理。
- **页面目录提示 `outline_hint`**：
  - 在 `case_generation/sources.prepare` 中生成，随 `input_snapshot` 固定。
  - 来源：原型链接（`LINK`，按 `binding["paths"]`）、GitHub 原型（`GITHUB`）、原型目录（`DIRECTORY`）。
  - 结构：`[{"source", "pages": [{"path": "端/分组/页面", "segments": [段落ID...]}]}]`。`path` 取自 segment `location` 前缀或所选路径，只做归类，不复制正文。没有原型类资料时不附带。
- **`SegmentRules` 实现**：
  - segment 用现有 `compact.normalize/validate` 校验（`source_indices` 沿用原逻辑）。
  - `merge` 合并成契约 3 的 `{cases, notes, complete}`，交给现有 `delivery.process` 和 `contract.validate_report`。
- **建议 key**：改为 `f"{batch_ref}.{segment_id}:C{index}"`。`suggestion_map`（`service.py:61`）同时读取 COMPLETED 和 PARTIAL 批次中已保存的段，`collision_keys` 沿用原逻辑。
- **补段**：`service.retry` 允许 PARTIAL，新增可选参数 `segment_ids`（默认全部未完成部分）。已保存的部分不可重发或覆盖。
- **迁移**：批次 status CHECK 增加 `PARTIAL`。
- **测试**（CLI 用模拟 driver 和事件序列，API 用模拟流）：
  - 规划不合格 → 失败且不入库。
  - 第 2 段失败 → 第 1 段保留，PARTIAL；恢复后从第 2 段继续，第 1 段和审核状态不变。
  - 指定段输出了其他段号 → REJECTED 并停止。
  - 两轮之间取消。
  - API：第三段断流 → PARTIAL；截断行不入库。
  - 契约 3 旧批次走原路径。
  - `outline_hint` 三种资料组合：只有原型链接、原型与 Word 混合、只有文件资料。

#### T7e 分段进度界面（公共组件 + 用例生成）

- 原型先行：
  - 公共的“分段进度”区块，五类报告页共用：显示“已保存 N / 共 M 段”、规划清单和每段状态（已保存、待补、不合格及原因），以及汇总状态。
  - CLI 运行中显示“正在输出：第 k 段 标题 / 汇总”。
  - “继续”按钮复用现有重试确认弹窗，写明“将按规划逐段请求，可能产生费用”。
  - 未通过整体校验的内容标注“分段草稿，尚未完成整体校验”。
  - 原生终端画面保持不变。
- 正式页面：新增公共组件（如 `frontend/src/AnalysisSegments.tsx`），先接入 `CaseGeneration.tsx`、`GenerationCliWorkspace.tsx`；兼容没有分段字段的旧任务。


---

### T8 变更分析聚焦模式

用户已确认：作为可选模式，**全量整体分析仍是默认**，由用户发起时明确选择；省略的范围必须对用户和模型都可见。

#### T8a 规则与原型

- 修改 `docs/CODE_STANDARDS.md:61`（“变更分析须一次完整输入，不筛减、不分批”），改为：默认 FULL_INPUT；用户显式选择 FOCUSED 时，平台按静态依赖圈定范围，并把省略的范围写入 `input_limitations` 和报告。同步 `docs/CHANGE_ANALYSIS_FULL_INPUT.md`，追加 2026-11-25 的用户确认。
- 原型：在 `verity-prototype.html` 的 `changeNewForm` 中，在“本人AI配置”上方加一个“分析范围”单选：“完整分析（默认）/ 聚焦变更及关联文件”，选聚焦时显示一行说明。审阅副本同步。须用户确认。

#### T8b 后端

- `schemas.AnalysisRequest` 新增 `execution_mode: Literal["FULL_INPUT", "FOCUSED"] = "FULL_INPUT"`。
- `service.enqueue` 写入 `metadata["execution_mode"]`。`service.retry`（`:370`，目前强制 FULL_INPUT）改为保留原任务的模式。
- 新增 `change_analysis/focus.py`：
  - 函数 `select(data) -> (subset_input, scope)`，复用 `batch_planning` 中的 `_nodes`、`_graph`、`_closure`，计算 `relevant = closure(changed, incoming) | closure(changed, outgoing)`，再加上非代码上下文（规则、用例、历史条目，参照 `plan()` :367-371）。
  - 把这三个函数改成公开名（去掉下划线前缀，旧名保留别名），供 focus 复用。
  - 用 `batch_planning.input_for` 生成子集，并在 `input_limitations` 中追加：“聚焦模式：已省略 N 个与变更无静态关联的文件”，附省略的 unit 路径清单（最多 200 条，超出写总数）。
  - 子集必须通过 `contract.validate_input`；不通过（例如前后端不匹配的目标缺少一侧）时，任务失败，错误码 `change_focus_scope_invalid`，提示改用完整分析。不自动回退到完整分析。
- **执行（`execution.py`）**：FOCUSED 时用子集替换 `input_data` 后调用模型。`validate_result` 用子集校验（覆盖率按子集计算，参照 `batching.validate_result`）。`metadata_snapshot["focus_scope"] = {included, omitted_count, omitted_paths}`。原完整 `input_snapshot` 照常保存，子集可以随时重新算出。
- `service.view` 输出 `execution_mode` 和 `focus_scope` 摘要。
- **测试**：复用 `test_change_batch_planning.fixture`。多层依赖被纳入；无关文件被省略并写进 limitations；子集校验失败时返回明确错误；重试保留模式；默认值是 FULL_INPUT，现有 `test_change_full_input` 不变。

#### T8c 前端

- `ChangeAnalysisNew.tsx` 按原型加单选，POST body 中加入 `execution_mode`。
- 报告页顶部，聚焦模式时显示“聚焦模式：省略 N 个文件”，可展开查看路径。

---

### T9 结构化输出试点（改为 Skill 助手，仅 API）

**为什么改范围**：五类分析改用多行 NDJSON 分段协议后，`text.format: json_schema` 只能约束单个 JSON 对象，不能约束多行输出，所以不再用于分析类。Skill 助手的输出是单个 `message + body` 对象，适合试点。

**设计**：
- `Settings.ai_structured_output_modules: list[str] = []`，可选值暂时只有 `skill_assistant`，默认不启用。
- schema 固化为 `skill/` 之外的平台文件（如 `backend/app/modules/skills/assistant_schema.json`），字段为 `message`、`body`，`additionalProperties: false`。加测试保证与 `skills/execution` 的校验一致。
- `responses.converse` 新增 `text_format: dict | None`，写入 `payload["text"] = {"format": {...}}`；`ai_client` 的 CLI 分支丢弃该参数。
- 中转站返回 400 parameters 时照常失败，提示关闭开关，不自动去掉参数重发。平台原有校验保留。
- 测试：启用时请求体带 format，关闭时不带，CLI 不带。

---

### T10 需求风险接入分段协议

- **契约 v4，Skill 3.1.0**：
  - plan：功能清单 `[{segment_id, name, sources}]`，与报告中的 `functions` 一一对应。
  - segment：该功能的 function 对象、risks、optional_suggestions；risk key 以段号开头。
  - summary：outcome、summary（`priority_risk_keys` 只能引用已保存的 risk）、coverage（每份资料恰好一项）、limitations。
  - 规划提示：沿用 T7d 的原型页面目录生成逻辑。把 `outline_hint` 的生成函数抽到 `requirements/analysis_materials.py` 附近的公共位置，两个模块共用。
- **`SegmentRules`**：`merge` 时 functions 按规划顺序排列，risks 按优先级排序，再交给现有的风险报告校验（`requirements/risk_analysis_execution.py` 中现有的校验函数）。
- **接入点**：`risk_analysis_execution.py:287` 的调用。CLI 传 `on_turn`，API 传 `on_text_line`。
- **迁移**：需求风险任务 status CHECK 增加 `PARTIAL`。
- **测试**：与 T7d 同一套场景；另加“summary 引用不存在的 risk → 拒绝”。

### T11 用例分析接入分段协议

- **契约**：
  - plan：用例分组 `[{segment_id, title, case_ids}]`，所有输入用例**恰好**分到一组（平台校验不重不漏），每组不超过一个上限（建议 50 条）。
  - segment：该组的 findings、notes、checked_case_ids（必须是该组的子集）。
  - summary：complete 和全局 notes。
- **`SegmentRules`**：合并后交给现有 `case_analysis/contract.validate`。现有规则全部保留：quote 必须是原文子串、MISMATCH 必须带证据等。
- **规划提示**：按用例现有的模块或目录字段分组的参考清单。
- **接入点**：`case_analysis/execution.py:144`。子任务沿用父任务的方式和规划规则。
- **测试**：用例遗漏或重复分组 → 规划拒绝；某组 checked_case_ids 越组 → 段落拒绝；其余同 T7d。

### T12 代码分析接入分段协议

- **契约 v3，code-review Skill 新版本**：
  - plan：文件组 `[{segment_id, title, units}]`，所有 coverage 单元恰好分到一组。
  - segment：该组的 findings、evidence、chains、coverage；key 以段号开头；跨组引用的证据由引用方所在段自行登记，不引用其他段的 evidence key。
  - summary：outcome、summary、target_results（checks 可以引用任意已保存段的 finding）、limitations。
- **规划提示**：用 `batch_planning` 的依赖图（`_nodes`、`_graph`、`_closure`，T8b 会改为公开函数）为代码单元生成依赖簇，作为参考。
- **`SegmentRules`**：合并后交给现有代码分析报告校验（`code_analysis/execution.validate_result`）。
- **接入点**：`code_analysis/execution.py:166`。
- **测试**：coverage 单元遗漏 → 规划拒绝；target_results 引用不存在的 finding → 汇总拒绝；其余同 T7d。

### T13 变更分析接入分段协议

- **契约新版本，change-impact Skill 新版本**：
  - plan：变更簇 `[{segment_id, title, units}]`，所有 coverage 单元（`(pair_ref, side, snapshot_ref, unit_id)`）恰好分到一组。
  - segment：该簇的 changes、function_impacts、code_impacts、case_impacts、risks、historical_reviews、evidence、chains、coverage。
  - summary：outcome、summary、target_results、regression_scope、limitations。
- **规划提示**：`batch_planning` 计算的变更依赖簇（`changed` 加上依赖闭包）。
- **`SegmentRules`**：
  - 合并逻辑优先复用 V2 分批的合并实现（见 `change_analysis` 下的 batch merge 代码和 `test_change_batch_merge.py`），合并后交给现有 `execution.validate_result`。
  - 与过去分批的区别：所有段都来自**同一次整体阅读**（CLI 同一会话，API 同一请求），不是分批各看一部分。
- **与聚焦模式（T8）叠加**：聚焦模式先缩小输入，分段协议再拆分输出，两者独立开关。
- **接入点**：`change_analysis/execution.py:262`。旧的 `BATCHED_V1/V2` 只做历史兼容，不改。
- **规范同步**：随 T8a 一起修改 `docs/CODE_STANDARDS.md:61`，写明“整体阅读、分段输出”不属于被禁止的拆批。
- **测试**：coverage 单元遗漏或重复 → 规划拒绝；regression_scope 引用不存在的 impact → 汇总拒绝；聚焦模式加分段组合；其余同 T7d。


---

## 六、暂不拆包的后续事项

- **T1-CLI 用量采集调研**：确认 0.166.0 的 app-server 或 exec JSONL 是否提供 token 用量及其口径；可信时再接入诊断，不能把进程数或轮次数当作调用量。
- **CLI 下 Skill 参考文件按需读取**：等 T1 有用量数据后，再评估 references 的固定成本。
- **API 续聊用 `previous_response_id`**：需要 `store=true`，涉及数据留存，须单独评估和确认。
- **多 Key 分摊和调大并发**：等中转站账号池问题解决后再做。
- **Skill 离线质量回归**：基于 `evaluation.md` 和 `examples` 做契约和规则检查，作为精简 Skill 时的基线。
- **中转服务方**：调大 `/responses` 的代理超时（至少 15 分钟）和请求体上限，增加上游账号。参考 [AI_RELAY_SUPPORT.md](AI_RELAY_SUPPORT.md)、[AI_RELAY_504_FIX.md](AI_RELAY_504_FIX.md)。

## 七、已确认事项（2026-11-25）

1. 实施 T7 用例生成分段输出（契约和交互变化须先改原型）。
2. 实施 T8 变更分析可选聚焦模式；完整分析仍为默认。
3. 允许 T4 一次真实调用来验证缓存，用本人配置，用完不追加。
4. T7 分段方式：AI 先按功能点规划（方案 B）；有原型类资料时，平台附上页面目录作为规划参考，不强制按目录分段。
5. 以 CLI 方式为主，API 作为次要路径；所有 AI 分析在两种方式下都要好用，两种方式分开设计（第二节）。

仍待确认：
- **五类分析统一改为“规划 → 分段 → 汇总”协议**（第二节 2.2、2.4）：每类分析的 Skill 和契约都要升级新版本，旧任务按原版本处理。
- **CLI 的自动逐轮请求**：平台按已保存的规划，在同一 CLI 会话中自动提交“规划 1 轮 + 每段 1 轮 + 汇总 1 轮”的后续请求；某轮失败即停止，不自动重试，由用户点击“继续”。这是新的平台自动调用行为，实施前须明确授权。
- **变更分析“整体阅读、分段输出”**（T13）：须同步修改 `docs/CODE_STANDARDS.md:61`，确认这种做法不属于被禁止的拆批。
- 各任务包的原型稿（T5、T6、T7e、T8a 开发前分别确认）。
