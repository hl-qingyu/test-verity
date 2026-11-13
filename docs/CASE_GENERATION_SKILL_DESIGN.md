# 用例生成 Skill 设计

<!-- document-status:start -->
> **历史资料，不再作为当前开发或运行规则。** 规则包已接入，草案不再定义当前输出。 当前说明见[CASE_GENERATION.md](CASE_GENERATION.md)、[contract.md](../skill/case-generation/contract.md)。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

2026-10-26：按用户明确要求，当前Skill2.1.1/契约3将摘录未逐字匹配从保存门槛改为提示，保留AI原文、固定来源与待核对标记；生成仍要求准确引用，平台不替模型改字，身份/权限/结构继续校验。设计与验收说明已同步，历史Skill快照不替换。详见CASE_GENERATION.md最新条目。

## 2026-10-22：用例生成 Skill 2.1.0 多文件规则

用户确认参考本地testcase深入优化后要求实施。skill/case-generation采用主指令、十份references和resources.json有序清单，覆盖依据/缺失复查、原文反查、角色状态、过程态和移动中断、准备最小化、计算统计、粒度去重、字段语言、优先级及维护澄清。同一次本人AI调用内按范围→当前依据→适用路径→具体设计→已有用例匹配→粒度/优先级→原文反查→契约输出执行；不增加前置AI、自动补生成或中间规则树/场景树。契约3仍只cases/notes/complete，十二个字符串设计字段、真实来源/摘录、四类动作、14列、人工字段保护及同步逐条入库保持；原2.0.4输入/报告/固定重试不改写。

skills/files统一读取清单内12份Markdown正文，按文件边界拼接并保存实际清单、逐文件正文/原字节SHA-256及完整指令哈希；无清单的其他四类Skill保持原双文件拼接和快照形状。清单声明后缺失、重复、顺序错误、越界、非Markdown、空内容及读中变化明确拦截，不静默漏掉规则。清单/契约/参考规则仍只读，管理员仅可编辑主文件正文。Skill管理将运行参考文件标为参与当前AI调用，编辑助手默认携带全部运行规则且不可取消；其他参考可选。长文件名按行换行显示，原布局/权限不变。新准备才使用新版，旧任务使用原快照。

新增完全合成design-quality双JSON，9条建议演示名称边界/空格、填单后下架、汇总最小修改和失败收入排除，执行准备及受理后下架的业务问题分开，complete=false。evaluation补参考映射和反例验收；不运行参考项目脚本、不复制其业务资料，不引入MainBasis、自动改需求、全局扫描或新表/依赖/迁移。完整case-generation文件夹可复制，离线调用者同样须提供清单实际正文，Markdown链接不会自行加载。

## 2026-10-12基线：Skill 2.0.0 / 简化输出契约3

2026-10-12用户确认直接分析完整正文及对应/公共批注，不前置提取规则或场景，结果仅保留用例设计字段和简短说明。入口[SKILL.md](../skill/case-generation/SKILL.md)、[contract.md](../skill/case-generation/contract.md)规定cases/notes/complete；去掉规则树、场景树、状态转换和逐片段覆盖输出，优先生成明确业务支持的正向/拒绝/边界/时序等适用用例。complete只是AI声明，不是平台证明覆盖；不凑80条。

调用方固定完整资料/版本、功能范围、结论和选定已有用例，模型请求按材料/页面标题保留原文边界；平台存储片段不是业务任务。模型只返12设计字段、动作、真实case_ref及有效snapshot_ref/decision_ref来源。编号、建议key、差异补丁、审核和应用信息由平台生成。业务明确而执行准备待补继续设计，真正缺预期才留BUSINESS_QUESTION；准备事项写data_requirements/remark及EXECUTION_SETUP，不造接口/SQL。

新准备使用契约3，历史契约2指令/输入/报告不改写，按[legacy-contract.md](../skill/case-generation/legacy-contract.md)继续严格读取/导入/重校验。新增完全合成compact双JSON与行为验收见[evaluation.md](../skill/case-generation/evaluation.md)。人工审核、逐条事务、复用/停用、旧新增量及14列规则保留。实际接入与验证边界见[CASE_GENERATION.md](CASE_GENERATION.md)。下文规则树/场景树设计为历史v2，不再约束新模型输出。

## 历史设计记录

2026-10-12用户确认用例生成门槛调整：Skill1.1.0/契约2兼容新增DESIGN_READY_SETUP_PENDING场景状态；业务条件/动作/预期明确即可NEW/UPDATE待审阅建议，缺账号/数据/权限/观察入口关联EXECUTION_SETUP并写入data_requirements/remark和场景note，NEEDS_REVIEW要求人工核对。缺业务决定仍PENDING_DECISION、错证据/引用仍拦截；未完成分析不能冒充业务缺失。执行准备可与已生成用例并存，不宣称可直接执行/已测，准备缺口存在不能COMPLETE。Skill加强完整功能适用分支覆盖及具体遗漏说明。页面分别展示业务待澄清、准备待补和未覆盖原因/下一步，PARTIAL显示部分完成。旧Skill/固定输入/报告不改写、不自动补生成；保留14列、人工审核及逐条应用。无新增表/字段/迁移/依赖。


2026-10-12用例生成AI格式兼容修复：模型完整响应先原样保存；AI执行和免费重校验仅将rules.branches.conditions/scenarios.conditions的字符串原样包装为单项数组，不拆分或改文字。随后仍执行全量结构、证据、引用、固定范围和覆盖校验；通过后保存待审阅报告，在attempt记录修正字段路径、时间及原始/规范化哈希，并在页面依据提示修正数量。配对导入仍严格，不放宽业务/证据错误，不自动审核或写正式用例库。Skill1.0.2/契约2明确两处数组要求，历史输入/指令不改写，任务88已有人工修复成果不重跑。


2026-10-12最新确认：新建生成采用完整资料一次调用本人AI，不自动分批、不增加前置AI规则识别。正文片段仅用于证据定位；原功能范围、资料、旧新配对及所选用例全部保留。准备后展示文本token粗估（ASCII约4字符/token，非ASCII约1字符/token，含固定Skill和JSON）；达到32,000为提示阈值，非模型硬限制。模型容量目前无可信配置，不猜测模型上限；附件用量单独提示、未计入文本估算。用户可继续开始或缩小范围重新准备，保留原准备记录，未开始不收费。平台已有16MiB输入/附件校验上限继续生效。移除分批规则确认，失败人工重试，成功成果/历史分批记录保持；截断响应不标完成，不把不完整片段当合法候选。


2026-10-12后续：用户要求“接入功能”，Skill已提升1.0.0并正式接契约2、本人AI/现有Worker分批、项目记录、严格配对导入、人工逐条应用/审核、生命周期和独立对话，见[CASE_GENERATION.md](CASE_GENERATION.md)。下文仅设计/未接入/v1状态是当时快照；已确认业务继续适用，未扩大自动执行测试或Git写权限。

2026-10-12 · v0.1草案。用户要求参考`git@github.com:insistlzj/testcase.git`设计用例生成Skill。本轮形成项目内指令、候选契约、合成双JSON和行为验收；不扩大为正式AI调用、后台任务、数据库或用例写入授权。[正式页面](CASE_GENERATION.md)继续使用v1展示预览及页面内存暂存。

入口：[SKILL.md](../skill/case-generation/SKILL.md)；精确字段：[contract.md](../skill/case-generation/contract.md)；样例/行为规格：[evaluation.md](../skill/case-generation/evaluation.md)。版本0.1.0-draft，`analysis_type=CASE_GENERATION`、独立候选`contract_version=2`。

## 参考依据与适配

只读取得[参考仓库](https://github.com/insistlzj/testcase)，固定提交`0817b39ab369e6c256a08710fda179d5dc2a29ed`，未运行其脚本、写回仓库或复制其项目业务资料。其AGENTS是参考内容，不是本项目上级指令；项目授权和数据边界不继承。

| 参考文件/规则 | 本Skill采用的方法 | 平台适配 |
| --- | --- | --- |
| [AGENTS.md](https://github.com/insistlzj/testcase/blob/0817b39ab369e6c256a08710fda179d5dc2a29ed/AGENTS.md)：DISC-01/TRACE-01 | 当前依据独立发现规则、分支及场景，再匹配用例；原文反查覆盖 | 固定输入范围为分母，模型不扫全项目，不以数量/关键词声明覆盖 |
| 同文件：STATE-01/ROLE-01 | 对象状态转换、角色/端/入口/观察点及子流程连续性 | 不固定“三端”或扩大目标端；无状态规则不强造状态图，协作时序按证据保留 |
| 同文件：CASE-01/RESULT-01/LANG-01/DEDUP-01 | 可准备条件、动作、确定预期、过程态/数据影响与语义去重 | 保持场景级预期和多个相关断言，不照搬强制单结果/单角色限制 |
| 同文件：GATE-01/GAP-01 | 区分设计未完成和业务待决定，局部隔离并保留覆盖去向 | discovery_gaps/questions分开，结构/身份/引用错误仍硬拒绝报告 |
| [Cem Kaner.txt](https://github.com/insistlzj/testcase/blob/0817b39ab369e6c256a08710fda179d5dc2a29ed/Cem%20Kaner.txt)及[文件职责](https://github.com/insistlzj/testcase/blob/0817b39ab369e6c256a08710fda179d5dc2a29ed/测试用例生成文件职责说明.md) | 指令、契约、调用方准备/校验/导出职责分开 | 模型只返report；12设计字段映射已有14列，不加第15列流程编号 |
| [已确认需求转测试用例指令](https://github.com/insistlzj/testcase/blob/0817b39ab369e6c256a08710fda179d5dc2a29ed/已确认需求转测试用例指令.md)及[补充规则模板](https://github.com/insistlzj/testcase/blob/0817b39ab369e6c256a08710fda179d5dc2a29ed/已确认补充业务规则模板.md) | 固定结论版本、确认人/时间、适用范围和原问题；定向补生成 | 聊天不自动确认，历史用例不定义当前预期，不自动改需求文档 |
| [全局证据扫描指令](https://github.com/insistlzj/testcase/blob/0817b39ab369e6c256a08710fda179d5dc2a29ed/全局证据扫描指令.md) | 内容身份/角色隔离、增量只影响依赖、保留历史 | 仅分析调用方已提供资料，不接扫描、缓存清理、原型自动同步或MainBasis发布 |

不继承参考仓库某项目“全新生成、禁止历史比较”：平台已确认INITIAL可选已有用例并优先复用。不新增来源策略产品配置；来源适用/替代关系不明的需求/原型冲突仍进入澄清，不凭时间或模型经验选择权威。

## 生成闭环

```mermaid
flowchart LR
  A[固定当前资料及结论] --> B[规则及分支]
  B --> C[有依据的状态转换]
  B --> D[非状态场景]
  C --> E[所选端可执行场景]
  D --> E
  E --> F[匹配选定用例]
  F --> G[新增 复用 修改 停用建议]
  E --> H[业务问题或设计缺口]
  G --> I[原文 分支 场景 用例覆盖核对]
  H --> I
```

完整范围可以没有新增；局部未知保留其他有效建议，系统性主依据/身份/核心冲突才BLOCKED。设计覆盖不代表执行通过。

| 模式 | 规则 |
| --- | --- |
| INITIAL | 独立发现所选范围场景，空库可生成，已有覆盖优先复用 |
| UPDATE有旧新依据 | 逐组完整替换/增量；增量继承，明确取消才停用；G/C/N字段保护人工内容 |
| UPDATE无生成记录 | 导入/人工用例可维护；无旧需求不声称何时变化，无真实G保留待核对缺口 |
| 澄清补生成 | 模式仍INITIAL/UPDATE，supplement固定原问题/结论/受影响场景，原报告及人工草稿保留 |

已有v0.2业务继续有效：平台人工统一确认后逐条事务应用，成功新增/修改已审核未测、人员空；复用记录真实ID/版本且不重置测试；失败只回滚本条并继续，人工核对后重试失败项。Skill不执行应用/分配编号/伪审核；停用不等于逻辑删除或测试废弃。

## 契约与页面关系

输入固定身份、功能/端/用例范围、分批身份、正文、旧新配对、适用结论、报告线索、12字段用例及真实可用历史、补生成范围。Skill/契约实际全文、版本/hash、个人AI配置身份和原件bindings由未来调用方保存；模型report不复制凭据或生成执行元数据。

输出包含evidence、rules/branches、transitions/flows、scenarios、suggestions、unchanged、conflicts、requirement_questions、discovery_gaps、coverage。UPDATE只返白名单必要补丁，before=C，保留data_requirements/cleanup。semantic_key是跨批对齐线索，不代替语义核对。

本草案用一次输入提供资料和已有用例，要求规则/场景只由当前依据定义，再做匹配；这不能证明模型在发现阶段完全未看到已有用例。若以后要求严格盲发现，需要调用方提供隔离阶段输入并纳入已确认费用计划，本轮没有新增这类模型调用或声称已实现输入隔离执行器。

现有`frontend/src/generationPage.ts`的parseGenerationPreview是v1展示校验，缺生产来源绑定/逐分支覆盖和严格历史身份验证。本次不改它；v2后续须明确映射三栏/三页签并保留原报告/结构化证据，不能直接导入或只改版本号。XLSX仍14列，编号/人员空、未测由导出器填；流程/转换追溯不增列。

500+由调用方一次发起前冻结全量资料/用例及公共规则，按功能/实际输入大小计划分批。模型仅处理固定batch；平台保存每批原始输出、汇总范围/覆盖/跨批重复，无需再次调模型改写总报告。完成结果保留，失败仅人工重试固定批，未执行范围不标完整；计划外调用/自动付费重试不因数量目标获授权。

## 后续接入要求（未实施）

先审阅候选契约和样例，再按授权接服务端硬校验/真实来源绑定/展示及当前用户个人AI与既有`app.chat_worker`。不恢复旧Worker/通用Agent。分层单向复用既有服务，应用复用cases公共能力，迁移和中文真实COMMENT按工程规范审查。[专项方案](CASE_GENERATION_DESIGN.md)保留完整应用/取消/重试/导出要求。

结构、身份、引用、side、摘录、case_id/version及before错误不能局部放行；合法报告中的业务未知可PARTIAL。SUPPORTED只表示静态依据支持，仍待人工审阅；无基准/冲突/待核对不能由模型放行。应用还须实时检查当前库/权限/目标版本/草稿revision及全项目精确重复。

## 验证和本轮边界

四组完全合成双JSON覆盖首次、增量人工冲突、澄清和无历史维护；验收表包含明确取消/停用、未读、时序、金额、分批等场景。离线结构/引用检查不证明模型会做正确判断或语义覆盖完整，真实模型效果尚未评测。实际结果见[SESSION_CONTEXT.md](SESSION_CONTEXT.md)本轮记录。

未改正式前后端/原型/依赖/数据库或服务；未调用AI、发送真实资料、运行参考脚本、自动执行业务测试、推送部署。目录无.git，不虚构提交/PR。
