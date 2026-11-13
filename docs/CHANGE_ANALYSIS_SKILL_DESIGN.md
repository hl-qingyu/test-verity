# 变更分析 Skill 设计

<!-- document-status:start -->
> **历史资料，不再作为当前开发或运行规则。** 分析规则已接入，格式以当前契约为准。 当前说明见[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)、[contract.md](../skill/change-impact/contract.md)。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

2026-10-10后续授权：用户要求“接入变更分析”，Skill已提升1.0.0并由后端加载实际内容/hash，契约2用于AI与严格导入，正式任务/项目保存/处理/独立对话及来源准备已实施，见[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)。以下“未接入/v1预览”描述为当时设计状态，不再是当前运行限制。

2026-10-10 · v0.1草案。用户本轮要求设计变更分析Skill；沿用已确认页面和比较规则，新增项目内Skill指令、候选契约与合成示例，尚未接入AI/后台任务/数据库。既有正式页面状态见[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)。

入口：[skill/change-impact/SKILL.md](../skill/change-impact/SKILL.md)；精确字段：[contract.md](../skill/change-impact/contract.md)；行为验收：[evaluation.md](../skill/change-impact/evaluation.md)。路径沿用[专项方案](CHANGE_ANALYSIS_DESIGN.md)的change-impact，不新增个人Codex技能或在线Skill管理入口。

## 职责和边界

Skill分析“实际变化、影响、问题归因、回归范围”。调用方负责权限、固定新旧内容、生成确定性文本差异、个人AI配置、输入输出校验和后续保存；模型不自行获取资料、执行代码、扩读目录或操作业务数据。

| 主方式 | 变化依据 | 方法重点 |
| --- | --- | --- |
| 需求变更 | 已确认配对的固定需求正文 | 按角色/条件/动作/结果比较；完整替换与增量补充分开，未变规则不列卡片 |
| 代码变更 | 同来源双固定提交/浏览器快照、清单与diff | 沿调用/查询/返回/状态传播；按选中Bug、需求符合性、一致性分别核查 |
| 原型变更 | GitHub双提交原型，或已保存旧链接正文与新固定正文 | 核对实际可读入口/字段/文案/交互说明；HTML、视觉、运行行为分别保留证据边界 |

补充的当前实现、用例和历史报告不是必选主资料。缺少实现只影响实现跟进；无用例仍可给回归场景，但不能声称全库无用例或无影响。一致性仍强制需要目标侧双方实际代码，缺一端整次拦截。

## 调用与结果设计

调用前保存`input.json`：身份、主方式、选中目标、固定比较对、快照原文/存在性清单、调用方diff、补充上下文、内部用例ID/设计版本、显式历史问题及限制。两文件原始内容及实际使用Skill/契约需在未来任务中冻结，模型仅返回report。

结果分别保存changes、功能/代码/用例影响、risks、historical_reviews、regression_scope，并共用带BEFORE/AFTER/CONTEXT的evidence、chains、coverage。三个页面页签将来由这些对象生成，不强迫模型写三个互不一致的报告。

introduced要求可比旧新证据和因果变化；pre_existing允许记录影响扩大；缺旧依赖/规则时序则unknown。归因与严重程度、静态证据、人工处理独立。同根因多目标一条风险，目标视图分别给要求/实现或后端/客户端对照。

历史问题复核不更新旧状态；KEEP/UPDATE/RETIRE/ADD_SCENARIO均为维护或回归建议，不生成正式用例、不自动应用，不继承旧版测试通过。人工处理与AI原始报告分开留存。

## 与现有展示格式的关系

实时复核`frontend/src/changeAnalysisPage.ts`：当前parseChangePreview只校验v1展示字段（before/after说明、changes/risks/regression_scope等），注释明确它不是生产Skill校验器；范围草稿也没有完整双侧正文。不能将这些草稿直接发给模型当完整变更输入。

本候选采用独立`CHANGE_IMPACT`契约2，明确区别v1展示形状。不是修改现有页面接口，也不升级需求v3或代码分析v2；新示例暂不能在现有预览器导入。未来适配需把结构化影响/证据/历史复核映射到三页签、固定范围与详情，保留原始report，不降成几段展示字符串后丢失证据。

## 后续接入顺序（未实施）

先审阅契约/合成样例及行为规格，再实现服务端硬校验、固定来源绑定、双JSON导入和结果展示；随后在用户授权范围接现有`app.chat_worker`与本人AI。读取复用公开只读服务、网络等待释放事务、返回后复核授权；不恢复旧analysis_worker，不新增Redis/任意Agent。

源码坐标/原文/身份/引用错误硬拒绝；语义证据不足须人工核对。沿用需求待核对机制时另存平台警示/降级判断，不能静默改写原始报告或让introduced继续冒充确定结论。真实模型效果由单独评测确认，格式正确不证明分析正确。

本轮只交付设计文件、三组人工合成双JSON及静态核对。没有改业务前后端/页面/数据库/依赖或运行服务，没有调用AI/外部来源。验证结果完成后记录在SESSION_CONTEXT；行为验收表不作为已经执行的模型测试。
