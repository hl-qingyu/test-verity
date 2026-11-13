# 分析模块输入输出设计

<!-- document-status:start -->
> **历史资料，不再作为当前开发或运行规则。** 跨模块初稿已由各模块实际契约和服务取代。 当前说明见[CODE_ANALYSIS.md](CODE_ANALYSIS.md)、[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)、[CASE_GENERATION.md](CASE_GENERATION.md)、[CASE_ANALYSIS.md](CASE_ANALYSIS.md)、[REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md)。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

2026-10-10正式接入：CHANGE_IMPACT契约2已用于变更后台分析、完整候选验证和双JSON导入；所有输入由授权来源准备并固定、结果/人工处理分离，见[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)。旧v1展示格式不自动转正式报告；需求v3、代码v2和用例生成边界保持。

2026-10-10：CHANGE_IMPACT已按用户设计请求形成[Skill设计稿](CHANGE_ANALYSIS_SKILL_DESIGN.md)与[独立候选契约2](../skill/change-impact/contract.md)，含三类比较、双侧存在性/原文、差异、归因、历史复核、用例建议及覆盖。不等同正式接入：现有页面仍为v1展示预览，需求v3/代码v2不变；下文此前“Skill未创建”是历史设计状态。

2026-10-09设计审阅后：CASE_GENERATION按[专项方案v0.2](CASE_GENERATION_DESIGN.md)落实已确认的统一确认即设计审核、导入/人工用例无生成基准维护、优先关联复用、人工澄清后补生成、500+计划内自动分批，以及逐条应用失败继续/人工确认重试。后续已按用户授权同步HTML合成演示与检查，见[原型说明](CASE_GENERATION_PROTOTYPE.md)；正式契约/AI/Skill未实施，其他模块既有授权和验证不因本文扩大。

2026-10-09：CASE_GENERATION的最新专项方案见[CASE_GENERATION_DESIGN.md](CASE_GENERATION_DESIGN.md)。细化INITIAL/UPDATE、上次已应用版本映射、旧新资料配对、当前人工字段保护、可应用候选门槛和配对导入绑定；用例编号及测试/审核/应用状态由系统负责。仅设计，独立正式契约与Skill尚未创建，不修改需求v3和代码v2。

2026-10-08：CHANGE_IMPACT的最新方案细化见[CHANGE_ANALYSIS_DESIGN.md](CHANGE_ANALYSIS_DESIGN.md)，补充两侧证据侧别、资料配对与有效更新范围、历史问题显式复核、源码严格校验/需求待核对边界及回归建议。仍是设计稿，正式契约和Skill未创建；需求v3和代码v2保持各自当前协议。

2026-09-17：其他四类分析的页面、对话、人工应用及实施方案见[OTHER_ANALYSIS_DESIGN.md](OTHER_ANALYSIS_DESIGN.md)。这是待审阅设计，四个正式模块仍未接入；需求分析当前能力以[需求分析开发方案](REQUIREMENT_ANALYSIS_DEVELOPMENT_PLAN.md)为准，旧v2/验收点和仅HTML状态不作为当前依据。

2026-09-16更新：当前产品方案见[LOCAL_ANALYSIS_SESSION_PLAN.md](LOCAL_ANALYSIS_SESSION_PLAN.md)，以持续分析会话＋报告快照为主。本文件保留五类分析的结构化报告与输入快照设计，不要求每轮对话JSON，不代表要建设自动模块流水线或AI共用知识库。


设计稿 v0.1 · 2026-09-15。依据本轮确认的五类分析职责设计；需求风险分析已实现契约3，其余契约为待实施方案。本次只设计，不调整现有运行接口、数据库或Skill。

## 1. 总体结构

所有模块采用两个文件：

- **input.json**：系统或本地执行程序在调用前保存的真实输入，包含范围、实际内容、依据及版本。不是要求AI重新生成输入。
- **report.json**：模型返回的完整结果JSON，由调用方保存为文件。导入接受结果文件实际名称，例如risk-report.json，以内容契约为准。

图片/PDF不重复放入附件目录，使用项目已有资料固定版本；本地来源如P1在导入时关联已有资料。关联只是原件定位，不是模型实际读取原件的证明。调用AI时必须实际提供对应正文/图片/PDF；只有链接、路径或文件名不算已读。

在线调用与本地导入都应进入同一结果校验、保存和展示链路。模型不负责数据库ID、报告导入时间、操作者、执行状态或人工处理记录。报告、功能、风险/问题、建议修改等是同一份结构化结果的不同视图，不必让模型额外生成互不一致的Markdown/Excel/HTML。系统从校验后的结果生成这些展示或导出文件。

## 2. 公共约定

### 调用标识及版本

| 字段/信息 | 归属 | 约定 |
| --- | --- | --- |
| contract_version | 两份JSON | 该模块契约版本；需求风险维持3，其他模块首期可各为1 |
| request_id | 输入生成，输出回传 | 唯一本次调用标识，两份文件一致；不当数据库写权限 |
| project_id | input | 平台项目ID；独立调用可null，导入时由登录用户选择授权项目 |
| revision | input | 调用方基准修订号；独立调用可null，不能代替每个资料/用例版本 |
| focus | input | 本次关注点；收窄范围要显式注明，不能默默声称项目级完整 |
| 分析类型 | 系统任务/导入入口 | REQUIREMENT_RISK、CASE_GENERATION、CASE_REVIEW、CODE_REVIEW、CHANGE_IMPACT；不要求对现有风险v3根对象新增字段 |
| 输入摘要 | 系统记录 | 对规范化输入计算SHA256，保存原始输入快照，不由模型自行计算或回造 |
| 执行状态 | 系统记录 | 等待、运行、失败、取消、已保存；与模型分析完整性分开 |

统一语义和处理方式，不强行把现有风险v3改成新包装。新模块采用各自schema；契约版本必须在“分析类型”范围内解释，不只凭数字3或1判断文件类型。

### 公共结果部分

各模块结果至少包含contract_version、request_id、outcome、summary、coverage、limitations，再增加本模块字段。

- outcome：COMPLETE完整处理本次约定范围；PARTIAL有未读取/未完成部分；BLOCKED无法进行有效分析。不是需求完备度、代码正确性或测试通过。
- summary：总体结论、优先处理事项；具体关联键由模块定义，不输出无依据质量分数。
- coverage：实际检查过的资料、功能、场景、用例或代码范围及其去向。没有发现问题也是一种处理结果；未读不能标为未发现问题。
- limitations：缺资料、缺依赖、未读附件、范围限制和无法判断的事项，说明对结论的影响。
- 问题、候选及修改建议均为待审阅产物。分析报告可在校验后自动保存，修改用例/停用用例/修改代码不因模型提出就自动执行。

### 共用依据对象

| 对象 | 必须包含的核心信息 |
| --- | --- |
| 资料快照 materials | source_id、名称、需求/原型来源类别、kind、snapshot_ref、read_state/read_note、实际segments正文与定位；沿用风险v3 |
| 功能范围 functions | 本次功能key、模块、名称、scope、来源evidence；可来自所选风险报告，也可由明确的需求范围建立 |
| 已确认业务结论 decisions | 可信来源标识、明确的业务结论、关联功能、依据/版本；由系统或人工准备，不从“已解决”状态自动推断 |
| 用例快照 cases | 内部case_id、当前设计version、展示编号、设计字段、已有需求依据；更新场景额外带last_generated版本内容 |
| 代码快照 code | 仓库/本地来源标识、固定提交或内容快照、已选文件清单、实际文件内容/片段、读取状态、位置及内容摘要 |
| 证据 evidence | 引用输入中已有的资料片段、用例字段或代码片段，保留source/segment、位置及摘录/观察；不能编造定位 |

风险报告中的F1/R1不是全项目ID。系统关联用“report_id + function_key/risk_key”，传给模型时可分配本次别名；多个报告不能仅因都有F1或名称相同就合并。用例定位必须用内部case_id及version，不能用允许重复的展示编号。

当前风险导入仍使用原evidence结构；其他模块需要引用代码和用例时，在其新契约中定义typed evidence，不给已有v3塞未定义字段。例如kind为MATERIAL/CODE/CASE，分别指向输入的资料片段、文件快照片段、用例版本字段。

## 3. 需求分析（REQUIREMENT_RISK）

### 输入

维持当前v3：contract_version、request_id、project_id、revision、focus、materials。

- 全部实际选择的需求正文和原型内容，固定当次版本。
- 来源由所属栏目识别，不让用户再选“资料用途”。
- 不要求已有用例或代码，也不以前一份风险清单代替完整需求。

### 输出

| 字段 | 系统用途 |
| --- | --- |
| summary | 需求风险总体结论、优先处理风险 |
| functions | 已识别功能及检查范围，无风险功能也保留 |
| risks | 问题、等级及理由、证据、检查范围、影响、待确认问题、完善建议/取舍、来源对比集中一条 |
| optional_suggestions | 非缺陷优化建议，不计风险 |
| coverage | 每份资料每个片段的处理记录 |
| limitations | 未读与无法判断的范围 |

入库后形成分析记录、功能清单、风险清单、完整报告及来源对照。人工处理状态、处理人和结论独立保存，不由模型生成。此模块不生成验收点或用例。

## 4. 用例生成（CASE_GENERATION）

### 输入

| 字段 | 内容 |
| --- | --- |
| mode | INITIAL首次生成或UPDATE用例维护；维护可按现状核对，有旧基准时再做变化对照 |
| scope | 全部需求范围或指定功能；完整生成指覆盖所声明的完整范围，不是把未提供内容也算进去 |
| materials | 本次需求/原型固定内容 |
| functions | 本次功能范围与依据，可在生成中补充有依据的功能 |
| decisions | 已确认的业务结论；未决问题不得伪装成已确认规则 |
| related_risks | 相关风险及明确处理结论，作为重点检查线索，不是唯一需求来源 |
| cases | 范围内当前已有用例，首次可空；用于避免重复、保留人工维护 |
| baseline | 可选旧需求/原型快照、可取得历史设计及成功应用/复用版本映射；无基准不拦截导入/人工用例维护，不补造历史 |
| case_library_revision | 平台当前用例库并发修订号，写入前复核 |
| focus | 本次重点，不要求额外扩展需求 |

UPDATE有基准时对照旧需求/实际历史设计、新需求、当前人工用例。没有旧基准时可按当前需求提出复用、修改、补充及有明确依据的停用；标明无法归因历史变化，不因新需求未提及某场景便判停用，不自动覆盖人工版本。

### 输出

| 字段 | 内容与用途 |
| --- | --- |
| functions | 本次完整功能范围；用于核对生成覆盖 |
| scenarios | 功能下有依据的场景：角色、条件、行为、预期及证据；是本任务快照，不恢复独立验收点库 |
| new_cases | 需要新增的完整用例草案 |
| reuse_suggestions | 同场景的已有case_id/version及关联依据，疑似重复需人工核对；复用确认后结束候选待处理且不重复新增 |
| updates | 对已有case_id/base_version提出字段级修改，含修改前后值、理由、需求变化及证据 |
| retire_suggestions | 因功能删除/不适用建议停用的用例及证据，不物理删除 |
| unchanged | UPDATE中已检查且无需变更的用例及原因；未检查不能列入 |
| conflicts | 新需求与人工改动冲突、疑似重复、无法唯一匹配等需人工判断事项 |
| requirement_questions | 需求缺失导致无法形成明确步骤/预期的问题，不造占位用例 |
| coverage | 每个功能/场景对应new_case key或已有case_id；未覆盖须有原因 |
| summary/limitations | 完整性与处理优先级 |

INITIAL优先复用已覆盖场景，缺失场景新增，有明确差异再建议修改；维护不要求用例曾由本平台生成。已确认业务结论保存版本、人员/时间和资料依据，用户发起后只补生成受影响场景，原报告及人工修改保留。

500+首次结果在同一记录内按预先展示的功能/输入计划自动分批调用本人AI，各批input/report与汇总快照保留；失败批次人工重试，成功部分不重放。人工统一确认应用完成设计审核；应用按条目独立事务，单条失败记录原因并继续下一条，成功映射保留，失败清单供人工确认后只重试对应条目。批次进度/审核/应用/测试状态由系统保存，不由模型回传。

### 用例草案字段

沿用当前用例管理的业务字段，不创造第二套用例格式：module功能模块、structure功能结构、case_type用例类型、priority优先级、description用例描述、title验证用例子项、preconditions前置条件、steps操作步骤、expected预期结果、remark备注，以及既有data_requirements测试数据要求、cleanup清理要求。

- 平台继续按现有14列展示/导出：序号、用例编号、功能模块、功能结构、用例类型、优先级、用例描述、验证用例子项、前置条件、操作步骤、预期结果、测试结果、测试人员、备注。
- 模型不分配正式序号/编号，不输出通过/失败或测试人员。人工确认且成功应用的新增/设计修改版本由系统设为已审核、未测、人员为空，记录确认人/时间；旧测试记录归原版本。仅生成或保存草稿不完成审核。
- updates只提交实际变更字段，不用空字符串覆盖未修改字段；保留已有编号，按当前版本生成新版。
- steps与expected是场景级文字，不要求逐行等长。缺关键业务预期时进入requirement_questions，不补造规则。

修改建议示意（不是完整report.json）：

```json
{
  "key": "U1",
  "case_id": 125,
  "base_version": 3,
  "function_keys": ["F1"],
  "scenario_keys": ["S2"],
  "changes": [
    {
      "field": "expected",
      "before": "输入订单号后显示匹配的订单。",
      "after": "仅显示订单号与输入内容完全一致的订单。",
      "reason": "本次需求明确为精确匹配。"
    }
  ],
  "evidence_refs": ["E1"]
}
```

示意中的before必须与input当前用例字段一致；正式写入还要重新检查数据库当前version及用例库revision，不以模型回传值作为事实。E1须指向同报告定义且能回查输入的新需求证据。

## 5. 用例分析（CASE_REVIEW）

2026-10-13专项功能草案见[CASE_ANALYSIS_DESIGN.md](CASE_ANALYSIS_DESIGN.md)。建议简化为findings/notes/checked_case_ids/complete，由平台补任务身份、版本、统计和审计，不强制规则树/逐段coverage；已检查与完成仅AI声明，不证明需求符合或语义覆盖。具体协议待后续Skill设计及审阅，本节下方字段保留为早期参考，不代表正式/coverage已接入或本轮创建了新契约。

### 输入

scope、materials、functions、decisions、related_risks、cases、focus。cases必须包含要审查的实际完整设计内容及版本，只有编号清单不够。若只选部分用例，注明不能做全库重复判断或项目级完整性结论。

### 输出

| 字段 | 内容与用途 |
| --- | --- |
| checks | 按功能/场景核对明确需求与现有用例，标明符合、部分满足、矛盾、缺失或无法判断 |
| case_issues | 已有用例问题：case_id/version、问题类型、字段位置、描述、需求/用例证据、影响和建议 |
| missing_scenarios | 需求明确但没有对应用例的场景、功能、依据和补充理由 |
| requirement_questions | 需求本身不明确的事项，与用例错误分开 |
| proposed_case_changes | 可提供具体修改草案，复用用例生成的updates/new_cases结构；不直接入正式用例 |
| coverage | 本次输入用例及选定需求范围分别检查到哪里，不能把未选用例当缺失 |
| summary/limitations | 总体审查结论、优先处理和范围边界 |

case_issues类型建议：REQUIREMENT_MISMATCH不符合需求、UNCLEAR_STEPS步骤不清、UNCLEAR_EXPECTED预期不可判断、INCOMPLETE_PRECONDITIONS前置缺失、TEST_DATA_GAP数据要求不清、DUPLICATE重复、CONTRADICTORY相互矛盾、OBSOLETE过时、UNSUPPORTED缺乏需求依据。

缺失场景没有现成case_id，单列missing_scenarios，不创建虚假的用例记录。没有问题的已审查用例在checks/coverage有记录，但不创建问题项。先不强制计算覆盖率；未来只有可复核的场景分母确定后才显示对应范围百分比。

新建/修改/停用建议共用用例变更审阅与应用逻辑：用户一次审阅整批，不强迫重新让AI生成一遍已完整的草案；需求仍缺关键规则时先澄清。

## 6. 代码分析（CODE_REVIEW）

### 输入

| 字段 | 内容 |
| --- | --- |
| scope | ALL或SELECTED；具体仓库、目录、文件及前端/后端范围 |
| materials/functions/decisions | 本次需求依据、功能及已确认业务规则；仅看代码也可检查Bug，但不能宣称已核对需求 |
| code | 每个仓库固定提交/本地内容快照、实际所选文件内容、路径/片段/行号、读取状态 |
| file_index | 已获授权的文件目录信息，用于识别依赖位置；目录存在不表示读过文件内容 |
| related_risks | 相关需求风险，作为检查重点 |
| runtime_evidence | 可选：调用方已经提供的日志、测试结果、接口样本及其环境/时间/版本；不由模型编造 |
| focus | 检查重点 |

ALL指已授权业务代码，仍按系统规则排除凭据、依赖产物、构建缓存等，不是无限读取整台电脑。SELECTED只读所选范围；发现关键依赖缺失时提出补选，不自行扩大读取或执行范围。本机目录接入与对外发送代码是不同授权，实际内容提供仍遵守当前项目的数据边界。

### 输出

| 字段 | 内容与用途 |
| --- | --- |
| functions | 识别或关联到的功能范围及依据 |
| findings | Bug、需求偏差、前后端不一致等发现 |
| call_chains | 页面操作→前端请求→后端接口→业务/数据处理→返回→前端展示的有依据链路；未知环节明确标注 |
| missing_dependencies | 未读取的关键文件/模块/接口及因此无法判断什么 |
| suggested_checks | 建议补充的运行验证、回归场景或接口核对；不是已执行结果 |
| coverage | 每个所选文件/片段与功能的检查记录，包括未完成原因 |
| summary/limitations | 总体结果、重点和证据限制 |

每条finding至少包含：key、type（BUG/REQUIREMENT_DEVIATION/FRONTEND_BACKEND_MISMATCH）、severity及理由、certainty（CONFIRMED/SUSPECTED/INSUFFICIENT_EVIDENCE）、function_refs、title、trigger、expected、actual、impact、evidence、call_chain_refs、fix_suggestion、verification_suggestion、verification_state。

- certainty=CONFIRMED表示证据足以确认问题，不是测试通过。
- verification_state区分STATIC_ONLY、RUNTIME_EVIDENCE和NOT_VERIFIED；没有输入提供的实际运行证据就不能声称复现。
- expected来自需求或明确的代码/协议约束；actual来自实际读取代码。需求不清不能仅凭AI偏好认定偏差。
- 前后端联合分析要求两端实际代码/协议依据；只提供一端时缺少部分留在missing_dependencies/limitations。
- 输出建议，不自动改代码、运行任意脚本或执行Git写操作。

## 7. 变更分析（CHANGE_IMPACT）

### 输入：需求变化 REQUIREMENT_CHANGE

mode、before_materials、after_materials、functions、before_decisions/after_decisions、当前code、当前cases、已有需求—代码—用例关联、focus。

必须有新旧需求内容快照。代码/用例若未提供，只输出能确认的需求变化与功能影响，将代码/用例影响标为证据不足，不能报告“没有影响”。

### 输入：代码变化 CODE_CHANGE

mode、before_code、after_code、diff、materials/functions/decisions、当前cases、已有关联、focus。

必须明确同一比较范围的基准与目标提交/快照。diff要带真实上下文或对应新旧文件片段，不能只给文件名。无旧内容时可检查新代码，但不能断言问题是本次引入。

### 输出

| 字段 | 内容与用途 |
| --- | --- |
| changes | 每项变化的类型ADD/MODIFY/REMOVE、新旧证据及实际业务含义，不只复述文本差异 |
| function_impacts | 受影响功能、关联变化、直接/间接影响、判断依据 |
| code_impacts | 需要检查或修改的前后端代码范围、调用关系及依据 |
| case_impacts | 对现有用例建议KEEP/UPDATE/RETIRE，或提出ADD_SCENARIO；明确case_id/base_version（新增场景除外） |
| risks | 本次变化风险，标明introduced、pre_existing或unknown的归因及新旧证据 |
| regression_scope | 建议优先回归的功能、场景、用例及原因；不输出测试通过 |
| missing_dependencies | 缺少的需求/文件/用例及其影响 |
| coverage/summary/limitations | 本次比较覆盖到哪里、主要影响及限制 |

每个impact包含change_keys、目标引用、effect、directness（DIRECT/INDIRECT）、certainty（CONFIRMED/POSSIBLE/UNKNOWN）、evidence、suggested_action。没有证据链的关联只列可能影响，不当确定修改清单。

变更分析负责确定影响与建议动作，不再独立完整生成另一批用例。将case_impacts作为用例生成UPDATE的补充输入；对完整草案也使用共用的用例变更校验/审阅/应用通道。

代码变更分析复用代码分析的finding与调用链结构，在变更范围加影响追踪和归因。当前实现有问题但旧版本也有，标pre_existing；没有基准证据时标unknown，不全部归因于本次修改。

## 8. 模块衔接与落库

| 上游 | 下游使用方式 |
| --- | --- |
| 需求分析 | 向用例生成/分析、代码分析提供功能定位与风险线索；完整需求仍来自原始资料 |
| 用例生成 | 经审阅应用new_cases/updates等，产生正式用例版本与需求依据映射 |
| 用例分析 | 保存审查报告；补充/修改建议进入同一用例变更处理，不自动覆盖 |
| 代码分析 | 保存发现、证据和建议验证，不直接修改代码 |
| 变更分析 | 保存变化与影响；将用例影响交给UPDATE，将代码问题复用代码分析结构 |

模型返回报告通过校验后整体保存并项目共享。修改业务实体需要单独应用：确认项目权限、目标存在、基准版本未变、修改字段白名单、证据合法及幂等性。目标过期时保留建议并要求重新核对，不覆盖新人工修改。

系统应保存：任务元数据、实际输入快照、所用Skill/契约内容及摘要、原始完整模型结果、校验后的报告、来源绑定，以及独立的人工处理/应用记录。原始完整结果若校验失败，只进入受控失败记录，不能作为正常报告展示；不记录到普通log文件。能否只重做校验/保存取决于确实已收到完整结果，不能拿半截流续成成功报告。

## 9. 校验与失败边界

1. 两份JSON匹配分析类型、契约版本和request_id；项目ID由系统核验，不信任外部文件授权。
2. 严格JSON，拒绝额外字段、重复字段、非法枚举/类型/长度；结果不能包含未授权的业务修改字段。
3. 所有引用来自本次输入；资料摘录/定位、代码行/片段、用例字段与版本能够对应。不能只验证ID存在而放过证据不支持结论。
4. 定位与摘录可以机械校验，但“代码是否确实有Bug”“语义上是否遗漏”仍需审阅或运行验证，不能以结构校验替代正确性证明。
5. COMPLETE与范围覆盖一致；PARTIAL保留已完成部分及原因；BLOCKED没有虚构业务产物。模型拒绝、断流或JSON不完整记失败，不自动付费重试。
6. 同一输入和结果重复导入不重复建立报告，同一修改批次重复应用不重复新建用例。报告保存幂等与业务修改幂等分别处理。
7. 导入资料原件可直接关联已有系统版本，不重复上传；仅凭文件名或最新版本不能绑定历史证据。
8. 不静默改写历史报告、需求依据、用例版本和测试记录；人工结论不由AI伪造。

## 10. 实施次序建议

1. 保持需求风险契约3和当前导入稳定，先定义用例生成INITIAL/UPDATE契约及完整合成样例。
2. 完成需求依据—用例版本映射与共用用例变更处理，保障首次完整生成和后续增量维护。
3. 接入用例分析，复用用例快照与修改建议结构。
4. 定义代码输入快照/范围和证据结构，接入代码分析。
5. 接入两种变更分析，复用上述版本、代码检查与用例更新能力。

本设计不代表这些模块已开发，也不扩大AI调用、代码外发、执行脚本或远端写入授权。具体接口和新表在实施各模块时按已确认流程落地，不提前建空模块。
