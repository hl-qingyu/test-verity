# 文档整理清单

本次检查根目录README、AGENTS及docs下66份顶层说明，并核对现有路由、业务服务、启动脚本、配置和迁移。分类按用途和内容判断，不按文件名后缀判断。

## 必须读哪些

开发先读根目录AGENTS、ARCHITECTURE和CODE_STANDARDS。界面任务再读UI_STANDARDS；具体业务只读对应模块说明和本模块规则包。无需每次通读设计历史或会话交接。

## 哪些已不再需要日常维护

31份旧方案、原型记录和实验说明已停止作为现行依据，原文件页首标出替代文档。保留原路径和正文供历史链接、决策及旧记录追溯；未删除文件。

ARCHITECTURE和CODE_STANDARDS已整理为现行规则，原来的累计内容分别保存在archive下。其他模块说明仍保留自身变更记录，阅读时优先看最新已实施内容。

“不再作为当前依据”不等于“数据或代码可以删除”。旧分批兼容、数据库迁移、固定规则快照、已发布版本和私有业务文件均不在此次清理范围。

## 工程规则（3份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 当前架构、分层、执行进程和依赖边界 | 保留本文件 |
| [CODE_STANDARDS.md](CODE_STANDARDS.md) | 当前编码、AI调用、数据和交付规则 | 保留本文件 |
| [UI_STANDARDS.md](UI_STANDARDS.md) | 界面任务必须遵守的控件、布局和验收规则 | 保留本文件 |

## 模块说明（26份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [AI_ACCEPTANCE.md](AI_ACCEPTANCE.md) | AI结果统计、人工处理口径和基准清单 | 保留本文件 |
| [AI_CODEX_CLI_IMPLEMENTATION.md](AI_CODEX_CLI_IMPLEMENTATION.md) | API与Codex命令行的现行调用方式、运行要求和权限 | 保留本文件 |
| [AI_SERVICE.md](AI_SERVICE.md) | 个人AI配置、测试、模型请求和错误处理 | 保留本文件 |
| [ANALYSIS_CANDIDATES.md](ANALYSIS_CANDIDATES.md) | 失败候选查看、人工修订和重新检查 | 保留本文件 |
| [ANALYSIS_RECORD_DELETION_DESIGN.md](ANALYSIS_RECORD_DELETION_DESIGN.md) | 分析记录删除；虽带DESIGN名称，实际已实施，继续保留 | 保留本文件 |
| [CASE_ANALYSIS.md](CASE_ANALYSIS.md) | 用例质量检查、需求对照、人工草稿和后台应用 | 保留本文件 |
| [CASE_GENERATION.md](CASE_GENERATION.md) | 生成与维护、准备确认、连续审核和同步逐条入库 | 保留本文件 |
| [CASE_IMPORT_RULES.md](CASE_IMPORT_RULES.md) | 用例文件导入、分类、重复和字段规则 | 保留本文件 |
| [CASES.md](CASES.md) | 用例设计、版本、测试记录、批量编辑和生命周期 | 保留本文件 |
| [CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md) | 变更范围、任务、处理、对话和导出 | 保留本文件 |
| [CHANGE_ANALYSIS_FULL_INPUT.md](CHANGE_ANALYSIS_FULL_INPUT.md) | 新建和重试变更任务的完整输入规则 | 保留本文件 |
| [CODE_ANALYSIS.md](CODE_ANALYSIS.md) | 代码来源、检查目标、结果校验和人工处理 | 保留本文件 |
| [DOCUMENTS.md](DOCUMENTS.md) | 需求资料上传、版本、分组和附件关联 | 保留本文件 |
| [GITHUB_PROJECTS.md](GITHUB_PROJECTS.md) | 个人GitHub连接、项目、成员和仓库管理 | 保留本文件 |
| [LOCAL_CODE.md](LOCAL_CODE.md) | 本地目录授权、读取范围和浏览器快照 | 保留本文件 |
| [LOCAL_PROTOTYPE_DIRECTORIES.md](LOCAL_PROTOTYPE_DIRECTORIES.md) | 目录原型上传、版本文件索引和分析选材 | 保留本文件 |
| [LOGGING.md](LOGGING.md) | 日志位置、轮转和敏感内容处理 | 保留本文件 |
| [LOGIN_ACCOUNTS.md](LOGIN_ACCOUNTS.md) | 登录、会话、账号管理和初始化 | 保留本文件 |
| [PAGINATION.md](PAGINATION.md) | 统一分页与页码跳转控件 | 保留本文件 |
| [PROJECT_DELETION.md](PROJECT_DELETION.md) | 项目删除权限和活动任务限制 | 保留本文件 |
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | 项目汇总、待办和记录跳转 | 保留本文件 |
| [PROTOTYPE_MATERIALS.md](PROTOTYPE_MATERIALS.md) | 原型资料来源、网页预览和页面采集 | 保留本文件 |
| [REQUIREMENT_ANALYSIS_SKILL_PACKAGE.md](REQUIREMENT_ANALYSIS_SKILL_PACKAGE.md) | 需求分析调用包和导入用法；格式以当前规则包契约为准 | 保留本文件 |
| [REQUIREMENT_CHAT.md](REQUIREMENT_CHAT.md) | 需求报告对话、消息引用和人工新增风险 | 保留本文件 |
| [REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md) | 需求风险报告、固定资料、人工处理和导入导出 | 保留本文件 |
| [SKILL_MANAGEMENT.md](SKILL_MANAGEMENT.md) | 本地规则包、管理员修改、备份和AI助手 | 保留本文件 |

## 历史兼容（1份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [CHANGE_ANALYSIS_BATCHES.md](CHANGE_ANALYSIS_BATCHES.md) | 旧分批任务仍需读取和解释，不能当无用文档删除；新任务看完整输入说明 | 保留本文件 |

## 运行参考（3份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [AI_RELAY_504_FIX.md](AI_RELAY_504_FIX.md) | 历史504诊断和配置候选，未证明远端已应用；不是可直接执行的部署指令 | 保留本文件 |
| [AI_RELAY_SUPPORT.md](AI_RELAY_SUPPORT.md) | 服务方排障材料，处理前重核现场，旧失败不代表当前状态 | 保留本文件 |
| [LAN_TRIAL.md](LAN_TRIAL.md) | 仅局域网临时试用时查阅，不是正式部署方案 | 保留本文件 |

## 待评审方案（1份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [LOCAL_READ_ANALYSIS_DESIGN.md](LOCAL_READ_ANALYSIS_DESIGN.md) | 任意授权范围的按需读取未按此稿全面实现；当前CLI仅读取本任务固定输入，不能混为同一能力 | 保留本文件 |

## 已确认待实施方案

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [REDESIGN_PLAN.md](REDESIGN_PLAN.md) | 2026-11-25 用户确认的重构与重设计任务包；实施前现行行为仍以各模块文档为准 | 保留本文件 |
| [AI_OPTIMIZATION_PLAN.md](AI_OPTIMIZATION_PLAN.md) | 原 AI 调用优化方案；未实施部分已由重设计方案取代或暂缓 | [REDESIGN_PLAN.md](REDESIGN_PLAN.md) |

## 会话记录（1份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [SESSION_CONTEXT.md](SESSION_CONTEXT.md) | 仅续作、追溯决定或授权不清时检索，不作为日常规则总表 | 保留本文件 |

## 历史资料（31份）

| 文档 | 处理及用途 | 当前替代说明 |
| --- | --- | --- |
| [AI_CODEX_CLI_PLAN.md](AI_CODEX_CLI_PLAN.md) | 双调用方式已实施，旧阶段门槛不再使用 | [AI_CODEX_CLI_IMPLEMENTATION.md](AI_CODEX_CLI_IMPLEMENTATION.md) |
| [AI_WEBSOCKET_TRANSPORT.md](AI_WEBSOCKET_TRANSPORT.md) | 失败方案已撤下，仅留排障记录，不是生产通道 | [AI_SERVICE.md](AI_SERVICE.md) |
| [ANALYSIS_INPUT_OUTPUT_DESIGN.md](ANALYSIS_INPUT_OUTPUT_DESIGN.md) | 跨模块初稿已由各模块实际契约和服务取代 | [CODE_ANALYSIS.md](CODE_ANALYSIS.md)、[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)、[CASE_GENERATION.md](CASE_GENERATION.md)、[CASE_ANALYSIS.md](CASE_ANALYSIS.md)、[REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md) |
| [CASE_ANALYSIS_DESIGN.md](CASE_ANALYSIS_DESIGN.md) | 用例分析方案已落地 | [CASE_ANALYSIS.md](CASE_ANALYSIS.md) |
| [CASE_ANALYSIS_PROTOTYPE.md](CASE_ANALYSIS_PROTOTYPE.md) | 仅记录当时原型交付，不是当前功能限制 | [CASE_ANALYSIS.md](CASE_ANALYSIS.md) |
| [CASE_GENERATION_BATCH_REVIEW_DESIGN.md](CASE_GENERATION_BATCH_REVIEW_DESIGN.md) | 批量审核已落地，旧交互被后续简化 | [CASE_GENERATION.md](CASE_GENERATION.md) |
| [CASE_GENERATION_CONTINUOUS_REVIEW_PROTOTYPE.md](CASE_GENERATION_CONTINUOUS_REVIEW_PROTOTYPE.md) | 连续审核已落地，原型阶段授权描述过时 | [CASE_GENERATION.md](CASE_GENERATION.md) |
| [CASE_GENERATION_DESIGN.md](CASE_GENERATION_DESIGN.md) | 生成方案已由完整输入和当前审核流程替代 | [CASE_GENERATION.md](CASE_GENERATION.md) |
| [CASE_GENERATION_PROTOTYPE.md](CASE_GENERATION_PROTOTYPE.md) | 多次原型交付记录，当前以正式实现为准 | [CASE_GENERATION.md](CASE_GENERATION.md) |
| [CASE_GENERATION_SKILL_DESIGN.md](CASE_GENERATION_SKILL_DESIGN.md) | 规则包已接入，草案不再定义当前输出 | [CASE_GENERATION.md](CASE_GENERATION.md)、[contract.md](../skill/case-generation/contract.md) |
| [CHANGE_ANALYSIS_DESIGN.md](CHANGE_ANALYSIS_DESIGN.md) | 变更分析已实施，旧执行方案不能覆盖完整输入规则 | [CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)、[CHANGE_ANALYSIS_FULL_INPUT.md](CHANGE_ANALYSIS_FULL_INPUT.md) |
| [CHANGE_ANALYSIS_PROTOTYPE.md](CHANGE_ANALYSIS_PROTOTYPE.md) | 变更原型阶段记录已被正式功能替代 | [CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md) |
| [CHANGE_ANALYSIS_SKILL_DESIGN.md](CHANGE_ANALYSIS_SKILL_DESIGN.md) | 分析规则已接入，格式以当前契约为准 | [CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)、[contract.md](../skill/change-impact/contract.md) |
| [CODE_ANALYSIS_DESIGN.md](CODE_ANALYSIS_DESIGN.md) | 代码分析设计已落地 | [CODE_ANALYSIS.md](CODE_ANALYSIS.md) |
| [CODE_REVIEW_SKILL_DESIGN.md](CODE_REVIEW_SKILL_DESIGN.md) | 规则设计过程，当前以运行包和模块说明为准 | [CODE_ANALYSIS.md](CODE_ANALYSIS.md)、[contract.md](../skill/code-review/contract.md) |
| [CODEX_DIRECT_DEMO.md](CODEX_DIRECT_DEMO.md) | 旧浏览器直连实验，未用于正式业务；现有演示代码未删除 | [AI_CODEX_CLI_IMPLEMENTATION.md](AI_CODEX_CLI_IMPLEMENTATION.md) |
| [DATABASE_DESIGN_DRAFT.md](DATABASE_DESIGN_DRAFT.md) | 初始候选表结构，不代表已建表，不能据此建库 | [models.py](../backend/app/db/models.py)、[versions](../backend/migrations/versions) |
| [FEATURES.md](FEATURES.md) | 多轮状态追加混有过时结论，停止作为功能总表 | [根目录 README](../README.md) |
| [LOCAL_ANALYSIS_SESSION_PLAN.md](LOCAL_ANALYSIS_SESSION_PLAN.md) | 早期会话和设备方案已由后端个人AI调用取代 | [REQUIREMENT_CHAT.md](REQUIREMENT_CHAT.md)、[AI_CODEX_CLI_IMPLEMENTATION.md](AI_CODEX_CLI_IMPLEMENTATION.md) |
| [LOCAL_PROTOTYPE_DIRECTORY_PLAN.md](LOCAL_PROTOTYPE_DIRECTORY_PLAN.md) | 本地原型目录已实施 | [LOCAL_PROTOTYPE_DIRECTORIES.md](LOCAL_PROTOTYPE_DIRECTORIES.md) |
| [OTHER_ANALYSIS_DESIGN.md](OTHER_ANALYSIS_DESIGN.md) | 四类分析已分别实施，不再使用首期总体草案 | [CODE_ANALYSIS.md](CODE_ANALYSIS.md)、[CHANGE_ANALYSIS.md](CHANGE_ANALYSIS.md)、[CASE_GENERATION.md](CASE_GENERATION.md)、[CASE_ANALYSIS.md](CASE_ANALYSIS.md) |
| [PROJECT_OVERVIEW_DESIGN.md](PROJECT_OVERVIEW_DESIGN.md) | 概览已实施，验收汇总已独立成页 | [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)、[AI_ACCEPTANCE.md](AI_ACCEPTANCE.md) |
| [PROJECT_OVERVIEW_PROTOTYPE.md](PROJECT_OVERVIEW_PROTOTYPE.md) | 旧布局演进记录，不能恢复已移除的验收面板 | [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)、[AI_ACCEPTANCE.md](AI_ACCEPTANCE.md) |
| [REQUIREMENT_ANALYSIS_DEVELOPMENT_PLAN.md](REQUIREMENT_ANALYSIS_DEVELOPMENT_PLAN.md) | 阶段计划已落地，旧调用时限和未接入描述过时 | [REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md)、[REQUIREMENT_CHAT.md](REQUIREMENT_CHAT.md)、[AI_SERVICE.md](AI_SERVICE.md) |
| [REQUIREMENT_ANALYSIS_INTEGRATION.md](REQUIREMENT_ANALYSIS_INTEGRATION.md) | 已停用的第2版接入历史，不执行旧后台启动命令 | [REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md)、[REQUIREMENT_CHAT.md](REQUIREMENT_CHAT.md) |
| [REQUIREMENT_RISK_PROTOTYPE.md](REQUIREMENT_RISK_PROTOTYPE.md) | 需求风险原型已由正式报告功能取代 | [REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md) |
| [REQUIREMENTS.md](REQUIREMENTS.md) | 旧人工验收点主页面已退役，底层保留能力不删除 | [REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md) |
| [REQUIREMENTS_PROTOTYPE.md](REQUIREMENTS_PROTOTYPE.md) | 旧验收点原型记录，需求主流程已改为风险报告 | [REQUIREMENT_RISK_REPORTS.md](REQUIREMENT_RISK_REPORTS.md) |
| [SKILL_MANAGEMENT_DESIGN.md](SKILL_MANAGEMENT_DESIGN.md) | 文件查看、管理员写回和助手已落地 | [SKILL_MANAGEMENT.md](SKILL_MANAGEMENT.md) |
| [SKILL_MANAGEMENT_PROTOTYPE.md](SKILL_MANAGEMENT_PROTOTYPE.md) | 旧原型交付，当前使用真实文件和后台助手 | [SKILL_MANAGEMENT.md](SKILL_MANAGEMENT.md) |
| [TEST_CASES_PLAN.md](TEST_CASES_PLAN.md) | 用例管理首期方案已由正式功能和导入规则替代 | [CASES.md](CASES.md)、[CASE_IMPORT_RULES.md](CASE_IMPORT_RULES.md) |

## 根目录、原型和运行文件

| 位置 | 处理 |
| --- | --- |
| [根目录README](../README.md) | 已按当前代码完整重写，作为功能和运行入口 |
| [AGENTS](../AGENTS.md) | 长期约束，保留，不追加本次整理过程 |
| [本整理清单](DOCUMENT_REVIEW.md) | 文档导航和分类记录，后续随文档用途变化维护 |
| [原型业务说明](prototypes/verity-business-rules/README.md)及其规则清单 | 当前原型说明和维护材料，保留 |
| docs/prototypes中的HTML和检查脚本 | 原型及验证材料，不按旧方案文档删除 |
| skill下的主说明、契约和引用文件 | 程序实际读取，不能并入历史文档清理 |
| outputs、log、work、backend/storage | 临时产物或运行/业务数据，不属于工程规则；未逐件核验，未批量删除 |

## 后续维护

现行规则直接修订和去重，过程写入会话记录。功能变化同步对应模块说明；方案落地后在原稿标明替代文档，不继续把阶段状态追加到根目录README。文档分类发生变化时更新此清单。
