# 用例生成调用契约 v2

2026-10-12 · Skill 1.1.0。`analysis_type="CASE_GENERATION"`、`contract_version=2`。正式/generate已接本契约，区别旧v1原型展示格式；旧v1不自动转换为正式报告。不改变需求v3、代码v2或变更契约2。

2026-10-12后续用户授权“接入功能”，Skill现为1.0.0，本契约已接生产校验/本人AI/严格导入及人工应用。正式页面仅契约2；下方草案状态是历史。合成示例仍须同项目真实来源/用例绑定，不能修改示例ID冒充实际依据。实现与限制见[CASE_GENERATION.md](../../docs/CASE_GENERATION.md)。

调用方选择完整资料范围时，target_ends可用ALL_IN_MATERIALS，表示只在这些资料有依据的实际端设计场景，不凭空增加端。资料正文统一LF并保留完整分段及原件二进制绑定；来自用例库的C/G设计字段逐字保留，不能为换行标准化改变patch.before。新建任务完整范围一次生成，片段仅用于证据定位，所选资料和用例不截断；功能模块视图由候选模块和原功能ref生成稳定标识，仅用于显示/聊天隔离，不修改原报告引用。

输出类型约定：`rules[].branches[].conditions`和`scenarios[].conditions`均为字符串数组，单项也必须使用`["条件原文"]`，空值使用`[]`。AI通道允许平台将这两处字符串原样包装为单项数组，保留原始响应、字段路径及哈希审计后重新严格校验；不拆分、删改文字或修复引用/证据。外部配对导入仍按原契约严格校验。

## 多批完整导出包

平台配对包各含`analysis_type="CASE_GENERATION_BUNDLE", contract_version=2, project_id, request_id, batches`。input.batches项恰为`batch_ref,request_id,status,input`；report.batches项恰为`batch_ref,request_id,status,report`。双方批次集合/请求身份一致，每个有report的批次必须COMPLETED，逐批遵守下方契约；失败/未执行批report为空且状态不能COMPLETED，其固定输入仍保留。各批namespace唯一，同snapshot_ref的材料全文必须一致。包不自动合并原始report；平台对跨批语义/同目标重复另列待人工核对，完整性按所有计划批次及固定总范围核对。人工草稿、回复来源、审核/失败审计及实际映射在独立audit导出，不由模型写进report。

## 共同约定

调用方在调用前生成/保存input，模型只返回report。各文件为一个JSON对象，不含代码围栏、重复JSON键或额外尾随内容。以下列出的字段均必填，不接受额外字段；nullable仅在明确允许处使用，空字符串/数组为`""`/`[]`。模型不计算哈希、不补造input。

ref/key/semantic_key为非空字符串，最长200字符，不使用对象原型保留名；各类别内唯一，引用数组无重复。semantic_key描述对象/角色/端/条件/动作/分支，跨批不靠数组序号匹配；它是语义对齐线索，不证明两个场景等价。ID/版本为正整数；输入revision为正整数，用例库revision允许0。字符串不得含NUL，统一LF。普通说明最长10000字符；设计字段按下表；原文text不套说明长度。

候选每份JSON建议沿用16MiB上限，实际提供的图片/PDF附件另按已授权模型能力与读取上限核对；超出模型上下文/输出限制须在调用前拆批，不能截断后声称完整。附件未实际提供不能写已读；哈希只证明提供内容身份，不证明全原件完整。权限、来源绑定、图像能力和预算均由调用方强制检查。

## input顶层

`analysis_type, contract_version, request_id, project_id, revision, mode, scope, focus, materials, update_pairs, decisions, related_reports, cases, supplement, batch, input_limitations`。

mode为INITIAL/UPDATE；request_id由调用方生成且结果原样回传，project_id为正整数。input_limitations为字符串数组；focus不得改变固定范围/业务来源权威。

### scope与batch

scope：`name, full_scope, functions, target_ends, case_scope`。

- name为本次范围说明；full_scope表示所选资料/功能范围完整，不是全项目完整。
- functions每项`function_ref, name, scope_note`，至少一项；引用由调用方固定。target_ends为非空端名数组，端名由用户选择，不由模型猜测。
- case_scope：`description, complete, count, library_revision`。complete表示完整取得本次所选用例集合，不是全库；count必须等于cases长度。library_revision为调用方读取的真实修订号，离线未核实可null并列限制，模型不能声称仍最新。

batch：`plan_ref, batch_ref, index, total, function_refs, namespace, limitations`。index/total为正整数且index≤total；function_refs为本批非空功能引用且属于scope，namespace为调用方唯一批次前缀。单批也提供batch，index=total=1。所有输出对象key以namespace加冒号开头；semantic_key不加批次前缀。多批共享公共材料和统一用例/功能身份，重试保持batch_ref，换request_id并另存尝试链。批计划、进度、合并和费用由调用方保存，模型不输出运行状态。

### materials：内容身份及角色

每项：`snapshot_ref, source_id, kind, side, name, version_ref, read_state, read_note, content_sha256, segments`。

- kind为REQUIREMENT/PROTOTYPE/CONTRACT/CODE；side为CURRENT/BEFORE/SUPPLEMENT/CONTEXT。CURRENT是当前有效正文，SUPPLEMENT是增量资料，BEFORE是旧基准，CONTEXT只为补充。INITIAL不使用BEFORE/SUPPLEMENT或update_pairs。
- source_id由调用方验证项目来源；version_ref是固定文件版本/完整Git SHA/正文快照标识，不能只是实时分支名或URL。离线PROVIDED版本明确未与平台原件自动核实。
- read_state为READABLE/PARTIAL/UNREADABLE/NOT_LOADED。READABLE/PARTIAL至少一段实际非空正文或实际提供图片；PARTIAL需read_note。UNREADABLE/NOT_LOADED为空segments/hash且原因非空，不算规则不存在。
- segments每项`segment_id, location, text, image_ref`。segment_id在本snapshot唯一，location非空；text/image_ref至少一个非空。无图片时image_ref为空；图片必须映射本次真实附件，图像没有可摘录文本时证据quote为空，并保留视觉解释及边界。
- 有正文时content_sha256由调用方对片段text按顺序用LF连接的UTF-8计算64位SHA-256；纯图片时对固定附件字节计算并由调用方绑定。混合文本/图片的附件字节映射另外保存在调用方bindings，不让模型构造。

至少一个本批范围内的实际可读需求/原型正文，人工结论及契约可补充明确业务规则；仅CODE/REPORT/CASE/结论摘要不能启动生成。没有主正文时BLOCKED，不联网补读。片段裁剪与未读取来源列入input_limitations，full_scope不能掩盖正文不完整。

### update_pairs：逐组更新

每项：`pair_ref, before_ref, after_ref, update_mode, function_refs, scope_confirmed, scope_note, comparison_complete`。

- 两侧引用不同material，双方kind相同且为REQUIREMENT/PROTOTYPE/CONTRACT；before为BEFORE，after为CURRENT（FULL_REPLACEMENT）或SUPPLEMENT（INCREMENTAL_SUPPLEMENT）。source_id可不同，但scope_note须解释已确认的同范围配对。相同来源同固定版本不能比较。
- scope_confirmed必须true；function_refs为本批功能子集；scope_note非空。comparison_complete只说明比较范围/清单完整，还须核对双方正文read_state。
- INCREMENTAL_SUPPLEMENT继承旧规则，只明确覆盖/取消项变更；FULL_REPLACEMENT在确认范围内比较。没有旧正文时update_pairs为空，UPDATE按当前依据核对且列无历史限制。遗漏资料/未读页不能支持停用。

### decisions与related_reports

decisions每项：`decision_ref, version, statement, scope_note, function_refs, actor, confirmed_at, applicability, supersedes, origin, basis_refs`。

- applicability为VERIFIED_CURRENT/UNVERIFIED，由调用方核实；confirmed_at为带时区ISO日期。UNVERIFIED不得定义确定性预期；actor不可由模型伪造。
- supersedes引用本input其他decision_ref，无循环。origin为null或`{request_id, question_key}`，保留原问题；basis_refs为已提供snapshot_ref，可空但scope_note须说明用户直接确认。关联历史报告摘要不能代替实际结论文本。

related_reports每项：`report_ref, analysis_type, report_id, item_key, statement, handling_snapshot, review_warnings, basis_refs`。analysis_type为REQUIREMENT_ANALYSIS/CODE_REVIEW/CHANGE_IMPACT；report_id是调用方保存的固定标识，basis_refs引用提供的materials。仅作风险/范围线索；已处理状态不自动确认需求，不自动复核/关闭原问题。

### cases：当前设计及可选历史

每项：`case_ref, case_id, design_version, display_number, category_id, lifecycle, design, baseline`。case_ref和case_id均唯一；case_id是内部正整数，display_number仅展示；category_id正整数或null。lifecycle为ACTIVE/RETIRED/UNKNOWN，只记录真实快照，未接生命周期时UNKNOWN并列限制，不伪造平台已支持停用。

design恰为以下12个字符串字段，与现有cases.DESIGN_FIELDS一致，不含编号/分类/测试或审核字段：

| 字段 | 含义 | 最大字符数 |
| --- | --- | --- |
| module | 功能模块 | 500 |
| structure | 功能结构 | 1000 |
| case_type | 自由用例类型 | 200 |
| priority | P0–P4或空 | 2 |
| description | 用例描述 | 4000 |
| title | 验证用例子项 | 4000 |
| preconditions | 前置条件 | 30000 |
| steps | 操作步骤 | 30000 |
| expected | 场景级预期 | 30000 |
| remark | 备注 | 10000 |
| data_requirements | 测试数据要求（详情） | 10000 |
| cleanup | 清理要求（详情） | 10000 |

baseline为null或`{design_version, design, origin, adoption_ref}`，origin为APPLIED/DESIGN_HISTORY。它必须来自真实历史库版本/成功应用映射；APPLIED的adoption_ref非空，DESIGN_HISTORY可空。版本≤当前版本，版本相同必须设计相同；未应用/失败/仅草稿不能成为baseline。baseline=null仍可维护，但不能宣称已完成G/C/N核对。

supplement为null或`{parent_request_id, decision_refs, affected_scenario_refs, scope_note}`；decision_refs必须指向本input VERIFIED_CURRENT结论；affected_scenario_refs是父报告的真实场景key（由调用方绑定），本批范围须限定受影响场景及直接依赖。父报告不重写，旧人工草稿不丢弃。

## report顶层

`analysis_type, contract_version, request_id, project_id, revision, mode, batch_ref, outcome, summary, evidence, rules, transitions, flows, scenarios, suggestions, unchanged, conflicts, requirement_questions, discovery_gaps, coverage, limitations`。

身份、版本、mode/batch_ref严格回传input。outcome为COMPLETE/PARTIAL/BLOCKED；summary为具体处理摘要，不含质量分数/测试结果，统计由调用方从唯一key重新计算。limitations至少保留输入限制、仅静态/视觉读取边界、所选用例范围与无历史基准等事实。

### evidence

每项：`key, kind, target_ref, segment_id, side, field, quote, note`。

- MATERIAL：target_ref引用snapshot_ref，segment_id引用该快照实际可读片段，side严格相等；field为空。文本quote非空且必须是该片段唯一连续原文（不跨片段拼接/改写）；视觉片段quote可空，note必须说明实际观察内容，调用方验证附件映射。
- CASE：target_ref引用case_ref，segment_id为空，side为CURRENT/BASELINE，field为设计白名单字段，quote须唯一连续匹配对应版本字段。BASELINE仅在baseline非null时允许。
- DECISION：target_ref引用decision_ref，segment_id/field为空，side为CONTEXT，quote匹配statement；UNVERIFIED只支持问题/冲突，不能支持确定预期。
- REPORT：target_ref引用report_ref，segment_id/field为空，side为CONTEXT，quote匹配statement；只作线索。

当前业务依据指CURRENT可读MATERIAL、有效增量关系内BEFORE＋SUPPLEMENT MATERIAL、CONTEXT的明确适用业务资料（非CODE），或VERIFIED_CURRENT DECISION。独立BEFORE不是当前预期依据；CODE/CASE/REPORT不能独自支持规则、预期或停用。

### rules、transitions、flows

rules每项：`key, semantic_key, function_ref, object, actor, statement, branches, evidence_refs`。function_ref属于本批；业务规则只从当前有效依据提取；branches至少一项，每项`branch_ref, conditions, result, state, evidence_refs`。branch_ref为本报告唯一key，state为CONFIRMED/PENDING_DISCOVERY/PENDING_DECISION；CONFIRMED的result非空且有当前业务依据，未知结果留空不补造。一规则可有多个分支。

transitions每项：`key, flow_ref, rule_refs, branch_refs, object, from_state, action, actor, action_end, to_state, observation_ends, evidence_refs`。仅有证据支持的转换进入此数组，状态、动作和端非空；rule_refs/branch_refs指同功能相关规则/分支。flow_ref引用flows；action_end/observation_ends属于输入target_ends。未选端作为上下文在note/条件中说明，不自动生成其场景，范围外转换进入discovery_gaps/coverage而非假闭环。

flows每项：`key, object, transition_refs, state, note`，state为COMPLETE/PARTIAL。COMPLETE须状态图连通、首尾有依据、每个声明的操作/观察端都有READY场景去向且无遗漏转换；只描述所选子流程时note明确边界，不声称整个业务闭环。无生命周期时两数组均空。

### scenarios

每项：`key, semantic_key, function_ref, rule_refs, branch_refs, transition_refs, actor, action_end, observation_end, entry, conditions, action, expected, state, evidence_refs, note`。

state为READY/DESIGN_READY_SETUP_PENDING/PENDING_DISCOVERY/PENDING_DECISION/OUT_OF_SCOPE。READY要求有当前业务依据的角色/两端/入口/动作/预期，业务设计和执行准备明确；无状态转换时transition_refs为空。expected为字符串，允许多个相关可观察断言；不同业务分支不能塞进一个场景。业务预期明确而账号/数据/权限/观察入口或故障准备待补用DESIGN_READY_SETUP_PENDING，note明确待补，关联含具体reason/next_step的EXECUTION_SETUP；entry可以为空表示入口待核对，不编造具体方法。业务尚未完成提取/设计用PENDING_DISCOVERY；确实缺业务决定用PENDING_DECISION。OUT_OF_SCOPE须说明固定范围原因，不因为已生成数量够多而排除。

### suggestions与unchanged

suggestions每项：`key, kind, function_ref, scenario_refs, case_ref, base_version, design, changes, reason, priority_reason, evidence_refs, basis_status`。kind为NEW/REUSE/UPDATE/RETIRE；basis_status为SUPPORTED/NEEDS_REVIEW，均仍待人工审阅，不代表可直接应用。

| kind | 目标和设计字段 | 约束 |
| --- | --- | --- |
| NEW | case_ref/base_version=null；design为完整12字段；changes=[] | 至少一个READY或DESIGN_READY_SETUP_PENDING场景；后者必须NEEDS_REVIEW、data_requirements/remark非空并明确待补项，关联EXECUTION_SETUP，不宣称可立即执行；title/steps/expected非空；只有所选库中缺失才能建议新增，不声称全库无重复 |
| REUSE | case_ref指已选ACTIVE或UNKNOWN用例，base_version等于当前设计版本；design=null；changes=[] | 当前证据支持必要条件、动作、断言均满足；UNKNOWN需披露生命周期未核实；多匹配/相似进入NEEDS_REVIEW及conflicts |
| UPDATE | 当前case_ref/version；design=null；changes非空 | 每项`field, before, after, reason, evidence_refs`，白名单字段唯一，before逐字等于input当前C且before≠after；只修改必要字段，合成后title/steps/expected非空 |
| RETIRE | 当前case_ref/version；design=null；changes=[] | 有旧新可读依据与完整替换明确删除/不适用证明，或增量/有效结论明确取消；不以单独未提及作为理由；永不默认勾选/自动停用 |

scenario_refs必须属于同一function且非空；RETIRE可关联OUT_OF_SCOPE的原场景但须有明确取消证据。UPDATE同字段G≠C且新建议与C冲突时，basis_status=NEEDS_REVIEW且有MANUAL_CHANGE冲突。没有baseline时UPDATE必须NEEDS_REVIEW，关联MISSING_BASELINE discovery_gap，不伪造G。RETIRED同设计匹配进入RETIRED_MATCH冲突和人工恢复/新增核对，不能建议直接复用或自动恢复。

unchanged每项：`key, case_ref, base_version, scenario_refs, reason, evidence_refs`。用于UPDATE中已完整检查且无需操作的用例，不生成设计新版、不重置测试。INITIAL的匹配用REUSE；未检查用例不得放unchanged。一个case_ref不能同时unchanged和有操作建议；同目标多场景优先合为必要补丁，同一目标互相矛盾的操作必须conflicts关联，不能假装可同时应用。

### conflicts、questions与gaps

conflicts每项：`key, kind, function_ref, scenario_refs, suggestion_refs, field_comparisons, statement, options, evidence_refs`。

- kind为SOURCE_CONFLICT/MANUAL_CHANGE/AMBIGUOUS_MATCH/RETIRED_MATCH/TARGET_COLLISION。
- field_comparisons每项`case_ref, field, baseline, current, proposed`；current等于C，baseline等于G（G缺失可null），proposed等于对应UPDATE.after。MANUAL_CHANGE必须提供非空真实G/C/N，不能空基准冒充三方冲突。其他冲突此数组可空。
- suggestion_refs指受阻建议，所关联建议必须NEEDS_REVIEW；SOURCE_CONFLICT可只关联未生成建议的待澄清场景。options为人工选择建议，不填“已选择/已解决”。

requirement_questions每项：`key, function_ref, scenario_refs, parent_key, trigger, question, options, evidence_refs, impact`。parent_key为本报告问题key或null，无循环；trigger描述前置结论依赖，不输出伪人工状态/负责人决定。问题必须是真实业务缺口/冲突，关联PENDING_DECISION场景；options中的具体数值必须说明是待确认提议，不能进入确定预期。

discovery_gaps每项：`key, kind, function_ref, scenario_refs, case_refs, material_refs, reason, next_step`。kind为UNREAD_CONTENT/UNMODELED/EXECUTION_SETUP/MISSING_BASELINE/UNPROCESSED_SCOPE。记录未读、未建模、工具/环境准备或历史血缘不足，不把生成遗漏写成需求问题。

### coverage

对象：`input_units, functions, branches, scenarios, cases`。各数组不重复，以下全集逐项有去向：

- input_units：每个实际输入片段一项`{snapshot_ref, segment_id, state, rule_refs, scenario_refs, issue_refs, note}`；未读materials另记录segment_id=null。state为PROCESSED/NON_BUSINESS/UNPROCESSED/CONTEXT_ONLY。NON_BUSINESS说明排除依据，未解释内容为UNPROCESSED且有gap。BEFORE/代码/补充报告线索可CONTEXT_ONLY，不因此声称当前规则覆盖。
- functions：本批每个function_ref一项`{function_ref, scenario_refs, issue_refs, state, note}`，state为COMPLETE/PARTIAL/BLOCKED；其他批功能不写本批已完成。
- branches：每个规则分支一项`{rule_ref, branch_ref, scenario_refs, issue_refs, state, note}`，state为MODELED/QUESTION/GAP/OUT_OF_SCOPE。MODELED要求至少一个READY或DESIGN_READY_SETUP_PENDING场景，规则有引用不等于分支已建模。
- scenarios：每个场景一项`{scenario_ref, suggestion_refs, unchanged_refs, issue_refs, state, note}`，state为SUGGESTED/EXISTING/QUESTION/GAP/OUT_OF_SCOPE。SUGGESTED绑定NEW/UPDATE/RETIRE，EXISTING绑定REUSE/unchanged；QUESTION/GAP须有对应对象，OUT_OF_SCOPE有已确认边界理由。
- cases：每个已选case_ref一项`{case_ref, suggestion_refs, unchanged_refs, issue_refs, state, note}`，state为SUGGESTED/UNCHANGED/UNMATCHED/NOT_CHECKED。UNMATCHED不能解释为停用；NOT_CHECKED须有缺口，不因未出现在建议中就声称已核对。

COMPLETE只在本批有效范围全覆盖、没有questions/gaps/conflicts/NEEDS_REVIEW、没有PENDING场景或UNPROCESSED内容时成立；允许有依据的NON_BUSINESS/OUT_OF_SCOPE或0条新增。存在有效场景/建议但有局部缺口用PARTIAL；系统性门槛失败用BLOCKED，suggestions/unchanged为空，保留已知问题/覆盖去向。总记录完整性由调用方按整个计划汇总，不能用单批COMPLETE替代。

full_scope=true时，主资料存在PARTIAL/UNREADABLE/NOT_LOADED且影响声明范围，必须保留UNREAD_CONTENT及相应未处理覆盖，不能COMPLETE；补充上下文未读也须披露其影响，不能当已核实反证。选定资料只处理部分功能不等于资料缺失，但必须逐片段记录明确范围去向。

## 校验和人工应用职责（后续接入要求）

调用方强校验严格JSON、字段/长度/枚举、项目/固定版本/角色/附件绑定、key引用、摘录、设计白名单、case_id/version、patch.before、三方对照及覆盖全集。不存在/错侧引用、伪造编号/审核/执行字段或损坏对象使该报告硬拒绝，原始候选可保留，不伪装PARTIAL成功；合法报告内部的局部业务不确定保留PARTIAL有效建议。语义覆盖与断言正确性仍须人工审阅，哈希/结构合法不是语义已证明。

应用时再查当前库、权限、草稿revision、目标版本和全项目精确重复，不能依赖固定旧input判断实时安全。人工统一确认后每条用例/设计审核/映射/审计同事务；失败只回滚本条、失败审计独立保存、后续继续，任务级撤权暂停；成功不重放。新建编号由平台分配；修改保留身份与原编号；新增/修改成功为已审核未测、人员空，复用/无设计变化不造新版或重置测试。正式后端沿用本业务约定，准备待补不等于测试通过。

候选XLSX固定14列：序号、用例编号、功能模块、功能结构、用例类型、优先级、用例描述、验证用例子项、前置条件、操作步骤、预期结果、测试结果、测试人员、备注。编号/人员留空、结果未测由导出器赋值，不由模型输出；flow/key/证据/冲突/应用历史在完整报告中追溯，data_requirements/cleanup保留详情及JSON，不添第15列流程编号。单元格按字面文字，配对导入不是安全批量更新的替代。
