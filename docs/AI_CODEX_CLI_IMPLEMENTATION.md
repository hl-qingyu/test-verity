# API / Codex CLI 实施契约

2026-11-13进度修复：使用read1及时消费不足64KiB的CLI事件，启动/等待/推理/固定资料读取分别投影，输出字数按已收到agent_message计算，不发布正文；事件/进程结束依旧不能代替业务JSON和契约校验。77项相关后端、213项前端及check/build通过，最终7项进度/取消/管道/架构复测通过。真实失败候选中的冲突priority按用户明确选P1单独人工修正，保留原件和审计，没有默认放宽重复字段校验或新增AI调用，见SESSION_CONTEXT。

2026-11-12最新确认：用户要求正式可用，并明确允许原生CLI的多轮模型请求、内部重试及上下文压缩，随后确认超过stdin上限时采用独立任务目录和受限只读工具读取完整资料。此确认替代下文早期“未验证不能激活”以及CLI单次输入/禁重试门槛；API原行为保持。当前规则见下节。

## 原生业务调用（现行）

- 已安装固定0.166.0时runtime返回available=true / execution_policy=native-v1，个人CLI可“保存并使用”。实际切换由用户在设置页完成；平台不擅自将保存的CLI配置设为当前方式，不触发收费验证。
- 五类分析、独立对话及Skill助手沿公共ai_client进入原生codex exec。本人Key、模型、强度、任务固定方式/版本和原业务契约校验保持；原API调用不受CLI的新授权影响。旧缺方式任务仍API。新CLI任务快照增加execution_policy，不改写历史。
- 业务CLI直连所配模型服务，保留CLI原生多轮、HTTP/SSE重试、上下文压缩和等待默认值；平台不增加总时限、不调用测试网关、不限制只发一次模型请求，也不在CLI失败后自动换API或重新提交任务。CLI本身仍可能有空闲超时/重试上限，不能宣称供应商或CLI无限等待。一个Worker槽代表一次CLI进程生命周期，实际模型调用数仍未知。
- 固定Skill和可信developer规则通过独立model_instructions_file传入，原messages角色/顺序/文字保存。小输入通过stdin完整传递。真实0.166.0实测stdin超过1,048,576字符在turn/start前本地拒绝；平台在90万字符以上改为将完整输入写入本次input/input.json，附尺寸/SHA256及读取说明。无平台摘要、截断或先挑来源。
- 大输入通过固定本地MCP stdio工具read_input/search_input读取，只有input.json白名单、受限字节范围和UTF-8边界，支持完整连续读取和字面量查找。工具只能访问本次文件，不能选择命令、URL、其他路径、数据库或平台密钥。CLI的functions.exec可编排这些固定工具；不提供shell/任意脚本接口。采用deny根目录、最小运行目录与本次工作目录只读的权限profile，禁用命令执行、外部搜索、通用图片读取及插件/其他MCP。受限文件工具的只读自动批准仅覆盖这两个固定工具。
- 模型自主决定读取和压缩策略，原始完整资料始终保留在任务固定快照；保存报告不证明全部资料已被模型阅读或结论已正确，继续原引用/结构校验和人工审核。
- 图片按顺序映射至原生--image，落盘字节保持原件；固定资料中的引用说明保留。PDF没有当前原生映射，明确拒绝且提示API，不静默转纯文本。CLI多段过程说明只保留最后agent_message作为业务候选，已恢复的错误事件不单独推翻最终完成；退出码非0、turn.failed、不完整/空结果继续失败。
- 每次调用仍使用独立CODEX_HOME、临时输入、Windows Job Object及不依赖stdout的取消检查。CLI只获本人模型Key，不继承平台.env或登录态；原始JSONL/stderr脱Key加密到events.enc，输入/配置临时目录在结束后清理。受限stdio工具只用标准库，无新第三方依赖、业务表或迁移。
- 原固定文字连接测试仍有独立120秒和单次网关约束，仅用于按钮测试；它不限制业务原生流程。


2026-11-12补充：按用户选择独立开放CLI固定文字连接测试，由用户本人手动点击。`probe_available=true`不改变业务`available=false`；先前“不能测试真实模型”仅保留为11日阶段历史，当前测试规则如下。

2026-11-11：用户确认本轮包含并发，总并发2、单用户1、同服务同Key1；Windows后端，CLI固定0.166.0。未验证能力不得激活，不执行真实收费验证。

## 原生接入验收（2026-11-12）

相关后端71项、前端213项及check/build、Ruff通过，日志见outputs/cli-native-backend-final-20261112.log、cli-native-real-exe-20261112.log及cli-native-frontend-*.log。真实固定exe使用本地假provider验证多轮与原生重试、图片原件映射、超stdin文件工具读取；只读工具完整重组多字节原输入、其他路径拒绝通过。没有使用用户真实Key发请求，不能据此宣称已解决实际中转大文件或长耗时失败。

本地API与Worker已在无活动任务后重载，API/5173代理ready=200，Worker ready且持续运行，runtime available=true / native-v1；真实迁移头仍20261111_44，无新迁移/依赖。用户自行在设置选择CLI并保存并使用，不自动切换其当前方式。临时视觉服务器5174交付关闭。

## 个人配置接口

- `GET /api/ai-service` 保留 `personal` API元数据，增加 `cli`、`call_mode`、`preference_version`、`cli_runtime`。不返回Key、密文、内部路径或凭据摘要。
- `POST /personal` 保留旧客户端的仅保存API语义。
- `POST /configuration` 加密提交原配置字段、`call_mode`、`preference_version`、`activate`。配置版本与偏好版本分别校验；同事务保存/激活。不变配置不重加密、不增配置版本；激活递增偏好版本。CLI不可用时只允许 `activate=false`，返回实际方式与未激活原因。
- `POST /activate` 加密提交 `call_mode`、`version`、`preference_version`，只切偏好，不重写配置。
- `POST /test` 加密提交当前表单及 `call_mode`；不保存、不切换。与Worker共用数据库预算，无空位返回 `ai_call_busy`。
- `POST /personal/models` 保留API模型列表协议。CLI只手动输入模型。

无偏好的历史用户按RESPONSES_API解释；缺少方式的历史任务也固定为API。任务快照增加方式、强度及客户端版本；固定输入和业务Skill不改。执行、取消回调和保存前均核对任务原方式和配置版本，不读当前偏好重新分流。人工重试保留原方式。

## 调度与预留

使用现有单调度Worker、两个有界执行槽和独立Session。领取前在数据库短事务内按固定全局锁顺序检查并预留全局/本人/服务凭据预算，然后同事务将该行改为RUNNING。额度不足仍QUEUED，继续检查其他用户任务。API测试也先预留。

预留保存UUID、任务身份、所有者、受主密钥保护的凭据分组摘要及调度/进程归属；不保存明文Key。释放只在调用结束后。失去调度锁时停止领取，通知活动调用停止，并等待全部调用结束再恢复；无法证明已结束的调用持续占位，不按超时回收，不自动重发。恢复仅回收本机可证明原进程已退出的归属；其他归属保留人工核验。

## CLI启用门槛

检查真实exe版本与固定部署版本；禁止CMD/PowerShell包装器、任意参数和个人登录配置。CLI适配器以独立目录、最小子进程环境、stdin和固定provider传入完整文本；JSONL与stderr并行消费；独立取消监控、Windows进程归属控制。图片/PDF均未验证，明确拒绝。

当前系统级租户隔离、CLI自身无限等待和额外收费请求控制尚未通过验证时，运行状态为未验证；可保存配置，不能激活或领取CLI业务任务；固定文字连接测试按独立probe门槛开放。无手工开关绕过此门槛。模拟进程测试只证明适配层，不作为CLI/模型验收。


## 本轮验收与未完成项

- 已执行迁移43/44，真实库版本 `20261111_44`；三张新表的所有COMMENT逐项与模型相同，Alembic check无差异。旧任务JSON、API密文与业务Skill未批量改写。
- 最终AI/调度/需求对话/Skill/架构/注释专项54项通过（含真实PostgreSQL回滚和模拟Windows进程）；用例分析7项通过。摘要查询限制复测通过；约大输入的完整传输单项复测通过。日志见 `outputs/ai-cli-acceptance-tests.log`、`ai-cli-review-final.log`、`ai-cli-focused-final.log`、`ai-cli-large-input-test-fixed.log`。
- 前端213项请求/业务/UI测试、check及build通过。构建仍有原有大chunk提示。正式组件使用明确合成数据完成API/CLI切换、空CLI配置、不可用/禁用状态、长名称、未保存确认、设置分类切换保护、应用内空值提示、390px窄屏、下拉与Escape焦点/无横向溢出检查。五类报告页面新增的简短调用标签未逐页做登录后视觉验收。
- 全量后端342项曾运行；本次引入的问题与旧模拟配置契约已逐项修正并复测。剩余3项既有项目标识断言失败：`test_github_projects`的2项和`test_project_deletion`的1项预期重复请求409，而现有项目服务自动生成新identifier并返回201。项目服务与开工前备份逐字节相同，隔离复测仍失败，不把全量套件称为全绿；记录在 `outputs/ai-cli-existing-project-tests.log`。
- 总HTML原型与仓库副本分别基于自身原件追加双方式界面，未用旧副本覆盖总原型；原件在本任务本地备份目录。原型JS语法与现有验收脚本通过。
- 本地开发API与Worker已重载。live/ready及5173代理ready正常；未登录AI接口401，新配置/激活/测试路径已在实际OpenAPI。Worker仅一份持有原advisory lock，无占位调用；重载前确认无排队或运行中的真实分析。已登记现有真实exe路径，探测版本0.166.0，运行状态 `unverified` / `available=false`。
- 未调用真实模型、未使用公司资料验证CLI、未安装升级CLI、未推送远端或发布部署。真实CLI的系统隔离、无限等待/重试和额外调用控制、业务输入映射仍待验收；当前不得激活。保留此门槛符合用户选择的“未验证能力保持不可用”。

最终装载核验补充：已处理本机无进程、无socket、无事务的历史孤立Worker锁连接，新Worker日志明确进入 `analysis_chat_worker_ready` 且进程持续运行。单有数据库锁记录并不能证明新Worker装载成功。最后缺版本快照拒绝及CLI不可用原因投影修正后21项双方式专项再次通过，见 `outputs/ai-cli-mode-tests-final.log`。

## 固定文字CLI测试（2026-11-12）

测试接入、最多一次外部请求控制和安全边界详见AI_SERVICE.md的11月12日条目。用户已选择自己点击，不授权代理使用其保存的真实Key发模型请求。新增runtime只读字段probe_available；表单测试按钮按它启用，保存/激活仍按available判定。通过固定exe+本地假provider验证后允许测试，结果不保存配置、不切方式、不创建业务任务。没有新表、迁移、依赖或业务CLI启用。

证据：outputs/cli-probe-backend-tests-20261112.log（54项）、cli-probe-native-final-20261112.log（6项真实exe/假provider）、cli-probe-frontend-tests-20261112.log（213项）、cli-probe-frontend-check-20261112.log、cli-probe-frontend-build-20261112.log。原生CLI无单次网关时的异常工具回复实测会再请求，网关已在交CLI前拒绝工具响应且阻止追加请求；此结果不外推到业务CLI能力。
