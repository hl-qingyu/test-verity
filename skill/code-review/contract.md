# 代码分析调用契约 v3

配合 SKILL.md 3.0.0 使用。2026-09-21平台已接入本契约：AI执行和双文件导入均由后端严格校验，创建请求与本契约输入不同，由平台从已授权来源组装。v1输入不得按v2猜测来源类型，历史报告不自动转换。

## 通用规则

输入和输出各为一个JSON对象，不输出Markdown围栏。下列对象只含列出的字段，均必填；可空文本用空字符串，可空列表用空数组，不省略字段。标识字符串在对应作用域唯一、非空且最长200字符；说明文本最长10000字符、标题最长500字符。key、引用、目标列表不得重复。snapshot_ref是调用方给出的不可变快照标识，不能以网址、分支名或当前时间冒充。

检查目标：BUG、REQUIREMENT_DEVIATION、FRONTEND_BACKEND_MISMATCH。未选目标不得出现在结果关联中。sources可同来源多仓库；source_kind必须与source_mode相同，当前界面不混选GitHub与本地。

## 输入

顶层字段：contract_version=3、analysis_type="CODE_REVIEW"、request_id、source_mode（GITHUB/LOCAL）、targets（非空目标数组）、focus（字符串）、sources、materials、input_limitations（字符串数组）。

### sources

每个来源：source_id、source_kind、repository_kind、name、snapshot_ref、commit、files。

- source_kind：GITHUB或LOCAL；repository_kind：BACKEND、WEB、FLUTTER或OTHER，均由调用方从已授权来源登记读取。PROTOTYPE作为materials传入，不作为实现仓库。
- GITHUB.commit必须是固定40位十六进制SHA；LOCAL.commit必须为空，使用本次内容快照标识。样例SHA明确为虚构演示值。
- source_id在sources和materials之间全局唯一；name仅作标签，不构成证据。来源、版本、文件身份不可由模型改写。
- files每项：file_id、path、read_state、read_note、segments。file_id在本来源内唯一，path为来源内相对路径，不包含越界的..段。
- read_state：READABLE、PARTIAL、UNREADABLE、NOT_LOADED。READABLE表示完整文件已提供；其他状态read_note必须说明原因。可读内容必须有非空snapshot_ref。
- segments每项：segment_id、start_line、text；segment_id在本文件内唯一，start_line是正整数原文件行号，text为非空代码原文，换行统一LF。end_line由text.split("\n")行数推导；调用方切片时不添加用于展示的行号、不伪造首行位置。片段不得重叠；READABLE须从第一行起连续覆盖完整文件，是否到真实文件末尾由调用方验证。
- UNREADABLE/NOT_LOADED没有segments；PARTIAL至少有一个可用片段，并说明省略内容。哈希、授权和来源真实性由调用方核验，文字协议本身不能保证这些事实。

### materials

每份资料：source_id、name、origin（REQUIREMENT/PROTOTYPE/CONTRACT/DECISION）、snapshot_ref、read_state、read_note、segments。

资料段：segment_id、location、text、image_ref。location沿用固定文档段落、页码或截图位置；text/image_ref至少一项非空。image_ref只能引用本次实际提供的图片附件，不是待下载网址。没有能力读取附件时列为限制，不能自称已审查。read_state约束与代码一致。DECISION仅容纳本次明确提供的已确认决定；CONTRACT只作接口参考，不能替代一致性所需的一端代码。

### 输入门槛与失败

一致性被选中时，必须在BACKEND及WEB/FLUTTER来源中各至少取得一段可读代码；只登记仓库、未选择文件、只有空文件或未读文件不满足。缺任一端则整次INVALID_INPUT：返回BLOCKED诊断，所有目标BLOCKED，findings/evidence/chains为空，不继续其他目标。版本、类型、目标、标识等关键输入非法同样处理；缺request_id时诊断回传空字符串，调用方不得当正常报告保存。

有效输入下，需求符合性没有可读REQUIREMENT/PROTOTYPE/DECISION时，仅该目标BLOCKED；只提供CONTRACT不自动充当业务需求。其他目标可继续。两端都有内容但缺关键接口关系时，是有效输入中的证据缺口，不是创建门槛失败。

## 输出

顶层字段：contract_version=3、analysis_type="CODE_REVIEW"、request_id（原样回传）、summary、target_results、findings、evidence、chains、limitations。

summary：conclusion（非空说明主要发现及边界）、priority_finding_keys（findings.key子集，允许空）。不输出分数、通过率或人工验收结论。

### target_results：每个已选目标恰好一项

每项：target、status、scope（实际范围）、checks、finding_refs、limitation_refs。

status：COMPLETE/PARTIAL/BLOCKED。COMPLETE只表示该目标本次范围检查完成；PARTIAL已有有效审查但相关内容缺失或未处理；BLOCKED无法有效审查。无完整正文、相关内容未读、UNPROCESSED或关键关联未核实时，不得声称相关目标COMPLETE。

checks每项：key（全报告唯一）、subject、assessment、evidence_refs、finding_refs、note。

- assessment：CONSISTENT（静态一致）、DEVIATION（偏差成立）、SUSPECTED（具体疑点）、UNRESOLVED（无法判断）、OUT_OF_SCOPE（本次职责外）。不能把CONSISTENT说成运行通过。
- DEVIATION/SUSPECTED必须有非空evidence_refs和finding_refs；DEVIATION所关联目标视图必须为STATIC_SUPPORTED，SUSPECTED至少有INSUFFICIENT视图。CONSISTENT必须有证据且finding_refs为空；其余可以没有证据，不编造定位。
- finding_refs与findings.target_views对应：该目标的finding_refs恰好为其所有checks.finding_refs的集合，也恰好为关联本目标的findings.key集合。一个发现可以被多个目标关联，但只计一次总数。
- BLOCKED时checks和finding_refs为空，并至少关联一项说明阻塞原因的limitation。

平台计算总体 outcome。每个非 COMPLETE 目标须有 limitation_refs 解释边界。

### findings

每项字段：key、target_refs、title、category、severity、severity_reason、evidence_state、trigger、actual、impact、evidence_refs、chain_refs、target_views、fix_suggestion、verification_suggestion、missing_evidence。

- target_refs是非空已选目标子集；category是有意义的问题分类文本，如字段映射、状态处理，不替代检查目标。
- severity：HIGH/MEDIUM/LOW/UNASSESSED；severity_reason说明影响与条件，不能根据资料缺失直接判高风险。
- evidence_state：STATIC_SUPPORTED/INSUFFICIENT。各目标有独立判断；只要任一目标视图INSUFFICIENT，发现汇总状态为INSUFFICIENT。严重程度与证据状态独立。
- evidence_refs非空，指向本次evidence；chain_refs可为空，不为每个问题强凑调用链。actual是代码可支持的实际处理，impact说明已知与可能的影响，不扩成已发生事故。
- trigger、actual、impact、fix_suggestion、verification_suggestion均为非空文本。证据不足时修复建议可以写“先核查某防护，确认缺失后再调整”，不强造确定修复。
- target_views对target_refs恰好一项，每项：target、evidence_state、expected、basis、basis_refs、explanation、evidence_refs、comparison_rows。expected是该目标下的预期，basis说明依据性质，explanation集中说明结论与反证核查边界。
- 每个视图evidence_refs非空；basis_refs是证据引用数组。需求符合性视图必须通过basis_refs引用实际业务需求/原型/决定材料。一致性STATIC_SUPPORTED视图的evidence_refs必须同时包含客户端与服务端代码及配对支持，不能只引用材料。
- comparison_rows每项：label、left、right；left/right均为statement、evidence_refs。需求符合性左侧为要求、右侧为实现；一致性左侧为服务端、右侧为某个客户端。未取得一侧明确写未知并用空引用，不虚构文件；对已证实的对照不能留空证据。一条发现可多行比较，但不得混淆不同客户端。
- Bug可以没有comparison_rows；需求符合性和一致性视图至少一行。没有这两类目标时不强制比较表。每个视图的evidence_refs/basis_refs/比较引用应包含在发现evidence_refs内。
- missing_evidence每项：needed、reason、effect，均为非空文本。它是补充建议，不是证据引用。INSUFFICIENT发现至少一项，STATIC_SUPPORTED可为空；仅缺资料而无具体疑点用limitations。

输出不含status、handled_by、handled_at等人工处理字段，也不含测试已通过或已执行标志。所有发现均属静态分析。

### evidence

key在整个evidence数组唯一。使用两种精确结构：

- CODE：key、kind="CODE"、source_id、file_id、segment_id、start_line、end_line、excerpt、observation。引用可用代码片段；行号范围必须落在该段内，excerpt必须逐字等于该范围的完整原文行（LF换行），不拼接其他位置。展示的路径、类型、提交与快照从输入取，模型不重写。
- MATERIAL：key、kind="MATERIAL"、source_id、segment_id、excerpt、observation。excerpt非空时必须为该段text的连续原文子串；仅图片证据excerpt为空，observation必须具体说明所见。两者至少一项非空，不能引用未提供或不能读取的附件。

所有*_refs均须指向存在的对象，不能用模型建议的文件路径当证据。代码/资料快照显示字段由调用方依据引用从原始输入取得。

### chains

每条：key、nodes、edges。nodes至少一项，每项：key（链内唯一）、label、observation、inputs、outputs、evidence_refs（非空代码证据引用）。没有证据的未知环节不生成虚构节点；放到missing_evidence/limitations，或在已知节点之间标明UNKNOWN连接。

edges每项：from、to、relation、evidence_refs、note。两端指向本链节点，不能自连；relation为CALL、RETURN、FIELD_MAPPING、STATE_ASSIGNMENT或UNKNOWN。前四类必须有非空代码证据，note解释支持该连接的具体事实；UNKNOWN允许空证据，但必须说明为何无法核实。节点存在本身不证明连接；不得用CALL表示后端直接调用前端。多个独立根因不塞进一条无关长链。

### 平台覆盖

平台统计各来源的可读、部分和不可读文件，并计算总体 outcome。候选只输出目标判断。未评估的文件使用 NOT_ASSESSED 限制，附 file_refs [{source_id, file_id}]。CODE 证据在段号或行号未知时可返回 null，保持真实文件身份和完整原文摘录，由平台唯一匹配补齐。

### limitations

每项：key、kind、target_refs、source_refs、detail、effect。kind为INVALID_INPUT、MISSING_CODE、MISSING_MATERIAL、PARTIAL_CONTENT、UNREADABLE、UNRESOLVED_RELATION或OUT_OF_SCOPE。target_refs只引用已选目标；source_refs只引用输入来源，未提供的依赖用空数组并在detail说明，不能捏造来源ID。detail/effect非空。


## 调用与验证边界

调用方应校验精确字段、类型、枚举、长度、唯一ID、完整覆盖、目标双向关联、角色、位置与原文、目标状态和汇总状态。校验成功也不代表语义正确；结果需要人工审阅，人工处理独立保存，不静默改写历史。

本目录`scripts/check_examples.py`只离线检查合成示例和关键反例，不是生产请求校验器，不读取数据库、源码目录、凭据或网络，不执行示例代码。生产结构和引用校验位于backend/app/modules/code_analysis/contract.py；独立Worker使用创建时固定的Skill文本和输入。真实模型语义质量不由协议校验保证。
