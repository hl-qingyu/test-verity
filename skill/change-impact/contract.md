# 变更分析调用契约 v2

Skill `1.0.4`，2026-10-26。`analysis_type="CHANGE_IMPACT"`、`contract_version=2`。

用户随后授权“接入变更分析”，平台已接本契约、后台分析/独立对话、严格导入、人工处理与完整导出。版本2明确区别原页面v1合成展示格式，不自动转换v1预览或修改需求v3/代码v2；实现状态和验证边界见[CHANGE_ANALYSIS.md](../../docs/CHANGE_ANALYSIS.md)。结构与权限错误硬拒绝，不把静态证据校验当推理正确或运行通过。

AI候选先原子保存原文；仅同一固定代码片段中的唯一完整原文行允许确定性校正行号/末尾LF，另存校正记录，原候选和输入不改。严格人工双JSON导入不做这项校正。历史问题只带入显式所选问题/处理快照与警示，未带旧正文时不证明修复。当前完整输入模式即使调用方文本diff为空，也交模型核对，不由平台提前判为已完成分析或零风险。

## 公共规则

调用方保存input，模型只生成report。两文件各为一个JSON对象；不输出Markdown围栏。下面列出的对象字段均必填且不接受额外字段；可空字符串用`""`，可空数组用`[]`，可空标识用`null`（仅显式允许处）。输入来源授权、原件绑定和事实真实性由调用方验证，JSON不证明这些事实。

key/ref非空且最长200字符；标题最长500字符，普通说明最长10000字符；原始片段text不套说明长度限制。标识不得重复，引用数组无重复且只能指向本次对象。不输出凭据、AI配置密钥、人工处理或任务运行状态。

代码与文本统一LF；哈希由调用方对实际UTF-8内容计算SHA-256，不要求模型重新计算。2026-10-26用户要求系统减少自行判断、完整内容交给AI，并指出多次传输对应独立分析会丢失整体上下文。当前新建和人工重试恢复完整固定input及全部原附件的一次模型请求，取消平台静态关联筛选、目标剔除、预排复核及跨批报告拼接。所选文件、版本、正文、范围、比较映射、diff、目标、上下文、用例和历史均完整提供，关联和业务结论由模型基于整个输入分析。同次请求可用多个连续input_text及无损相同正文引用装配，但不是多次模型分析，也不能扩大总上下文容量。模型拒绝或返回不完整时明确失败，仅人工重试，不静默截断、缩范围、自动分批或重发。单文件大小、来源权限、路径/哈希/引用和输出契约校验保持，只有URL不能充当已读图片。

历史V1/V2分批记录、原Skill、候选、成果和人工处理保留作审计，不自动补写或重跑。人工点击完整输入重新分析会新建记录，以本人当前配置一次分析完整固定根输入；旧批报告和人工处理不冒充新的整体结论。当前不返回INTEGRATION或reconciliations包装，最终report.json及人工双JSON导入仍为本v2结构。

## 输入

顶层：`contract_version`、`analysis_type`、`request_id`、`project_id`、`revision`、`mode`、`targets`、`focus`、`comparison_pairs`、`snapshots`、`context_refs`、`cases`、`historical_items`、`input_limitations`。

- project_id/revision为正整数；request_id由调用方生成，结果原样回传。revision是固定输入修订号，不由模型递增。
- mode：REQUIREMENT_CHANGE / CODE_CHANGE / PROTOTYPE_CHANGE。至少一组已确认比较对、至少一个目标。
- input_limitations为说明字符串数组；focus不能扩大范围或权限。

### targets与页面映射

| mode | 允许目标 | 已有页面名称 |
| --- | --- | --- |
| REQUIREMENT_CHANGE | BUSINESS_IMPACT / IMPLEMENTATION_FOLLOWUP / CASE_REGRESSION | 业务变化与功能影响 / 代码实现跟进 / 用例维护与回归建议 |
| PROTOTYPE_CHANGE | BUSINESS_IMPACT / IMPLEMENTATION_FOLLOWUP / CASE_REGRESSION | 原型行为变化与功能影响 / 代码实现跟进 / 用例维护与回归建议 |
| CODE_CHANGE | BUG / REQUIREMENT_DEVIATION / FRONTEND_BACKEND_MISMATCH | 代码Bug / 需求符合性 / 前后端一致性 |

所有方式都会做基础变化识别和有依据的影响追踪。代码方式同时给有关变化的回归建议，不新增页面复选项。CASE_REGRESSION可无现有用例，仍提供场景建议，明确现有用例未核对。

### snapshots：新旧原文和补充上下文

读取GitHub代码时先取得旧基准全文，新目标相同blob经哈希校验复用正文，新增/修改blob再只读获取；根input保存所选范围完整双侧快照，分批子输入按固定计划选取完整文件。scope_note/read_note与unit_mappings.note明确标识旧基准、新目标、固定提交、路径和正文新增/修改/删除/未变，补充依据仅由context_refs标识。复用不是版本替换；证据必须引用对应侧自己的snapshot_ref/unit_id/segment_id。文件是否变化不直接证明风险归因，路径变化不自动认定重命名。

每项：`snapshot_ref`、`source_id`、`kind`、`repository_kind`、`name`、`provenance`、`scope_complete`、`scope_note`、`units`。

- snapshot_ref全输入唯一、不可变；source_id是调用方验证的项目来源标识。
- kind：REQUIREMENT / PROTOTYPE / CODE / CONTRACT / DECISION；repository_kind：BACKEND / WEB / FLUTTER / OTHER / NONE。CODE不能是NONE，其他kind必须NONE。角色由项目登记提供，PROTOTYPE不能满足一致性客户端门槛。
- scope_complete仅表示本次确认比较范围的清单完整，不表示全项目完整；与某单元正文是否完整是两个维度。false时scope_note非空。每个snapshot必须在某比较对或context_refs中使用。
- provenance：`source_kind`（UPLOAD/GITHUB/LOCAL/LINK/PROVIDED）、`version_ref`、`commit`、`captured_at`。version_ref为真实固定文件版本/本地快照/页面内容快照标识；GITHUB.commit必须40位十六进制SHA，其余为空；captured_at为调用方记录的带时区ISO时间。LINK.version_ref不是URL；PROVIDED明确为用户提供、未自动核实仓库的快照，不冒充正式来源。LOCAL只适用于CODE。
- CODE_CHANGE的主比较对统一GITHUB或统一LOCAL，允许同方式多个来源；离线导入可统一使用PROVIDED，保留“用户提供、未与真实仓库自动比对”边界，由调用方在来源绑定时核验登记角色，不用上传内容自报角色满足一致性门槛。同次主比较不混用这三种方式，上下文可来自其他已授权方式。比较对两侧source_id/repository_kind必须相同，不跨仓库配SHA。

units每项：`unit_id`、`path`、`presence`、`read_state`、`read_note`、`content_sha256`、`segments`。

- unit_id在本snapshot内唯一；path为文件/页面/章节相对位置，不含越界`..`、凭据或本机绝对目录。无已确认映射时不根据path自动跨版本匹配。
- presence：PRESENT / VERIFIED_ABSENT / OUT_OF_SCOPE / UNKNOWN。VERIFIED_ABSENT需要完整清单或调用方可复核的存在性记录，read_note说明核实方式；不能用于表示“某规则未在文中出现”。
- read_state：READABLE / PARTIAL / UNREADABLE / NOT_LOADED。PRESENT＋READABLE正文完整；PARTIAL至少一段且read_note解释遗漏。UNREADABLE/NOT_LOADED无segments/hash且说明原因。非PRESENT一律NOT_LOADED、空segments/hash且read_note非空。
- PRESENT＋READABLE/PARTIAL的content_sha256为实际提供片段按顺序用LF连接所得64位SHA-256；它证明提供内容身份，不证明完整原件。存在但零字节文件可以READABLE、空segments且哈希为空文本的真实SHA-256；不满足可读代码门槛。
- segments每项：`segment_id`、`location`、`start_line`、`text`、`image_ref`。segment_id本单元唯一。CODE必须正整数start_line、非空text、空image_ref；其他内容start_line可null，text/image_ref至少一项非空，location非空。代码片段不得重叠；READABLE完整文件从第1行连续覆盖，最后一行真实性由调用方验证。未提供视觉附件时不填写image_ref。

### comparison_pairs

每项：`pair_id`、`name`、`before_ref`、`after_ref`、`update_mode`、`scope`、`scope_confirmed`、`unit_mappings`、`text_diffs`。

- pair_id唯一；before_ref/after_ref引用两个不同固定snapshot。主方式分别要求两侧kind同为REQUIREMENT、CODE或PROTOTYPE。同来源同固定版本/同提交不建立比较对；不同资料来源的相同版本标签不表示同一版本。不同快照内容相同合法，但不自动付费分析。
- update_mode：FULL_REPLACEMENT / INCREMENTAL_SUPPLEMENT / CODE_SNAPSHOT。CODE只能CODE_SNAPSHOT；需求/原型可用前两种。scope为用户确认的非空范围说明数组，scope_confirmed必须true。
- unit_mappings每项：`mapping_id`、`before_unit_ids`、`after_unit_ids`、`relation`（MATCH/RENAME/SPLIT/MERGE/CANDIDATE）、`confirmed`、`note`。各侧数组非空，可指向VERIFIED_ABSENT单元；代码新增/删除通过两侧文件清单记录，不以空数组代替存在性证明。CANDIDATE必须confirmed=false；未确认映射不能支持确定迁移/删除。映射保留一对多、多对一。
- 资料以原始比较范围核对规则，不要求调用方预先提炼规则；映射按章节/页面/文件提供，规则匹配由模型给候选说明。
- text_diffs每项：`diff_id`、`mapping_ref`、`before_segment_refs`、`after_segment_refs`、`note`。segment_ref为`{unit_id, segment_id}`，仅引用本对相应侧；diff_id在本对唯一。确定性文本差异由调用方生成，模型不改写；若涉及图片或无可用确定差异，可为空并说明范围缺口。CODE文本已改变的可读映射需有diff；文本相同映射不造diff。新增/删除一侧引用可空，另一侧有实际正文；空文件的存在性变化可两侧空，由note和清单支持。

context_refs为非主比较快照的snapshot_ref数组，包含目标代码、固定资料和已确认决定。代码变更需要未变化客户端时可以通过context_refs提供目标侧代码，无需伪造同提交比较对。context只表示指定目标实现，不能证明旧实现；归因仍需要实际旧侧依据。

### cases与historical_items

cases每项：`case_ref`、`case_id`、`design_version`、`library_revision`、`display_number`、`title`、`design`。内部ID/版本/库修订为正整数，case_ref唯一；design为`{preconditions, data_requirements, steps, expected}`四个字符串。仅固定设计字段，编号不用作身份匹配，不提供测试通过状态。相同case_id只允许一个本次选定版本。

historical_items每项：`history_ref`、`module`（REQUIREMENT_ANALYSIS/CODE_REVIEW）、`report_id`、`item_key`、`title`、`statement`、`handling_revision`、`handling_snapshot`、`basis_refs`、`review_warnings`。report_id/handling_revision为正整数；handling_snapshot为调用方固定的处理摘要，review_warnings为字符串数组。basis_refs引用已提供snapshots，可为空（摘要不能代替证据）；history_ref唯一。未选择的旧问题不自动复核，不从其他聊天隐式带入。

### 门槛及失败

模式/枚举/标识/引用非法、比较对未确认、缺一侧实际主正文或可比存在性清单、链接缺旧正文，整次BLOCKED。至少一个主比较对须有双方可读内容或合法新增/删除清单及另一侧可读内容，不能用两份全未读范围开展变化分析。个别未读单元属于有效输入的部分覆盖。

选FRONTEND_BACKEND_MISMATCH时，AFTER或CONTEXT中BACKEND与WEB/FLUTTER各至少有一个CODE/PRESENT可读非空代码片段，否则整次BLOCKED；BEFORE代码不能替代目标代码。

有效输入下：IMPLEMENTATION_FOLLOWUP缺目标代码仅该目标BLOCKED；REQUIREMENT_DEVIATION缺可读REQUIREMENT/PROTOTYPE/DECISION仅该目标BLOCKED。CONTRACT只作接口辅助，不自动变业务需求。其他目标继续；本次资料歧义、依赖缺失和部分正文记PARTIAL/限制。

## 输出

顶层：`contract_version`、`analysis_type`、`request_id`、`project_id`、`revision`、`mode`、`outcome`、`summary`、`target_results`、`changes`、`function_impacts`、`code_impacts`、`case_impacts`、`risks`、`historical_reviews`、`regression_scope`、`evidence`、`chains`、`coverage`、`limitations`。

身份字段原样回传。outcome为COMPLETE / PARTIAL / BLOCKED：比较覆盖与所选目标均完成才COMPLETE；无法开展任何有效分析或输入非法为BLOCKED；其他为PARTIAL。完成只表示固定范围分析完成。summary为`{conclusion, priority_risk_refs, inheritance_note}`，不让模型生成重复统计数、分数或通过率；调用方按唯一对象计算。inheritance_note概述增量继承，完整替换可空。

所有结果key、evidence.key、chains.key、limitations.key全报告唯一，前缀建议C/F/K/U/R/H/G/E/N/L，不赋予项目稳定业务编号。未选目标不能出现在结果target_refs中。

### evidence

每项：`key`、`side`（BEFORE/AFTER/CONTEXT）、`pair_ref`、`snapshot_ref`、`unit_id`、`segment_id`、`kind`（TEXT/IMAGE/ABSENCE）、`start_line`、`end_line`、`excerpt`、`observation`。

- BEFORE/AFTER必须pair_ref指向比较对并匹配snapshot；CONTEXT.pair_ref为空且snapshot位于context_refs。
- TEXT引用实际片段且excerpt为非空连续原文子串；CODE行号为正整数并逐行精确匹配输入，非代码行号null。IMAGE引用实际提供图片，excerpt为空，observation非空，不编造文字坐标；行号null。
- ABSENCE仅引用VERIFIED_ABSENT单元，segment_id/excerpt为空、行号null、observation说明调用方存在性证据；不是“模型没找到某规则”。CODE证据不能作为IMAGE。

### changes

每项：`key`、`pair_ref`、`mapping_refs`、`diff_refs`、`title`、`function`、`kind`、`evidence_state`、`before`、`after`、`business_effect`、`evidence_refs`、`questions`、`limitation_refs`。

- kind：ADD / MODIFY / REMOVE / RENAME / SPLIT / MERGE / TEXT_ONLY / CONFLICT / UNCERTAIN；不接受UNCHANGED。
- evidence_state：STATIC_SUPPORTED / INSUFFICIENT。before/after为说明字符串，未取得内容就明确未知。evidence_refs非空。确定变化需BEFORE＋AFTER；新增/删除文件允许相应侧ABSENCE。增量新增规则的BEFORE可引用相关旧规则实际检查范围，不要求虚构规则不存在清单。
- REMOVE：完整替换需要双方对应范围完整且相关正文实际检查，或新侧VERIFIED_ABSENT；增量只允许新文明确取消旧规则并引用。范围移出不能REMOVE。PARTIAL原型HTML只能支持已提供HTML变化，不能支持全页面视觉删除。
- mapping_refs/diff_refs仅引用本对对象；没有确定diff可空，不能编造diff_id。未确认映射相关变化用INSUFFICIENT并列问题，不确定名称匹配不输出确定RENAME。
- 所有变化限本次比较对；重复根因事实合并相关证据，纯未变规则不输出。

### function_impacts / code_impacts

两组共用对象：`key`、`title`、`change_refs`、`subject`、`subject_refs`、`directness`（DIRECT/INDIRECT）、`certainty`（STATIC_SUPPORTED/POSSIBLE/UNKNOWN）、`description`、`evidence_refs`、`chain_refs`、`suggestion`、`limitation_refs`。

subject_refs为`{snapshot_ref, unit_id}`数组，引用实际单元；功能可由主资料单元定位。STATIC_SUPPORTED必须有目标证据与相关变化；间接确定影响还须传播关系链。未知外部依赖只进入limitations，不造不存在的subject_ref。同对象同原因不重复计数。

### case_impacts

每项：`key`、`case_ref`、`change_refs`、`action`（KEEP/UPDATE/RETIRE）、`certainty`、`reason`、`proposed_fields`、`evidence_refs`、`limitation_refs`。

case_ref必须指向已选case；certainty同影响枚举。proposed_fields为`{field, proposal, basis_refs}`数组；field仅title/preconditions/data_requirements/steps/expected，UPDATE非空，KEEP/RETIRE为空。RETIRE需要确定取消规则依据，否则仅给UNKNOWN待确认建议。不输出新用例内部ID、审核状态或测试结果；未有已选用例的新增场景在regression_scope使用ADD_SCENARIO。

### risks

每项：`key`、`title`、`target_refs`、`change_refs`、`severity`（HIGH/MEDIUM/LOW/UNASSESSED）、`severity_reason`、`evidence_state`、`trigger`、`actual`、`impact`、`root_cause`、`target_views`、`attribution`、`history_refs`、`evidence_refs`、`chain_refs`、`counterevidence_note`、`fix_suggestion`、`verification_suggestion`、`limitation_refs`。

- target_refs非空已选目标子集，change_refs非空；只有具体疑点才报风险。未变原有问题若与变化无关，仅在显式历史复核中描述，不扩成全库审计。
- target_views每已关联目标恰好一项：`{target, evidence_state, expected, basis, basis_refs, comparison_rows}`。comparison_rows每项`{label, left, right}`，left/right为`{statement, evidence_refs}`；需求/实现跟进左规则右实现，一致性左后端右某客户端，业务风险左旧/预期右新。同根因的多目标分别对照。BUG可空comparison_rows，其他视图至少一行。
- STATIC_SUPPORTED需求/跟进视图必须有明确规则及目标代码；一致性视图同时有目标侧双方代码与实际接口配对。资料冲突或待核对警示不支持确定偏差。任一视图INSUFFICIENT则风险汇总INSUFFICIENT，且非空limitation_refs；严重程度独立判断。
- attribution为`{kind, explanation, before_refs, after_refs, causal_change_refs, impact_expansion, limitation_refs}`。kind严格为introduced/pre_existing/unknown。introduced必须风险STATIC_SUPPORTED、可比BEFORE和AFTER证据非空、causal_change_refs非空且为本风险change_refs子集；不能只以新规则＋未变代码归introduced。pre_existing同样需双侧同根因证据；旧规则变化或旧路径不足降unknown。impact_expansion说明触达扩大，无扩大为空。unknown须说明缺口并有limitation_refs。
- attribution、视图、对照及chain中使用的本风险证据都应收纳到evidence_refs；历史处理摘要不作为当前实现证据。fix/verification只给建议，不写已修复或已执行。

### chains

每项：`key`、`nodes`、`edges`；node为`{node_id, label, evidence_refs}`，edge为`{from, to, relation, certainty, evidence_refs, note}`。relation：CALL / RETURN / FIELD_MAPPING / STATE_ASSIGNMENT / RULE_TO_IMPLEMENTATION / DEPENDENCY / UNKNOWN；certainty：STATIC_SUPPORTED / UNKNOWN。

节点有实际证据；边只连本链节点。确定边必须有关系证据和说明，不因两段代码存在就判调用。UNKNOWN边引用可空但note非空，相关影响不得据此标确定。新旧执行链可分列并保留侧别，不把跨版本节点串成实际执行链。

### historical_reviews

每个historical_items恰好一项：`key`、`history_ref`、`result`（STILL_PRESENT/STATIC_IMPROVED/UNVERIFIABLE/NOT_CHECKED）、`note`、`evidence_refs`、`risk_refs`、`limitation_refs`。

STILL_PRESENT需本次目标证据，STATIC_IMPROVED需旧问题基准与目标证据且防护路径已核查；后两类有原因/限制。未提供旧正文不得凭摘要证明修复。risk_refs可空；复核不关闭旧问题、不写已解决/测试通过。history_refs与风险引用互相一致。

### regression_scope

每项：`key`、`title`、`function`、`change_refs`、`risk_refs`、`case_refs`、`action`（KEEP/UPDATE/RETIRE/ADD_SCENARIO）、`priority`（HIGH/MEDIUM/LOW）、`reason`、`preconditions`、`data_requirements`、`steps`、`expected`、`expected_basis_refs`、`certainty`（STATIC_SUPPORTED/NEEDS_CLARIFICATION）、`questions`、`limitation_refs`。

change_refs非空，关联case/risk须实际存在。已有用例action与对应case_impacts一致；ADD_SCENARIO.case_refs为空，不声称全库不存在对应场景。STATIC_SUPPORTED.expected及依据非空；NEEDS_CLARIFICATION需questions与限制，expected可以为空，不能把建议当确定业务规则。RETIRE.expected可写“停用理由需人工审阅”，不表示还要执行过时场景。优先级单独说明，KEEP可以HIGH。步骤与场景级预期不用校验行数相等。

### target_results、coverage、limitations

target_results每个所选目标恰好一项：`{target, status, scope, checks, risk_refs, limitation_refs}`。status：COMPLETE/PARTIAL/BLOCKED。checks每项`{subject, assessment, evidence_refs, risk_refs, note}`，assessment：CONSISTENT/DEVIATION/SUSPECTED/UNRESOLVED/OUT_OF_SCOPE；静态无偏差也可留checks，不作为未变变化卡片。DEVIATION/SUSPECTED需证据及对应本目标风险，CONSISTENT需证据且风险引用为空。BLOCKED的checks/risk_refs为空、limitations非空。risk_refs恰为该目标风险集合及checks.risk_refs并集。

coverage每个比较对每侧snapshot的每个unit，以及每个context快照的每个unit，按`(pair_ref, side, snapshot_ref, unit_id)`恰好一项：`{snapshot_ref, unit_id, side, pair_ref, status, segment_reviews, note, limitation_refs}`。同一快照若用于多个比较对须分别核对该对覆盖。status：CHECKED/PARTIAL/UNAVAILABLE/OUT_OF_SCOPE；side/pair归属同evidence。segment_reviews每个已提供片段恰好一项`{segment_id, status, note}`，status：CHECKED/IRRELEVANT/UNPROCESSED。缺片段正文与模型未处理分别记录，不用“提供过”证明检查过。VERIFIED_ABSENT可CHECKED（检查存在性），OUT_OF_SCOPE不能当不存在。范围不完整、PARTIAL/未读/未处理或相关UNKNOWN链必须有对应限制，并影响有关目标和总体完成程度。

limitations每项：`{key, code, description, affects, needed}`；code：INVALID_INPUT / READ_GAP / SCOPE_GAP / MAPPING_UNCONFIRMED / MISSING_DEPENDENCY / AMBIGUOUS_RULE / UNPROCESSED / NO_CASE_SCOPE / HISTORY_NOT_CHECKED / ATTRIBUTION_GAP / VISUAL_NOT_PROVIDED / REVIEW_WARNING。affects为受影响的目标或对象key/输入ref字符串数组，needed说明需补什么或人工确认什么。

无效输入诊断仍返回同顶层结构，身份中缺失字段用request_id空字符串、project_id/revision为null、mode为null；可识别身份原样回传。所有结果/evidence/chains/coverage数组为空，所能识别的合法目标均BLOCKED，至少一个INVALID_INPUT限制。它不是可入库报告；调用方在模型调用前本应阻断此类输入。

## 平台校验与人工复核责任（后续设计）

1. 调用前：鉴权、项目/来源/版本、角色、存在性清单、固定正文与哈希、目标门槛、图片实际附件、输入大小；准备失败不补入稍后最新版本。所有调用仅当前操作者个人AI配置。
2. 结构硬校验：严格字段、类型、枚举、身份、唯一性、引用、双侧归属、源码摘录/行号/哈希、目标门槛、覆盖与状态一致性；失败保留原始候选，不保存伪成功。
3. 语义复核：实际影响链、配对正确性、删除/归因与严重程度不是JSON验证能够完全证明。需求语义偏差可按已有机制形成平台独立review_warnings并降待核对；原始report不可改写，若降级则另存校验/展示判断，不静默覆盖原introduced。硬错误不通过语义警示绕过；双文件人工导入继续严格。
4. 人工处理、回归采纳与用例修改独立保存，不在AI报告内。取消、撤权、配置版本变化的晚返回不能成功落库；失败由人重试并复用固定双侧输入，新增范围另建分析。候选重校验不追加AI费用，也不替换输入。
5. 不新增通用知识库/Agent、自动工具调用、代码执行、Git写操作或自动测试。执行沿用app.chat_worker与分层模块，数据库迁移和中文注释已同步；用例/旧问题仍只关联与建议，不自动写入。
