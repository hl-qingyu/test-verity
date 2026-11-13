# 文档目录

使用和启动平台先看[根目录README](../README.md)。开发时按下面的顺序阅读；历史方案和交接不需要每次通读。

## 必须遵守的工程规则

| 文档 | 何时阅读 |
| --- | --- |
| [AGENTS](../AGENTS.md) | 所有开发、修复、重构和续作 |
| [架构说明](ARCHITECTURE.md) | 同上，明确分层、依赖、执行流程和权限边界 |
| [代码规范](CODE_STANDARDS.md) | 同上，明确编码、数据、AI调用和验证要求 |
| [界面规范](UI_STANDARDS.md) | 涉及页面、弹窗、控件或交互时 |

当前用户指令优先。涉及已确认的架构、原型或业务约定变更时，先说明差异并确认。旧文档中的阶段限制不重复覆盖后续已经确认的实现。

## 按功能查阅

| 工作内容 | 当前说明 |
| --- | --- |
| 登录和账号 | [账号管理](LOGIN_ACCOUNTS.md) |
| 项目、成员和GitHub | [GitHub与项目](GITHUB_PROJECTS.md)、[项目删除](PROJECT_DELETION.md) |
| 项目概览 | [概览](PROJECT_OVERVIEW.md) |
| 需求资料 | [资料管理](DOCUMENTS.md) |
| 原型资料 | [原型资料](PROTOTYPE_MATERIALS.md)、[本地原型目录](LOCAL_PROTOTYPE_DIRECTORIES.md) |
| 本地代码 | [目录与快照](LOCAL_CODE.md) |
| 用例管理 | [用例管理](CASES.md)、[导入规则](CASE_IMPORT_RULES.md) |
| 需求分析 | [风险报告](REQUIREMENT_RISK_REPORTS.md)、[分析对话](REQUIREMENT_CHAT.md)、[调用包用法](REQUIREMENT_ANALYSIS_SKILL_PACKAGE.md) |
| 用例生成 | [生成、维护和审核入库](CASE_GENERATION.md) |
| 用例分析 | [需求对照、质量检查和应用修订](CASE_ANALYSIS.md) |
| 代码分析 | [代码分析](CODE_ANALYSIS.md) |
| 变更分析 | [变更分析](CHANGE_ANALYSIS.md)、[完整输入规则](CHANGE_ANALYSIS_FULL_INPUT.md) |
| 失败结果和人工修订 | [候选处理](ANALYSIS_CANDIDATES.md) |
| 分析记录删除 | [已实施的删除规则](ANALYSIS_RECORD_DELETION_DESIGN.md)；虽带设计后缀，仍是当前说明 |
| AI结果验收 | [指标与人工基准](AI_ACCEPTANCE.md) |
| AI服务 | [配置和公共调用](AI_SERVICE.md)、[API与Codex命令行](AI_CODEX_CLI_IMPLEMENTATION.md) |
| 分析规则管理 | [规则文件、编辑与助手](SKILL_MANAGEMENT.md) |
| 共用分页 | [分页和跳转](PAGINATION.md) |

模块说明保留各自的变更记录。遇到“尚未接入”“只做原型”等旧段落时，先核对前部已实施说明和当前代码，不把历史状态当作现行限制。

## 分析规则和结果格式

业务规则文件由程序实际读取，位于项目根目录 `skill/`，不放在本目录或个人技能目录。

| 分析 | 规则目录 |
| --- | --- |
| 需求分析 | [requirement-analysis](../skill/requirement-analysis) |
| 用例生成 | [case-generation](../skill/case-generation) |
| 用例分析 | [case-analysis](../skill/case-analysis) |
| 代码分析 | [code-review](../skill/code-review) |
| 变更分析 | [change-impact](../skill/change-impact) |

修改模块时核对对应目录的主说明、契约和引用清单。任务保存使用时的快照，旧任务不随当前文件变化。早期规则设计稿不能替代运行包。

## 原型和业务说明

总原型为项目根目录的 [verity-prototype.html](../verity-prototype.html)，后续直接修改此文件，右侧提供菜单页、弹窗和具体操作说明，支持搜索与展开收起。[审阅副本](prototypes/verity-requirement-risk-review.html)保留作参考。

说明栏的[维护文档](prototypes/verity-business-rules/README.md)和[规则清单](prototypes/verity-business-rules/RULES.md)用于核对业务。HTML使用演示数据，不代表已执行真实分析。

## 运行、排障和历史

| 材料 | 用途 |
| --- | --- |
| [日志](LOGGING.md) | 日志位置、轮转和安全诊断 |
| [局域网试用](LAN_TRIAL.md) | 临时同网访问，使用前核对地址和浏览器条件 |
| [中转排障](AI_RELAY_SUPPORT.md)、[504诊断](AI_RELAY_504_FIX.md) | 旧现场证据及候选处理方法，不能当作已部署结果 |
| [旧分批说明](CHANGE_ANALYSIS_BATCHES.md) | 解释历史任务和兼容逻辑，新任务使用完整输入 |
| [按需读取方案](LOCAL_READ_ANALYSIS_DESIGN.md) | 待评审能力，与当前CLI仅读取固定任务文件不同 |
| [会话交接](SESSION_CONTEXT.md) | 续作或追溯决定时按主题检索 |
| [文档整理清单](DOCUMENT_REVIEW.md) | 逐份分类、当前用途和替代关系 |
| [规则历史副本](archive/README.md) | 整理前的累计架构和代码规范 |

31份已被替代的方案、原型记录和旧实验说明，在原文件页首标注为历史资料。保留路径和正文以维护旧链接，不再作为日常开发入口。`outputs/`、`log/`、`work/` 和私有存储未做批量删除。
