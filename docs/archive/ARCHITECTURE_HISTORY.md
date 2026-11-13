# ARCHITECTURE 整理前记录

> 历史留档，不作现行规则。当前版本见[ARCHITECTURE.md](../ARCHITECTURE.md)。

# 系统架构与模块开发说明

2026-11-13：五类分析的校验失败候选可见及免费人工修订已接入。共同能力、权限/不可变审计、各模块完整校验及历史边界见[ANALYSIS_CANDIDATES.md](../ANALYSIS_CANDIDATES.md)。用例生成契约3逐条隔离问题，其他有效建议继续人工审核；其余报告保留全部可解析候选及关联，人工修订通过完整契约后再保存正式报告。原响应、旧成功报告及已应用用例不覆盖，不自动调用AI。


2026-11-12原生CLI正式开放：用户允许CLI原生多轮/内部重试/上下文压缩，并确认大输入用独立任务目录与受限只读工具。个人配置可保存并使用，ai_client分流及固定任务/权限/业务结果校验不变；integrations/codex_files为仅本次input.json的MCP stdio白名单读取/查找，无通用脚本/命令。小输入stdin、超90万字符完整文件读取，图片原生--image、PDF明确提示API；CLI保持原生等待/重试默认，不受测试网关约束。无新依赖/表/迁移，见AI_CODEX_CLI_IMPLEMENTATION.md现行章节。

2026-11-12CLI连接测试独立开放：runtime.probe_available与业务available分开，固定0.166.0的纯文字测试通过integrations/codex_probe本机单次网关，复用responses公共HTTP/错误能力；最多转发一次本人服务请求，真实Key留父进程、子进程只得本机短期令牌。测试不保存/激活或创建分析，业务CLI仍未验证禁用，无新表/迁移/依赖，见AI_SERVICE.md。

2026-11-11双AI方式接入：个人API配置保留，独立CLI配置/偏好/调用预算三表，五类分析、对话、Skill助手通过integrations/ai_client显式分流，responses仅HTTP协议；固定任务方式/版本，缺方式历史按API。现有单调度Worker内有界并发2/用户1/同服务Key1，PostgreSQL预留协调API测试，失锁后先处理活动调用再恢复。Windows CLI固定0.166.0，未完成系统隔离/无限等待/调用控制真实验收，保持不可用但可保存配置。接口、模型、部署与验证边界见AI_CODEX_CLI_IMPLEMENTATION.md、AI_SERVICE.md。

2026-11-10原型链接兼容：integrations/prototype_project复用受限字面量解析器，读取多端PROTO_PROJECT/PROTO_TREE及所选页面独立PROTO_ANNOTATIONS；prototype_link沿原只读采集链路兼容当前127.0.0.1:4173服务，保留安全嵌套路径、目录/批注快照与Markdown闭包。前端、共用AnalysisSelection及代码分析来源同步路径校验，项目鉴权不变，无新依赖/接口/表/迁移或AI调用，见PROTOTYPE_MATERIALS.md。

2026-11-09需求分析进入查询优化：requirements任务列表延迟加载完整context，只在SQL中提取原功能风险校正；累计清单延迟加载未使用的报告input。两条只读查询均联表读取作者名称，继续复用原项目鉴权、逻辑删除及共享报告删除权限。未向ORM写入裁剪快照，默认详情、固定输入、导出、重试及Worker保持原行为；无新接口、依赖、表或迁移。见REQUIREMENT_RISK_REPORTS.md。

2026-11-09分析输入合计门槛移除：代码分析新建前端/入队及sources.prepare默认不设16MiB输入预算；用例生成sources.prepare和用例分析service.prepare撤正文/附件合计字节拦截。保持原模块分层、完整单次输入、来源/哈希/权限、结果/配对导入与独立对话校验和公共AI协议，无新依赖/接口/字段/迁移/Worker，不触发收费调用或自动重试。需求及变更分析原本无此合计拦截，见CODE_ANALYSIS/CASE_GENERATION/CASE_ANALYSIS。

2026-10-27变更页面查询优化：change_analysis/presentation只组装SQLAlchemy只读JSONB投影，service复用项目鉴权/可见性并返回独立映射，router仅转发page_view参数。默认完整接口/导出和Worker行为保持；页面列表不读大型固定input，详情投影不进入ORM身份缓存或写服务。无新模块间依赖/表/迁移/依赖。见CHANGE_ANALYSIS.md。

2026-10-27变更原型证据定位兼容：纯evidence.normalize_coordinates扩展非CODE TEXT的同固定snapshot/unit内唯一完整逐字摘录定位，仅修segment_id并保存原/新位置审计。execution、service.revalidate和历史batch_execution仍共用原函数，后续全部contract.validate_report继续执行，直接导入不调用normalizer。无跨模块/HTTP/DB反向依赖，无新接口/表/迁移/依赖；复用原免费重校验恢复640。见CHANGE_ANALYSIS.md。

2026-10-26WebSocket候选已撤下：真实610以1013/no available account失败，客户端/调用参数/依赖及其测试均归档移出生产，五类仍共用responses._model_response → send_response/read_stream/output_text，timeout=None。保留历史安全传输诊断字段，共用HTTP/流内错误增加无可用上游账号分类及原UI文字提示；没有新客户端/协议分支/依赖/迁移/表/Worker。未自动重发，实际中转故障及权限边界见AI_WEBSOCKET_TRANSPORT.md/AI_RELAY_SUPPORT.md。

2026-10-26上游错误保留：integrations/response_errors仅依赖core配置、security既有主密钥及response_diagnostics，将受限错误体脱实际Key后加密原子落私有本地目录；无DB/业务/HTTP反向依赖，无公开读取路由。responses所有HTTP错误及SSE失败使用同一捕获，日志只安全ref/hash；诊断解析支持长JSON、有限封装及非JSON，失败存储不遮盖原HTTP错误。change_analysis/execution仅将safe_snapshot写metadata.ai_diagnostics，权限/取消/固定输入不变，无新表/迁移/依赖。详见AI_SERVICE最新错误诊断条目。

2026-10-26用例生成摘录匹配提示化：case_generation/compact在契约3内部证据中仅为未匹配摘录追加quote_verified=false与核对说明，不再因此拒绝报告；service复用原投影并添加可选quoteWarning，前端GenerationEvidence在既有依据布局区分AI待核对文字。来源/目标/权限/结构检查、旧v2严格规则和存储报告重新计算校验保持，历史成功报告不重写，不增加业务审核门槛。复用原免费revalidate保存1423的19条建议；Skill2.1.1、契约3，无新模块/依赖/表/迁移或收费调用。见CASE_GENERATION.md。

2026-10-26最新完整输入方向：service新建/retry标FULL_INPUT，execution不走batching.plan或comparison无差异短路，完整根input及全部原binaries直接复用共用responses分析。平台取消新任务语义筛选/目标剔除/多次复核及报告拼接；旧V1/V2模块只保留历史记录与已授权旧任务/免费校验兼容，旧start拒绝。重试新记录归档previous_batch_execution，不改原计划/Skill/结果，也不把旧人工处理套到新整体报告。前端保留历史details、撤继续分批入口，明示完整一次调用。Skill1.0.4/契约2，无新依赖/表/字段/迁移/Worker，见CHANGE_ANALYSIS_FULL_INPUT.md。

2026-10-26关联分批语义修正：change_analysis/batch_planning负责V2静态引用/类型/接口候选及完整路径分组，batch_merge按证据身份和已校验复核决定去重、保留冲突及原批结论；batching只dispatch新旧计划。batch_execution复用原Responses，对预列INTEGRATION附前置成功报告并严格验证内部reconciliations来源和原件交集；前置失败零调用，人工处理合并留别名/冲突审计。service新建BATCHED_V2、旧V1 start拒绝并在新retry重新准备，旧记录/Skill/结果不改。前端原区域显示阶段/依赖/未配对和实际次数。无新表/字段/迁移/依赖/Worker，详见CHANGE_ANALYSIS_BATCHES.md。

2026-10-23原型批注 Markdown：`integrations/prototype_link` 单向复用现有 markdown-it-py 和标准 HTMLParser，只解析静态链接，沿现有受限 GET 客户端读取当前原型目录内的 Markdown 引用闭包，去重／循环终止并将完整正文和 URL／字节哈希纳入固定证据。各分析仍复用 prototypes.link_pages 的读前／读后项目鉴权及原模型通道；业务只同步读取说明，生成依据保留 Markdown 数量。预览 iframe 仅追加新标签和浏览器下载权限，两份总原型同步，无新接口、模块、依赖、数据库字段或迁移。详见 PROTOTYPE_MATERIALS.md。

2026-10-22变更分批：change_analysis/batching为纯固定子输入/报告合并；batch_execution复用responses、现有候选私有存储、权限与原Worker。service/router新增原任务start动作，原retry复制成功成果仅重排未完成，revalidate支持原批候选免费校验。原metadata保存计划、原批结果和安全尝试，JSONB增量合并避免重传固定资料；控制检查通过load_only加载状态列。迁移42仅扩PREPARED状态/中文注释，无新表/字段/依赖/Worker。前端原布局内增加可展开计划、开始次数和失败重试，详见CHANGE_ANALYSIS_BATCHES.md。

2026-10-22变更392实际HTTP400后的兼容修正仍只在共享协议层：response_input将超长user正文在同一消息内顺序拆为多个input_text，每片100万字符且全部保留，JSON引用展开/原始输入、Skill及附件顺序保持；response_diagnostics识别嵌套error/detail与422校验条目，区分字符串/请求长度和模型上下文。responses日志增加安全诊断快照，即使业务未持久化diagnostics也保留错误指纹/请求与片段大小；frontend/aiErrors增加共同长度提示，不改请求层/页面布局。无模块私有客户端、依赖、接口、表/迁移或真实模型重发；开发规则及事实边界见AI_SERVICE/CODE_STANDARDS和SESSION_CONTEXT。

2026-10-22模型调用公共链路：五类业务分析/独立对话/Skill助手经`integrations/responses.analyze|converse → _model_response → send_response/read_stream/output_text`统一组装协议、完整响应及安全错误；模型等待显式None，不加600秒socket或总任务时限。`integrations/response_input`仅对用户消息内有效JSON重复长正文无损引用，保留双侧身份、原文和行号，原输入/Skill不变，不触碰developer规则或附件；安全诊断加复用数/节省字节和null超时。业务权限、候选保存/输出契约仍各模块负责，客户端不依赖业务/DB。模型列表/连接测试、来源读取和浏览器HTTP保留有限超时；边界见AI_SERVICE及CODE_STANDARDS，不把上游504说成已解决。

2026-10-22生成标题兼容：case_generation/contract.normalize_ai_report仅在AI通道启用compact.normalize的缺标题恢复；NEW漏title时原样沿用已有description并追加待核对说明，既有严格validate仍要求必需字段并验证来源/目标/摘录，直接导入不启用新补齐。复用execution的格式修正审计和免费revalidate，恢复1371的105条待审阅建议，不写用例库。无依赖、接口、表/迁移、前端或Skill快照变化；单向依赖及调用职责保持，见CASE_GENERATION.md。

2026-10-22人工重试快速失败的兼容调整：skills/files.model_context仅处理固定指令快照，case_generation/execution装配主指令/契约与十份developer规则消息；integrations/responses增加可选协议消息，默认四类调用不变。response_diagnostics持久化安全请求尺寸/配置及哈希，SSE错误日志受控无原文。无HTTP/DB反向依赖、接口/表/迁移/依赖或前端变动；保留Skill2.1.0、契约3和完整资料单次调用，无收费重试，尚未证明长流失败已修复。见CASE_GENERATION.md最新条目。

2026-10-22用例生成Skill2.1.0多文件规则：skills/files在原固定五包目录内验证可选resources.json并按序拼接主文件、十份参考Markdown和契约；新任务固定文件路径/全文/原字节哈希及指令哈希，旧任务和其他无清单包保持。共享文件层不依赖HTTP、DB或业务模块；编辑辅助复用文件usage默认携带运行规则，前端复用原文件树/主题勾选及公共HTTP，仅增加用途说明和上下文逐行样式。契约3/单次本人AI/Worker/人工确认直接入库保持，无新模块、接口、表、迁移或依赖。参见CASE_GENERATION.md和SKILL_MANAGEMENT.md。

2026-10-21用例生成连续审阅正式接入：CaseGeneration负责记录/筛选/20条分页、按需侧栏及既有请求装配；GenerationTable只呈现分组用例和触发回调，generationPage共用分组与页大小；GenerationBatchReview复用原预览校验、CaseDialog/Form/FormSelect，实现数量确认及独立重复处理。最终提交继续既有apply-preview/applications及公共HTTP，原GenerationDetail稳定实例和历史应用查看保持。无后端模块/依赖/接口/表/迁移/Skill变动，见CASE_GENERATION.md。

2026-10-20用户要求AI服务支持其他中转并修复模型名称／推理强度错位。已撤ConnectionInput的三地址白名单，保存／测试／模型目录共用HTTPS格式校验；显式非公网IP／localhost和点路径仍拒绝，重定向及代理保持禁用。旧allowed_base_urls响应仅兼容保留，不控制准入。前端说明及两份总原型同步，AI表单字段align-content:start防止网格拉伸导致控件错位。无依赖／数据库变化。后端协议3项通过、4项数据库用例未启用，架构检查通过；未调用真实AI、保存配置或重启服务；浏览器视觉尚未验证。详见AI_SERVICE.md。

2026-10-20目录HTML预览修复：原browser路由继续鉴权，directories固定当前请求版本的文件索引并经file_path核对哈希，纯转换器prototypes/html_preview只解析静态相对引用，将CSS／JS／图片编码为data资源，CSS引入按引用文件路径递归并终止循环。CSP仅追加data脚本／样式，sandbox继续不授予allow-same-origin，网络仍默认禁止；无资源托管接口、外部读取、新依赖或迁移。转换只作用于预览响应，下载及各分析明确所选原件保持，见LOCAL_PROTOTYPE_DIRECTORIES.md。

2026-10-19本地原型目录：prototypes/directories复用documents项目权限、资料库revision与私有存储，新增DIRECTORY来源和DocumentVersion.directory_files固定索引（迁移41），无新表或依赖。浏览器File Blob按未压缩TAR封装上传；后端不按用户路径解压，完整校验后才原子发布版本。各分析单向复用目录读取器，原型变更新增DIRECTORY_PROTOTYPE；CodeFileTree提取为公共文件树，原导出兼容。详见[LOCAL_PROTOTYPE_DIRECTORIES.md](../LOCAL_PROTOTYPE_DIRECTORIES.md)。

2026-10-19单条生成审核确认叠层仅改前端：GenerationDetail稳定key保留实例，以显式保存刷新信号同步修订版本并保护未保存编辑；GenerationSingleReview作为独立主题dialog位于其上方，关闭仅恢复下层交互和焦点。公共CaseDialog和后端协议保持，无新模块、依赖或数据变更，见CASE_GENERATION.md。

2026-10-19普通用户创建项目复用原POST /api/projects及projects/service.create_project，只放开有效Actor创建且非ADMIN的owner_id必须为本人；不开放people目录前置权限或修改负责人规则。前端App的两处入口和ProjectForm共用原主题/公共HTTP，新建非管理员显示本人且提交本人ID。无新模块、API、表、迁移或依赖，见GITHUB_PROJECTS.md。

2026-10-19单条生成审核前端复用原保存／预览／同步应用接口：CaseGeneration按详情返回来源选择GenerationSingleReview小确认，批量仍GenerationReview，均复用原版本／重复规则。GenerationDetail单条撤额外核对勾选，由审核动作写原人工确认字段，普通草稿不自动算审核；字段错误使用本组件的精确缺失／当前版本比较及共用主题样式显示。没有新增后端模块、接口、数据结构或依赖，原型与当前约定见CASE_GENERATION.md。

2026-10-19生成用例人工确认改为同步直接入库：case_generation/router原applications POST转apply.submit并返回200，服务在当前请求内复用原逐条权限／版本／重复检查和独立提交，旧application表只保留请求幂等、结果及中断审计；新记录不进入Worker队列，前一条未完结不拦其他候选。原execute仅兼容历史排队记录，新提交状态FAILED标记未完成、COMPLETED标记完结；Worker不会领取或重放。迁移40仅修改原表默认值及真实中文注释，不加表／字段。投影增加requestId供前端准确定位本次结果，现有确认／结果布局及公共HTTP不变；仅该入库请求等待600秒。AI生成／对话和用例分析模块后台任务保持，见CASE_GENERATION.md最新约定。


2026-10-19 GitHub原型读取`change_analysis/sources.prototype_git`复用原`github_text`与`artifacts`的项目／仓库／Git blob隔离私有缓存，网络仍是integrations/github固定GET白名单，缓存不能代替固定树或读前读后授权。用例生成prepare在远端读取结束后重新获取项目锁并复查请求UUID幂等；compact校验仅允许同文件连续字符区间的精确跨段摘录。前端generationApi仅准备请求延长至600秒并保留取消，复用GitHub／分析错误字典展示明确失败原因；公共HTTP默认等待和AI调用方式不变。无新模块、依赖、接口、表／迁移或Skill变动，见CASE_GENERATION.md。

2026-10-16共用Responses的HTTP400／422分类复用integrations/response_diagnostics安全元数据：上下文／输出配置／模型／参数明确区分，未知请求拒绝不再自动归因个人配置。新增固定参数名白名单及safe_snapshot投影，日志只含受控类别／码／参数和请求大小；无HTTP／DB／业务层逆向依赖、表或依赖变化。前端aiErrors增三项共21项，AIService／skillApi也以此作为专用上下文提示后备，五类分析原复用链保持；不改权限、输入容量约定或自动收费重试。验证及运行见SESSION_CONTEXT最新条目。

2026-10-16账号新增TEST测试、DEV开发、PRODUCT产品、MANAGER经理，复用原accounts/auth及platform_role字段；角色配置仍仅管理员可改。新角色统一走非ADMIN已有权限分支，不增加权限矩阵或管理服务；项目负责人由owner_id独立决定。前端accountRoles共用标签和类型，Select继续使用主题控件；迁移39仅扩约束、默认值及真实中文注释，旧USER不改写。见[LOGIN_ACCOUNTS.md](../LOGIN_ACCOUNTS.md)。

2026-10-16五类分析及其对话统一通用AI错误说明：frontend/src/aiErrors.ts维护同一组18个安全错误码的中文提示，codeAnalysisApi、chatApi、riskApi组装时复用；变更／生成／用例分析沿用现有codeError／codeErrors依赖取得同一说明。需求已保存任务风险契约详细路径仍优先显示，各模块业务错误和公共HTTP未知结果／401语义保持。此为前端纯文案复用，不新增请求层／后端服务／任务模型或依赖；后台五类执行原本共用integrations/responses和app.chat_worker，Skill、输入输出契约、固定资料与业务处理仍归各模块。验证见SESSION_CONTEXT最新条目。

2026-10-16分析删除入口移至四类页面左侧记录项的独立图标（需求表入口保持）。现有代码／变更／生成列表只追加已查询的发起人标量，前端据本人和项目管理资格提示入口，点击仍复用原删除预览与服务端权限校验；没有新请求层、路由、模型或依赖。见[分析记录删除](../ANALYSIS_RECORD_DELETION_DESIGN.md)。

2026-10-16项目逻辑删除已按用户确认接入：管理员/负责人可操作，活动分析/对话/批次/入库阻断，统一项目访问及全部项目汇总排除已删除项目，保留关联数据和历史。迁移38、接口、原型和验证见[PROJECT_DELETION.md](../PROJECT_DELETION.md)。

2026-10-16：五类分析记录删除复用 modules/projects/record_deletion 的项目权限、关联活动检查、行锁及删除审计，各业务 router 只转发，原 own/view 与标量列表／统计／新来源基准保持显式删除边界。六张现有分析表增加 deleted_at/deleted_by（迁移 20261016_37），保留原始输入、报告、对话、应用和重试关联；公共前端 AnalysisRecordDelete 复用 api/http、CaseDialog，删除成功通过模块工作区重新挂载取消旧请求和清理详情／对话／分页。无新业务表、依赖、AI 调用或 Git 写入。 删除权限为本人发起／导入者、项目负责人或管理员；共享需求报告涉及多个创建者时仅负责人／管理员可统一删除。排队／执行中的分析、对话及应用须先取消或等待，未开始的 PREPARED 可删除；本期无批量清空／恢复入口，逻辑删除不释放存储。见 [分析记录删除](../ANALYSIS_RECORD_DELETION_DESIGN.md)。

2026-10-15文本误拦修复新增security/source_content纯文本规则（仅标准库re，无HTTP/DB/业务依赖），代码/变更的来源准备及契约单向复用；仅兼容明确的PEM标记字面量空串清洗，其他私钥标记仍拒绝并独立错误码。读取后、固定输入及严格导入使用一致判断，不改正文/哈希/证据结构或Skill契约，无新表/依赖/模块路由，详见CHANGE_ANALYSIS.md。

2026-10-15用户要求AI结果验收支持全部项目和不同项目汇总，专属指标全部展开并允许重新设计UI。正式/ai-acceptance默认全部项目，页面独立范围下拉可选单项目，不随左上角工作项目变化；单项目进入分析时切换对应工作项目。新增管理员GET /api/analysis-acceptance（project_id=null），复用五类SQL标量投影和原计数，按分子分母累计而非平均比例；原项目汇总及单记录权限保持。范围栏／四张总量卡／五模块卡同步两份总原型，通用和专属指标始终展开，概览继续无验收区，无二次确认／新表／迁移／依赖／AI／Worker。见docs/AI_ACCEPTANCE.md及SESSION_CONTEXT最新条目。

2026-10-15用户要求AI结果验收改为管理员独立菜单页，已接`/ai-acceptance`（配置与管理），按当前项目汇总并包含用例采纳率。项目概览撤验收区域／采纳率卡并恢复四卡，overview GET不再返回采纳总量；新页菜单／直达路由／汇总GET及service均限制平台管理员。各分析记录内处理和指标仍按原项目权限，不增加二次确认。见AI_ACCEPTANCE.md及SESSION_CONTEXT最新条目。

2026-10-15用户进一步选择完整单次提交，变更分析撤合计输入/请求/配对导入/对话固定字节门槛；共用code_analysis.prepare新增仅内部调用的input_limit关键字（默认保持原代码分析限额），变更上下文显式None。模型输入仍完整、一次调用，结构/权限/单文件校验和AI输出校验保持；不猜服务容量，不自动分批或收费重发。两份原型仅同步变更范围说明/配对导入限额，布局/其他模块保持。

2026-10-15变更代码读取优化：integrations/github保持固定GET/域名/无重定向白名单，对瞬时只读连接与指定5xx有限重试，不重发AI。change_analysis/sources仍拥有项目/来源授权、双固定树和全文准备，artifacts原子保存项目＋仓库＋Git blob哈希隔离的私有已读正文；缓存完整性校验复用integrations/github.blob_sha，无数据库/HTTP下载入口。旧侧全量、新侧复用相同blob并读差异，保存及模型输入仍为带明确旧新侧别/文件分类的完整双侧快照。根skill/change-impact升级1.0.1、契约2结构不变；历史固定Skill/输入不改写。未增加业务模块/依赖/表/Worker或Git写操作，详见CHANGE_ANALYSIS.md。

2026-10-15用户反馈二次确认繁琐，已撤独立“逐条验收”：现有详情确认／处理／实际入库是唯一逐条操作，记录及概览自动统计。口径改为人工处理进度／人工认可率，忽略／不适用单列已处理且不当误报；遗漏与基准仅按需补充，不要求另填报告结论。此决定替代此前独立验收入口和原稿有效率描述，详见AI_ACCEPTANCE.md及SESSION_CONTEXT最新条目。

2026-10-15用户授权AI结果人工验收：项目概览增加独立五模块汇总区，各分析按原分析记录提供验收进度、有效率、依据充分率、人工关键遗漏／基准及适用专属指标；独立人工结论不映射旧处理状态，不改原报告或自动调用AI。新模块、迁移36、原型和完整口径见[AI_ACCEPTANCE.md](../AI_ACCEPTANCE.md)，验证以SESSION_CONTEXT最新条目为准。

2026-10-15项目概览新增用例采纳率：case_generation/overview在既有JSONB摘要查询中只追加NEW/UPDATE候选key投影，与已保存最新处理状态计算各记录计数；overview/service在近期筛选/截8条之前汇总全项目，并通过原GET counts.generation_candidates/generation_adopted输出。前端overviewApi校验整数/可用性/分子不超过分母，ProjectOverview复用统计卡增加第五卡；单向依赖、权限和只读白名单保持，无新表/迁移/依赖/Worker或AI。

2026-10-14项目概览正式开发：`modules/overview`单向组合五个业务模块公开只读摘要，项目标量工具位于`projects/analysis_summary.py`；router仅转协议，无新表/迁移/Worker或依赖。JSONB投影仅身份/状态/必要完成字段，概览最多8条/选择器每页20条。前端独立ProjectOverview/overviewApi/OverviewEntry，App装配并对五模块传入已校验定位；生成原摘要支持run_id，均复用原权限及公共HTTP。保持最新原型等宽/非零红色及四页签，不恢复独立任务中心，详见PROJECT_OVERVIEW.md。

2026-10-14用户移除项目设置“模块绑定”：正式ProjectSettings仅保留基本信息/GitHub仓库/本地代码/成员与权限；原型绑定表单/保存动作及配置绑定入口同步撤除。无后端接口/数据库变化，已有分析资料绑定、Skill文件及历史快照保留，详见GITHUB_PROJECTS.md。

2026-10-14用户移除平台设置「原型数据」：正式Platform删除demo分类及仅服务占位的后备内容，总HTML/审阅副本删除对应分类、配置导出及演示重置动作；保留已有浏览器项目/配置及模块数据。平台设置现仅AI服务、GitHub连接、账号管理，无独立后端或业务表需要撤除；原型资料模块及原型页面批注采集不受影响。

2026-10-14 Skill管理读取优化：浏览API使用白名单/文件标识校验＋最长5秒的进程内内容缓存，固定五包、每包缓存上限8MiB；批量contents与known_token未变响应减少网络传输。前端用户工作区内存复用文件包/预览、切换直接显示并后台核对，不写localStorage。默认目录校验、保存、AI入队及五类分析快照仍直接读最新文件；无新依赖/表/后台任务。详见[SKILL_MANAGEMENT.md](../SKILL_MANAGEMENT.md)。

2026-10-14 Skill管理正式接入：用户选择本地文件直接读取/管理员保存写回，已新增modules/skills文件白名单、跨进程锁/冲突/备份原子替换及权限服务，五类分析单向复用files.snapshot；需求入队固定Skill/重试原快照，旧缺快照不补造。管理员本人AI辅助修改使用既有app.chat_worker，迁移35仅SkillChatTurn及真实中文注释，正文不走数据库覆盖。前端Skills/skillApi/skills.css接/skills及原型三栏/左对齐/对话/对照/人工保存，复用公共请求和主题组件。详见[SKILL_MANAGEMENT.md](../SKILL_MANAGEMENT.md)，替代下方仅设计/原型和数据库正文修订建议，无新Worker/依赖或通用Agent。

2026-10-14项目概览仅原型：用户在方案后授权「改下原型」，总HTML及仓库副本新增本地摘要/有限近期记录及回原模块的筛选定位，未建立正式overview模块/API/表或依赖。真实统计/权限/深链接仍按PROJECT_OVERVIEW_DESIGN.md后续授权实施；原型交互及验证见PROJECT_OVERVIEW_PROTOTYPE.md，不恢复独立任务中心。

2026-10-14 Skill管理AI辅助修改仅原型：沿用docs/prototypes/片段与两份总HTML，浏览器S.skillAssistant按体验管理员/Skill保存合成对话，建议先对照再应用草稿，另行保存演示修订；文件树左对齐。无正式模块/接口/数据库/Worker或真实模型调用，既有根目录Skill原文及历史指令不改；见[SKILL_MANAGEMENT_PROTOTYPE.md](../SKILL_MANAGEMENT_PROTOTYPE.md)。

2026-10-14后续Skill管理原型：外总HTML及仓库副本嵌入五类固定37份文本快照、文件树/内容/管理员正文演示修订，说明见[SKILL_MANAGEMENT_PROTOTYPE.md](../SKILL_MANAGEMENT_PROTOTYPE.md)。片段在docs/prototypes/，不新增正式modules/skills、依赖、接口或表；Skill功能文件仍在根目录skill/，原文未改。浏览器演示状态不作为真实权限或任务快照实现。

2026-10-14用户移除独立“任务与报告”功能：正式导航及/tasks占位路由、项目概览“全部任务”和通向该页的“结果确认”步骤、总原型及审阅副本对应入口已撤除。旧正式地址沿用“页面不存在”。各分析模块的后台任务、记录、固定输入、报告、人工处理、导出和审计仍归原模块，无独立任务中心后端或业务表需要删除；本次不新增跨模块汇总或报告功能。

2026-10-14用户移除模板管理：正式导航及/templates占位路由、模板关联提示和原型编辑/绑定/发布入口已撤除。无独立后端/表或迁移；历史任务固定指令及输出约定保留，不影响项目内分析Skill、契约及14列用例。Skill管理仍按独立设计阶段推进，不恢复模板绑定入口。

2026-10-14 Skill管理仅设计：用户明确先设计方案、只展示内容且仅管理员可修改，见[SKILL_MANAGEMENT_DESIGN.md](../SKILL_MANAGEMENT_DESIGN.md)。建议固定五类入口、正文修订及页面/分析共用快照加载；根目录skill/继续维护底版和只读契约。此方向替代早期平台完全只读限制，具体修订存储和modules/skills接入待审阅；本轮未新增模块、依赖、接口或表，也未修改原型/Skill原文/Worker。后续须补齐需求任务完整指令冻结和代码分析版本标签差异，不能把本方案写成现有实现。

2026-10-14用例分析中文说明：Skill1.0.1/契约1仅新准备固定指令/版本/哈希；caseAnalysisApi将已知平台字段词及字段标签投影为中文，页面/Markdown复用，不改变原报告/引用原文或内部定位键。现有JSON契约、表结构、Worker及人工应用保持，无迁移/依赖/额外AI请求，详见CASE_ANALYSIS.md。

2026-10-14用例分析正式接入：新增modules/case_analysis的router/schemas/service/contract/execution/apply，拥有独立run/chat/application三模型与Skill1.0.0/CASE_REVIEW契约1；资料采集单向复用case_generation/sources，用例写入复用cases公共事务，Worker注册已有app.chat_worker，无新Worker/依赖/通用Agent。人工草案审核逐条失败继续/成功防重放、原报告不变；CASE_REVIEW source_kind追溯设计/审核来源，前端CaseAnalysis独立状态/API/对话，共用主题、公共请求、GitHub范围与文字XLSX能力。迁移34三表带中文真实注释，详见CASE_ANALYSIS.md。

2026-10-13用例逐条需求证据摘要：case_generation/compact为现有契约3增加兼容可选evidence_quotes，核对本条来源、需求/原型资料类型和固定原文存在性后映射已有evidence；service投影已核对摘录标记，generationApi校验后由共用GenerationEvidence显示短原文。Skill2.0.4要求新文字用例带逐条原文摘录，旧报告缺摘录明确提示，不从用例设计字段伪造证据，无新表/迁移/依赖/额外AI请求。详见CASE_GENERATION.md。

2026-10-13简化批量审核正式接入：GenerationReview复用CaseDialog/FormSelect及GenerationDetail批量返回模式，GenerationWorkspace装配现有预览、草稿保存与申请提交，临时分类最终随请求固定。case_generation/schemas校验分类意图，apply负责项目分类核对、固定条目及逐条事务/失败审计，复用分支仍不移动分类，旧幂等请求兼容。申请状态使用已有摘要/详情轮询；无新模型/表/迁移/依赖或跨层调用。详见CASE_GENERATION.md。

2026-10-13用例生成读取优化：原列表GET增加可选summary模式，router仅转发，case_generation/service按项目权限查询标量摘要及批次/应用刷新标识，不读历史正文/重试输入；原完整详情、列表默认模式和导出数据保留。前端generationApi校验摘要/详情身份，GenerationRemote按摘要选择并刷新当前详情、隔离账号/项目内存缓存，维护基准/组合导出按需读取完整记录。无新表、依赖或跨层调用，详见CASE_GENERATION.md。

2026-10-12用户确认并要求实施简化用例生成：Skill2.0.0/契约3，完整所选正文及对应批注直接发送，页面/说明段保持完整，不按1600字符/8行重新切分、不前置提取业务格式、不自动分批。模型仅返回cases/notes/complete，12设计字段服务既有14列，notes仅业务待确认/执行准备/未完成；无规则树、场景树、逐段coverage。平台生成候选key和当前目标差异补丁，校验字段/真实来源/项目/版本；来源为资料级引用，不伪造逐段摘录或语义覆盖。完整原始响应保留，纯JSON围栏与设计字段字符串数组可无损兼容并审计。v3结果保存在原有JSONB记录，旧v2输入/指令/报告保留并按legacy_contract校验，contract为单向分发入口、compact为新格式及原文请求装配。静态未执行脚本与业务范围完成分别表达，complete为AI声明/人工待核对。导入及澄清/对话/逐条人工应用沿用既有授权；澄清补生成明确创建新的v3任务，清除父导入export字段且不改父记录。当前/旧任务不自动重跑，不自动收费。无新表/字段/迁移/依赖；不能把80条合成保存验证冒充模型实际生成80条。


2026-10-12最新：用例生成Skill2.0.0/输出契约3在原case_generation模块内提供简化解析、来源/真实目标验证和平台建议映射；模型请求按资料/页面标题带完整正文及批注，不让AI解读存储片段或返回规则树/场景树/coverage。旧v2校验与历史读取隔离保留，不静默迁移旧报告；平台生成key/补丁/审核元数据。执行继续单次本人AI、既有app.chat_worker和人工逐条应用，未增加前置识别/自动分批、依赖或跨层调用。详见[CASE_GENERATION.md](../CASE_GENERATION.md)与[新契约](../../skill/case-generation/contract.md)。

2026-10-12用户确认用例生成门槛调整：Skill1.1.0/契约2兼容新增DESIGN_READY_SETUP_PENDING场景状态；业务条件/动作/预期明确即可NEW/UPDATE待审阅建议，缺账号/数据/权限/观察入口关联EXECUTION_SETUP并写入data_requirements/remark和场景note，NEEDS_REVIEW要求人工核对。缺业务决定仍PENDING_DECISION、错证据/引用仍拦截；未完成分析不能冒充业务缺失。执行准备可与已生成用例并存，不宣称可直接执行/已测，准备缺口存在不能COMPLETE。Skill加强完整功能适用分支覆盖及具体遗漏说明。页面分别展示业务待澄清、准备待补和未覆盖原因/下一步，PARTIAL显示部分完成。旧Skill/固定输入/报告不改写、不自动补生成；保留14列、人工审核及逐条应用。无新增表/字段/迁移/依赖。


2026-10-12原型页面批注采集修复：用户明确要求所选页面批注与页面一起传AI。真实站annotations.js采用初始JSON对象后逐页赋值、常量字符串、固定数组追加/别名以及pages.push；旧读取器仅读初始对象，漏了后续批注和新增目录。新增integrations/prototype_data仅解析受限数据字面量及两种明确固定列表模式，不执行JS/任意函数/模板插值或请求；不支持语法明确报错，避免静默漏批注。每页HTML与对应/公共批注同次固定，重复标题合并保留，批注位置显式标注，快照哈希包含批注。生成binding保留所选文件和批注块数，read_note显示数量；各分析复用同一原型采集器。任务88历史正文/输入保持，不自动用新批注替换重试固定依据。


2026-10-12用例生成AI格式兼容修复：模型完整响应先原样保存；AI执行和免费重校验仅将rules.branches.conditions/scenarios.conditions的字符串原样包装为单项数组，不拆分或改文字。随后仍执行全量结构、证据、引用、固定范围和覆盖校验；通过后保存待审阅报告，在attempt记录修正字段路径、时间及原始/规范化哈希，并在页面依据提示修正数量。配对导入仍严格，不放宽业务/证据错误，不自动审核或写正式用例库。Skill1.0.2/契约2明确两处数组要求，历史输入/指令不改写，任务88已有人工修复成果不重跑。


2026-10-12记录读取修正：用户反馈刚才生成记录不可见，实查任务88仍在项目5/FAILED、列表包含88和77且实际前端解析均通过，未丢失/删除。列表接口日志15–45秒，首次读取期间曾误显示暂无记录。页面改为明确读取loading/读取失败提示，只有成功读取后展示空列表；后端projection复用本次批次查询和批量资料版本查询，消除同记录重复SQL，保留完整报告/配对导出/原件。实查两条记录9次SQL约9.83秒，仅单次测量不承诺固定延迟；未读取/外发正文到AI、重试或修改业务记录。前端84项/check/build、后端准备/生成/导入真实事务专项1项及架构/Ruff通过；未浏览器实点。更新API前队列0，只更新本地API，Worker及失败任务保持。


2026-10-12：用例生成增加执行loading、真实开始时间/阶段/耗时/接收字节和输出字符数，后台领取时同事务将主记录更新RUNNING，3秒轮询/1秒计时且无虚构百分比。安全诊断复用integrations.response_diagnostics白名单，保存在现有attempts JSONB中，每次请求独立、约5秒进度采样并在失败/完成时保存最终诊断；仅已知分类/代码、受控请求ID、数值和事件计数，无密钥/资料/上游原文。失败页面直接展示原因及可展开诊断。历史未保存的诊断不补造，任务88不自动重试。迁移33仅同步attempts真实中文注释，未新增字段/表/依赖。总原型及副本同步loading演示。


2026-10-12最新确认：新建生成采用完整资料一次调用本人AI，不自动分批、不增加前置AI规则识别。正文片段仅用于证据定位；原功能范围、资料、旧新配对及所选用例全部保留。准备后展示文本token粗估（ASCII约4字符/token，非ASCII约1字符/token，含固定Skill和JSON）；达到32,000为提示阈值，非模型硬限制。模型容量目前无可信配置，不猜测模型上限；附件用量单独提示、未计入文本估算。用户可继续开始或缩小范围重新准备，保留原准备记录，未开始不收费。平台已有16MiB输入/附件校验上限继续生效。移除分批规则确认，失败人工重试，成功成果/历史分批记录保持；截断响应不标完成，不把不完整片段当合法候选。


2026-10-12原型链接目录修复：integrations/prototype_link 同时解析通用 PROTOTYPE_PAGES/PROTOTYPE_ANNOTATIONS 与旧 XETA 目录，统一输出页面和说明，不执行脚本。PrototypeLinkPages 和 requirements/risk_schemas、code_analysis/sources 同步命名 HTML 文件校验；各分析继续复用 prototypes 的项目鉴权、外部请求前释放事务及返回后复核。未新增模块/依赖/数据库或扩大主机白名单。


2026-10-12用例生成正式接入：新增modules/case_generation的router/schemas/service/sources/contract/execution/apply/imports/chat；单向复用既有资料/原型、cases公共事务能力及个人AI。app.chat_worker每轮领取一个固定生成批、一个应用条目或独立对话；不加独立Worker/Redis/Agent。迁移31新增run/batch/application/chat_turn/lifecycle_history五表及managed_case生命周期，迁移32同步实际来源注释。候选及应用条目/处理审计以有结构JSONB保存，逐条独立事务。前端CaseGeneration/generationApi撤App内存记录、接项目轮询与正式操作；公共HTTP和主题原型布局保持。详情见[CASE_GENERATION.md](../CASE_GENERATION.md)。

2026-10-12用例生成Skill设计：项目内`skill/case-generation/`0.1.0-draft含候选契约2、合成双JSON和行为规格，见[CASE_GENERATION_SKILL_DESIGN.md](../CASE_GENERATION_SKILL_DESIGN.md)。仅设计文件，不改模块/依赖/数据库/Worker或原型；正式/generate仍v1展示预览，不直接导入v2或视为AI接入。

2026-10-10变更分析正式接入：integrations/github固定读取按需带路径存在性、原型比较可读空清单；普通读取/保存默认行为及白名单不变。modules/change_analysis独立router/schemas/service及sources/contract/comparison/evidence/execution/chat/export/artifacts，单向复用既有公开只读来源、用例、项目及本人AI。app.chat_worker增加变更分析/对话领取与恢复，仍单执行进程；迁移30新增任务/对话表及真实中文注释。前端App移除变更内存保存，ChangeAnalysis/New/Import/Context/Chat与changeAnalysisApi接项目记录、后台状态、处理/导出及独立对话；公共HTTP、主题控件与已确认三栏不变。细节见[CHANGE_ANALYSIS.md](../CHANGE_ANALYSIS.md)。

2026-10-10变更分析Skill设计：项目内新增`skill/change-impact/`指令、候选契约2、合成双JSON和验收规格，见[CHANGE_ANALYSIS_SKILL_DESIGN.md](../CHANGE_ANALYSIS_SKILL_DESIGN.md)。仅设计文件，未改变模块依赖/数据库/Worker；正式页面v1预览和内存暂存边界保持，不能把草案存在视为AI接入。

2026-10-10用例生成先接页面：App装配CaseGeneration按账号/项目在React内存暂存，CaseGenerationNew/Dialogs承接范围/草稿/澄清及预览；generationPage负责本页展示形状/证据/版本比较，generationRead复用cases/edit-scope只读快照，generationExport输出字面文字XLSX/报告。资料复用既有GET options/原型库/versions、只读prototypes/scope和页面树，经api/http保留取消/超时/401/响应校验。无生成后端/表/迁移/AI/Skill/Worker，不调用用例写接口；详情见[CASE_GENERATION.md](../CASE_GENERATION.md)。

2026-10-08 Git版本只读选择：projects/router的GET repositories/{id}/versions仅转service；service负责项目/本人连接/仓库授权、释放事务及返回后复核，调用integrations/github固定branches/tags/commits读取白名单。前端GitVersionPicker共享用于变更代码/原型，走api/http并校验项目/仓库/种类/页/ref；选择后固定SHA。不新增业务表、任意URL/Git命令或写权限，见CHANGE_ANALYSIS.md。

2026-10-08：变更分析先实现前端页面，不接AI/Skill或新建后端。App装配ChangeAnalysis并在容器按账号/项目暂存；ChangeAnalysisNew复用现有代码分析GET来源/双侧文件树、CodeFileTree及浏览器本地快照。changeAnalysisPage仅负责显示形状/预览门槛/导出，不是生产契约；所有网络继续通过共享HTTP，无变更写接口/业务表/Worker修改。状态和限制见[CHANGE_ANALYSIS.md](../CHANGE_ANALYSIS.md)。

2026-09-24：需求分析AI输出的结构、项目和引用编号仍强校验；`risk_schemas.validate_report(..., review_warnings=[])`将证据/覆盖等语义差异转为待人工核对提示，严格双JSON导入仍用原校验。Worker及无AI候选重校验把警示保留在任务context；`risk_service`经项目鉴权关联报告并将警示用于详情、累计清单和导出，需求对话固定上下文也带警示。迁移29更新真实中文注释，不新增字段或改变历史报告。见[REQUIREMENT_RISK_REPORTS.md](../REQUIREMENT_RISK_REPORTS.md)。

2026-09-24：`requirements/risk_schemas.normalize_comparison_text`仅在AI候选解析前把有效字符串列表按顺序合并为文本，供自动执行和无AI手动重校验共用；严格双JSON导入不走该步骤。原候选不可变，校正元数据存于任务context，其他证据/覆盖验证继续阻断不可信结果。详见[REQUIREMENT_RISK_REPORTS.md](../REQUIREMENT_RISK_REPORTS.md)。

2026-09-24：需求分析重试优先使用旧任务链上已保存的固定`input/bindings`，Worker重新写入本次request_id/revision并经`risk_analysis_service.frozen_materials`复核项目来源、资料版本与二进制哈希；无快照才走实时`prepare`。重新分析仍由重试者本人AI配置执行，不从已失效的原型站重复获取已固定页面，也不免除权限/完整报告校验。见[REQUIREMENT_RISK_REPORTS.md](../REQUIREMENT_RISK_REPORTS.md)。

2026-09-23：需求分析AI完整响应由`requirements/artifacts.py`先原子保存至私有候选目录；`risk_schemas.normalize_function_risks`只从风险的功能归属重建重复索引，原候选不改，再执行原有v3全契约校验。`risk_analysis_service`按项目权限提供候选下载与原发起人手动重新校验（同任务、不调用AI），失败结果不伪装成正式报告。`requirements/router.py`仅做协议转发；无新增表或依赖。详见[REQUIREMENT_RISK_REPORTS.md](../REQUIREMENT_RISK_REPORTS.md)。

2026-09-23：原型链接只读解析由 `integrations/prototype_link.py` 限定 HTTPS 主机和静态路径、拒绝重定向并限制响应大小；`prototypes/service.py` 在网络等待前释放事务，返回后复核项目权限及来源地址。`prototypes/router.py` 提供受鉴权页面目录，`requirements/risk_analysis_execution.py` 与 `code_analysis/sources.py` 复用同一读取流程，把所选 HTML 和原型说明固定进各自输入。未新增表/依赖，不执行页面脚本或扩展 Git/外部写权限。

2026-09-23：代码分析在完整AI响应返回后，将原文原子保存到私有本地候选目录；只对同片段唯一完整原文行做确定性坐标校正，再经严格校验与权限复核入库。证据校验失败的候选可由原发起人在同一任务上手动重新校验，原文下载仍受项目权限保护，不再次调用AI。目录由`CODE_ANALYSIS_RESULT_PATH`配置，AI调用失败/无完整响应不生成文件。详见[CODE_ANALYSIS.md](../CODE_ANALYSIS.md)。

2026-09-21：代码分析正式接入Skill v2本人AI后台任务和input/report配对导入。modules/code_analysis按router/schemas/service/sources/contract/execution/chat/export分层；chat_worker轮流领取需求/代码分析及两类对话。迁移28增加任务元数据/人工处理和独立代码对话表。GitHub只走固定GET白名单，本地代码由浏览器读取所选文本；不执行代码或Git写操作。详见[CODE_ANALYSIS.md](../CODE_ANALYSIS.md)。

2026-09-17：HTML浏览器预览由documents/router的browser端点返回隔离HTMLResponse，service.html_preview复用stored_version权限与files.decode_text；前端OriginalPreview仅展示固定版本新标签链接。后端不运行上传脚本，浏览器CSP沙箱不开放同源权限和外部资源，无新表或依赖。

2026-09-17：需求分析方案阶段1至4正式接入。requirements/risk_analysis_service负责首次分析任务、权限和幂等，risk_analysis_execution由既有app.chat_worker执行Skill v3个人AI调用；risk_service统一累计清单、导出和独立人工风险。requirement_chat_turn按function_key隔离需求/功能对话并保存risk_key引用。迁移26新增requirement_risk_analysis、requirement_manual_risk及聊天范围字段，不恢复旧analysis_worker；链接采集和附件仍未实现。

2026-09-17：首期需求分析对话新增requirements/chat_schemas、chat_service、chat_execution及独立app.chat_worker；前端RequirementChat/chatApi复用api/http。DB表requirement_chat_turn保存轮次和队列；调用只使用操作者个人配置，经integrations/responses.converse接收完整响应，不改风险数据。详见REQUIREMENT_CHAT.md。

2026-09-16最新产品方向：围绕同一需求分析记录的功能风险、依据、产品确认及复核，提供一个需求分析对话和各功能独立对话，并保存完整报告快照。平台后端使用当前操作者个人AI服务API，平台管理对话历史与上下文，不要求安装本机连接程序、启动CLI或绑定电脑；此方向替代此前本机执行器主方案，见[LOCAL_ANALYSIS_SESSION_PLAN.md](../LOCAL_ANALYSIS_SESSION_PLAN.md)。本轮仅调整HTML与说明，正式会话/上下文/分析调用尚未实施，不改变本文core/db/security/integrations/api/modules分层、个人密钥后端管理或Git只读边界，不扩大真实AI调用及资料外发授权。


2026-09-15需求风险报告正式接入：RiskReports/riskApi使用公共请求，requirements/router的risk-reports转risk_service，risk_schemas严格处理契约3与跨文件证据，复用documents权限/私有版本预览。requirement_risk_report及迁移24保存固定输入/结果/关联与独立处理审计。旧验收点前端、v2分析服务/路由/Worker及Skill兼容目录已移除，不接AI。旧表和人工服务保留数据引用，但新报告不走它们。实现及边界见REQUIREMENT_RISK_REPORTS.md。下文此前v2 Worker运行说明是历史，不再执行。


2026-09-15 Skill v3：根skill/requirement-analysis/SKILL.md及contract.md已升级为需求风险报告契约3，examples提供完整合成输入/输出。现有正式任务接口仍为v2，analysis_service.SKILL_ROOT显式固定到同功能目录compatibility/v2，两个旧文件与原2.0.0包逐字节一致；不是新增业务模块，不改数据库或API输出。v3正式风险报告链路尚待实现。


2026-09-15日志：core/logging提供无业务依赖的标准库轮转文件handler与安全异常格式；main在生命周期配置api.log并记录路由模板/状态/耗时，analysis_worker配置analysis-worker.log，analysis_service记录任务阶段。目录为根log/，不新增数据表/依赖，详情见LOGGING.md。

2026-09-15分析全链路诊断：integrations/response_diagnostics只解析安全协议元数据，responses通过注入的进度回调报告计数/阶段，不导入业务或数据库。analysis_service负责每阶段及节流写入，Worker负责失败和重启状态；analysis_diagnostics将本地结构/引用校验错误转换为不含输入值的诊断。迁移23为requirement_analysis增加diagnostics JSONB中文注释列，历史为空，不修改旧任务结果。前端AnalysisDiagnostics在现有任务详情显示阶段/耗时、来源计数、响应事件、已识别错误与可复制安全信息，仍复用公共请求。

2026-09-15本地 HTML 原型：沿用 prototypes 上传路由 → documents.upload → files 文本校验/预览及私有版本存储，HTML/HTM仅对PROTOTYPE上传开放。PrototypeEditor复用原上传流程，OriginalPreview转义显示源码，鉴权下载强制附件。analysis_materials.file_material将固定版本HTML按完整文本读取，不执行或获取依赖；无新表/依赖。见PROTOTYPE_MATERIALS.md。


2026-09-15需求分析调用：Requirements内RequirementAnalysis通过公共http调用requirements/router，analysis_service负责任务/权限/快照/原子采纳；analysis_schemas校验Skill v2及引用，analysis_materials只做不执行代码的完整内容处理。app/analysis_worker.py为独立单进程，PostgreSQL会话锁防重复Worker，持久化领取、进程中断不自动重新计费。ai/service.analysis_configuration只解析当前用户个人配置，integrations/responses.analyze复用固定协议客户端；github.prototype_content新增固定GET blob与SHA完整性校验。迁移22新增任务表及验收点来源任务字段，原人工Source表不改。详见REQUIREMENT_ANALYSIS_INTEGRATION.md。

2026-09-14追加：需求/原型资料删除复用documents.deletion_info/delete_document，通过purpose隔离，两模块路由只转发；SourceDocument增加删除审计列，旧版本读取继续鉴权。MaterialDeleteDialog共用影响预览/确认，新增引用在requirements服务和附件绑定服务校验删除状态，历史来源不重写。


2026-09-14追加：需求功能分类删除增加迁移其他、待归类、一起删除三种处理，requirement_rule.deleted_at由20260914_20迁移实现验收点逻辑删除，服务统一过滤已删除记录；保留版本与来源历史，详见REQUIREMENTS.md。

2026-09-14用户本地代码：modules/local_code按router/schemas/service分层，仅登记项目关联元数据，复用projects.access_project；新增local_code_source及迁移19，中文COMMENT齐全。前端LocalCode装配在项目设置本地代码分类，localCodeApi复用api/http，localCodeFiles只读浏览器授权目录，localCodeStore负责IndexedDB事务追加快照。代码内容与历史不上传、不执行，AI未接入。具体边界见LOCAL_CODE.md。

2026-09-14原型资料正式接入：新增modules/prototypes的router/schemas/service及Prototypes/PrototypeEditor/PrototypeLinkPreview/prototypeApi，复用documents的项目权限、revision、分组和私有图片版本存储；需求/原型通过purpose区分。GitHub元数据读取仅扩展integrations/github固定GET白名单。迁移14及16已落库，功能与真实验证边界见PROTOTYPE_MATERIALS.md。AI/Skill和网页快照采集未接入。

2026-09-14追加：所有可见控件遵守UI_STANDARDS.md。FormSelect/Select为共享主题下拉与自由输入建议，FilePicker封装文件选择入口，Form统一应用内校验；业务弹窗复用既有CaseDialog/主题dialog。页面只传选项和值，不新增原生下拉/浏览器业务弹窗。共享组件不依赖业务页面或API，后端与权限不变。

2026-09-14追加：导入用例编号通过managed_case.imported_number保留文本原值，20260914_13回填初始版本来源；内部number保留排序/分配职责，API用例number为展示字符串，设计版本number仍整数。接口分层不变，详见CASES.md。


2026-09-14追加：用例行内/批量编辑共用cases/service.apply_case_update及项目锁，快照读取/范围校验/整批事务均留在cases模块；逻辑删除由20260914_12增加审计列，不移除历史。前端CaseTableEditor复用现有公共请求、弹窗及列表，main.tsx用既有React Router的createBrowserRouter/RouterProvider提供useBlocker离开保护，原App路由和URL保持不变。详见CASES.md。


2026-09-14原型资料：已获授权更新总 HTML，新增同级资料入口，GitHub 代码来源复用本人连接与项目已关联仓库的权限交集。正式读取、接口和数据表未实施；后续按现有分层及固定只读白名单接入，不允许上传/运行原型代码扩大权限。见 PROTOTYPE_MATERIALS.md。

2026-09-14：需求分析人工维护页面已按现有分层接入，新增modules/requirements的router/schemas/service，前端Requirements/RequirementEditor/requirementApi及共用FormSelect；复用公开资料访问校验、项目锁与只读原文预览。迁移20260914_11新增六表，具体边界见REQUIREMENTS.md。AI、Skill、分析任务尚未接入。

2026-09-12范围调整：用户要求先去掉“接口资料”。正式前端和总HTML已移除该菜单、页面与原型导入/详情操作；旧入口转到需求资料。后续当前范围不包含独立Apifox/OpenAPI资料模块。平台自身API、GitHub接口、代码中的接口字段分析不受影响；未删除历史浏览器原型数据或数据库记录。


更新：2026-09-12。本文件描述当前代码架构；功能范围见各模块说明与 FEATURES.md。整体采用 React + TypeScript、Python + FastAPI、PostgreSQL 的模块化单体，不拆微服务。

2026-09-12追加：需求原始资料已按本架构实施。新增`modules/documents/{router,schemas,service,files}.py`、前端`Documents.tsx`/`documentApi.ts`，复用项目权限和公共请求；新增四张资料表及迁移20260912_06。files.py仅承担本模块本地格式处理，不依赖HTTP/数据库。私有存储、版本、组内排序、拖动移组和预览边界见DOCUMENTS.md；以下“需求文件解析尚未实现”是重构时历史快照，需求分析任务仍未实现。

## 1. 实现范围与本次重构

2026-09-12追加：用例管理已实施，modules/cases包含router/schemas/service/files；前端Cases.tsx、CaseEditor.tsx、CaseImportDialog.tsx、CaseDialog.tsx与caseApi.ts。复用公共api/http、项目权限和openpyxl/xlrd；六张新增表使用中文注释及20260912_09迁移。用例普通字段独立列，导入原始解析和预览快照JSONB。具体接口、版本、事务和导入规则见CASES.md。

2026-09-12追加：本地Office预览解析集中到documents/office.py（安全XML/压缩包、DOCX结构、openpyxl读取XLSX、xlrd读取XLS），files.py负责格式分发及文本/图片/PDF；不依赖HTTP/数据库。前端OfficePreview.tsx按受校验的结构渲染正文和工作表，仍使用现有鉴权预览接口，无新表。

2026-09-12追加：Markdown附件关联复用documents模块，新增markdown_links.py纯解析助手（不访问链接地址）、service内追加关联/继承流程、DocumentLinks.tsx选择和预览。迁移20260912_08新增document_link_binding，组合外键固定同项目版本，表字段有中文注释。后端markdown-it-py用于原文链接校验；AI模块仍未实现资料分析。

已实现：自有账号登录和账号管理、密码请求加密、个人/平台 AI 配置和固定文字连接测试、GitHub 多连接与指定仓库只读授权、最小项目/成员/仓库入口。

本次仅调整代码职责与依赖方向，修复前端自带取消信号时默认超时失效。没有改界面、接口协议、数据库表、主密钥或已保存配置。现有登录会话仍由数据库保存；API重启会使未提交的一次性挑战失效，重新提交即可重新获取。

尚未实现：需求文件解析、用例业务、代码下载与快照、分析任务、Worker、报告、自动测试等。新增业务仍须逐项确认。

## 2. 当前目录

~~~text
backend/
  app/
    main.py                   FastAPI装配、健康接口、统一错误及响应安全头
    init_admin.py             保留现有本机管理员初始化CLI
    api/
      router.py               已实现模块的路由注册
      dependencies.py         DB依赖、当前用户/管理员、Origin、请求限流适配
      encryption.py           HTTP路径白名单、Cookie绑定、密文协议适配
    core/
      config.py               backend/.env配置；路径与原文件保持一致
      errors.py               不依赖FastAPI的AppError
    db/
      session.py              Engine、Session生命周期、Base与就绪查询
      models.py               当前全部ORM声明；原表名/约束不变
    security/
      passwords.py            scrypt密码和会话Token哈希
      envelopes.py            RSA/AES封装、一次性挑战与防重放机制
      rate_limit.py           进程内有限容量限流
      secrets.py              AI/GitHub凭据加密主密钥读取
    integrations/
      github.py               固定GET白名单、GitHub协议/响应校验
      responses.py            Responses协议及固定文字测试
    modules/
      auth/                   登录、退出与身份查询
      accounts/               管理员账号CRUD和密码重置
      ai/                     配置作用域、版本、密钥与使用来源
      github/                 个人连接、发现凭证、授权仓库持久化
      projects/               项目、负责人、成员与仓库关联
        router.py             上述每个模块都有此协议入口
        schemas.py            每个模块的输入/输出校验结构
        service.py            每个模块的用例流程、业务权限、事务
  migrations/                 Alembic历史迁移；env引用db/models
  tests/                      原功能检查及分层依赖检查

frontend/src/
  App.tsx                     登录拦截、原型工作台和路由
  Platform.tsx                平台设置容器，装配账号/AI/GitHub页面
  Accounts.tsx                账号管理组件
  Auth.tsx                    登录/身份状态
  AIService.tsx               AI配置页面
  GitHubConnections.tsx       GitHub连接页面
  Projects.tsx                项目、成员和仓库页面
  api/http.ts                 共用JSON/加密请求、超时/取消、错误分发
  githubApi.ts                GitHub类型与业务错误文案
  projectApi.ts               项目错误文案，复用必要GitHub错误
  passwordTransport.ts        既有Web Crypto封装
~~~

没有为尚未确认的模块创建空实现。models.py当前集中保存8个模型是有意保留，不必每表一个文件。复杂查询出现复用时再提取查询文件，不创建只转发调用的Repository层。

## 3. 依赖方向

~~~mermaid
flowchart TD
  Main["main / api.router 装配"] --> Routes["modules/功能/router"]
  Routes --> Deps["api/dependencies 与 encryption"]
  Routes --> Service["modules/功能/service"]
  Routes --> Schema["modules/功能/schemas"]
  Deps --> Auth["auth/service 身份查询"]
  Deps --> Security["security 安全机制"]
  Service --> Schema
  Service --> DB["db Session 与 ORM"]
  Service --> Client["integrations 外部客户端"]
  Service --> Security
  Client --> Core["core 配置与错误"]
  Security --> Core
  DB --> Core
~~~

明确规则：

| 层 | 负责 | 禁止 |
| --- | --- | --- |
| main / api.router | 应用和模块装配 | 填入业务流程 |
| api适配 | HTTP身份、来源、Cookie、密文上下文 | 承载项目/用例业务 |
| 功能router | 参数/密文解析、协议结果、调用service | SQL、外部请求、调用其他模块router |
| schemas | 输入校验和结果结构 | 事务、网络调用、反向调用router |
| service | 资源权限、业务规则、版本检查、事务 | FastAPI/Request/Response/Depends、依赖app.api |
| integrations | 对外固定协议、白名单、超时和响应校验 | ORM/数据库/业务模块、任意命令 |
| security | 通用安全机制 | 业务路由路径列表、业务模型 |
| db | 连接与ORM声明 | 依赖router/service或调用AI/GitHub |
| core | 配置与安全错误定义 | 反向依赖上层 |

schemas可以引用已有纯校验函数，例如Git分支格式和Responses地址规范化，但不执行外部I/O。

跨模块允许真实业务依赖，不能形成环：当前 projects/service 只从 github/service 调用 own_connection、saved_token；accounts/schemas 复用 auth/schemas 的账号格式。未来只通过明确公开的服务/契约调用，不能导入路由文件以复用内部函数。

## 4. 两条实际调用链

### 项目仓库关联

~~~text
POST /api/projects/{id}/repositories
→ api.dependencies：确认登录用户、请求来源、注入Session
→ projects/router：解析RepositoryInput
→ projects/service.bind_repository：
   验证项目管理权限、本人连接、授权仓库、记录当前版本
→ github/service：本人连接与已保存凭据读取
→ 释放数据库事务
→ integrations/github.check_repository：固定GET读取仓库/分支
→ projects/service：再次核对操作者状态、项目权限、连接/表单版本
→ 原事务规则提交仓库元数据
→ router返回原结构
~~~

项目仅关联仓库元数据，不借用其他人的Token。所有远端请求只能走客户端白名单；本次没有实现clone/fetch或代码快照。

### AI连接测试

~~~text
POST /api/ai-service/{scope}/test
→ api依赖：身份/来源/限流
→ ai/router：校验scope权限，解密并构造ConnectionInput
→ ai/service：核对配置版本，解析本次或已保存的Key
→ 释放数据库事务
→ integrations/responses.probe_model：只发送固定文字
→ 协议校验结果或AppError
→ main统一映射安全错误
~~~

不自动保存测试表单，不自动重试或切换使用来源。模型强度原样传递，当前256输出token/120秒网络等待等行为保留。

## 5. 事务、错误和安全

- service拥有当前业务提交/回滚边界，router只转发，不额外提交。Session生命周期由db管理。
- 外部等待前释放事务，返回后再次检查权限与版本再写库。不得把操作者/授权的旧快照当作长期有效。
- AppError保留安全detail错误码、状态码及必要响应头，API统一映射；它不继承HTTPException，未来Worker可以直接记录错误码。不是新建一套抽象异常工厂。
- 用户输入校验仍用Pydantic；API不返回校验输入、SQL参数或上游凭据。
- 原backend/.env读取位置固定保留。共享主密钥配置仍名为AI_ENCRYPTION_KEY，以兼容现有AI/GitHub密文；名称历史不意味着GitHub依赖AI业务模块。
- 一次性挑战与部分限流仍为进程内状态，仅支持单API进程。安全机制与HTTP适配已分离，但并未实现跨进程共享；扩容需另外设计原子消费、密钥管理和共享限流。
- 初始化管理员仍用python -m app.init_admin，已有管理员时不得重新初始化。

Git客户端保持固定域名、GET与禁止重定向，不提供任意URL、方法、请求体或命令入口。平台禁止push、上传/修改远端文件、远端分支/Tag增删、PR创建/合并、评论。权限不能被Skill或用户补充指令突破。

## 6. 新功能如何接入

1. 先取得具体业务确认：流程、字段、角色、数据版本、接口、异常、验收标准。
2. 对照总HTML原型确认页面入口及布局；不因分层重构更改设计。
3. 在modules/<功能>下增加实际需要的schemas/service/router，职责见上表。
4. 业务权限放service可复用的明确函数，路由同时使用身份依赖；未来Worker从可信上下文加载操作者，再执行同样的资源校验。
5. 需要持久化时增加ORM与审查后的Alembic迁移；不要启动时create_all，不覆盖原有历史。
6. 需要外部能力时先复用现有integrations客户端；只有确实新增协议才增加客户端，不预建供应商工厂。
7. 在api/router.py注册路由；涉及密文提交时显式更新api/encryption.py白名单，安全核心不感知新业务路径。
8. 前端按功能增加组件/业务API，使用公共请求工具；传入取消信号仍必须保留超时。
9. 添加与风险对应的最小测试，运行类型/格式/构建、架构和业务检查；描述真实与模拟验证边界。
10. 更新对应模块说明、功能状态和SESSION_CONTEXT.md。只有明确确认的内容才能标记为已实施。

后续功能按以上方式增加，不为未来能力提前建立数据库表或空服务。Skill当前以根目录功能文件为准，平台普通用户只读、管理员备份后直接写回正文；任务保存实际内容快照。本人AI对话只产生待人工应用的建议，不直接修改文件，详见SKILL_MANAGEMENT.md；不恢复旧原型的导入/发布/项目绑定系统。

2026-09-14用户明确：现有及后续 Skill 统一放在项目根目录 `skill/<功能目录>/`，每个功能目录包含 `SKILL.md` 及必要契约、引用文件。需求分析位于 `skill/requirement-analysis/`。不放在 `docs/skills/` 或个人 Codex 技能目录；新增或移动时同步文档引用。本约定不代表调用功能已接入，也不扩大外部调用授权。

## 7. 前端公共边界

2026-10-14全部翻页面板接入共用PageJump：只负责页码输入、整数/已知范围校验及主题反馈，实际分页数据/筛选/读取仍由所属页面处理；不引入后端分页协议或跨模块请求。详见[PAGINATION.md](../PAGINATION.md)。

Platform.tsx仅装配平台设置分类，Accounts不再加载AI和GitHub组件。菜单、分类默认项和JSX内容保留原设计。

api/http.ts集中已有GitHub/项目使用的JSON和加密请求，取消信号使用AbortSignal.any与超时组合；401转换为统一错误码。错误文案由githubApi/projectApi决定，项目关联仓库需要的GitHub错误有明确复用。

历史登录/AI页面的交互和请求流程未批量重写，后续修改时逐步复用。泛型仅描述编译期返回类型，不宣称能在运行时验证所有响应字段。

## 8. 界面与业务约束

总原型：C:/Users/geekonup/Documents/Codex/2026-08-17/new-chat/outputs/verity-prototype.html

总原型右侧业务规则说明按当前代码分菜单页、弹窗及具体操作维护，覆盖字段条件、数量/长度限制、版本冲突、权限和数据影响；支持搜索、展开收起及当前弹窗定位。维护说明与代码核对索引见 [原型业务规则](../prototypes/verity-business-rules/README.md)，规则正文见 [RULES.md](../prototypes/verity-business-rules/RULES.md)。说明栏描述正式实现，原型交互仍使用虚构示例，不触发真实业务或AI调用。

不得擅自修改菜单、顺序、分组、字段或交互；新增独立原型必须回接总原型。账号登录不列为侧栏业务菜单。平台设置保留AI服务、GitHub连接、账号管理；2026-10-14用户移除原型数据。具体菜单和14列规则见SESSION_CONTEXT.md、FEATURES.md。

原型只是模拟，正式分析功能以各模块当前代码及模块文档为准。多步骤对应场景级预期；AI新用例默认未执行；原表的通过是导入测试记录。原型调整不授权真实AI付费测试、业务资料发送或其他远端操作。

## 9. 迁移对照与验证

| 原路径 | 新位置 |
| --- | --- |
| app/auth.py | modules/auth + api/dependencies + security/passwords/rate_limit |
| app/users.py | modules/accounts |
| app/ai_service.py | modules/ai + integrations/responses |
| app/github.py | modules/github + integrations/github |
| app/projects.py | modules/projects |
| app/password_transport.py | security/envelopes + api/encryption |
| app/config.py | core/config.py |
| app/database.py / models.py | db/session.py / models.py |
| Accounts.tsx中的Platform | Platform.tsx |
| githubApi.ts中的请求函数 | api/http.ts |

原平铺模块已移除，内部调用、测试mock、CLI和迁移加载均已同步。URL和app.main启动入口不变；不要重新导入旧模块。

本次验证：OpenAPI重构前后相同（21个路径）；24项后端检查通过，包括真实PostgreSQL事务回滚检查及AST依赖/循环检查；GitHub/AI上游模拟。Alembic current为20260912_04，check无新迁移。前端check、test、build通过。数据库记录、已保存密钥不因整理目录重置。

本地后端已重启，live/ready、前端代理ready正常，未登录访问项目/GitHub返回401。浏览器检查真实未登录拦截、模拟管理员数据下的平台设置装配、原菜单分类和窄屏布局；未发送真实供应商请求。

tests/test_architecture.py自动检查服务不依赖HTTP、客户端不依赖DB/业务、路由不写SQL/网络以及循环导入。该检查是静态依赖防线，不代表全面安全或并发审计。
