# SKILL_MANAGEMENT 历史记录

现行规则见 [SKILL_MANAGEMENT.md](../SKILL_MANAGEMENT.md)。

## 2026-10-22：人工重试仍快速失败，接入多文件消息装配与安全错误日志

用户再次人工重试1371/687，10:49:17发起、10:49:28失败，10.893秒、HTTP200流内response.failed/server_error、类别overloaded，输出正文0；这是正式入口仍使用48,804字节顶层instructions的第四次快速失败，不是第二组902秒的长流中断。原先因完整验证未通过而未部署的拆分方案，现在作为针对快速拒绝路径的兼容调整接入；不宣称长时间流中断已修复，不自动调用AI验证。

skills/files.model_context只从任务固定快照校验完整instructions哈希、文件顺序和正文一致性，提取SKILL.md＋contract.md作为顶层instructions14,332字节，十份完整参考Markdown为同一请求developer消息；所选资料仍user。case_generation/execution复用该装配，responses.analyze只增加可选instruction_messages，其他四类分析默认请求保持。所有12份规则和原资料完整发送，无截断、缩范围、规则回退、模型/推理强度/输出上限变化、新调用或自动重试。无files的旧快照保持原instructions字节，新旧快照不读当前文件冒充；1371的原Skill全文/hash及输入/失败历史不改写。

共用SSE错误日志仅增加受控事件、类别/码/参数、请求/响应标识、请求字节、接收字节/输出字符及错误指纹，不记录错误原文、源码或提示词。safe_snapshot额外保留请求大小、socket超时/响应容量、输出token配置和合法64位指纹；未识别原因仍unknown，不凭902秒认定900秒硬上限。回归明确流读取器在模拟1001秒仍可接受完成事件；600秒为socket操作超时，不是总任务截止。

这是请求装配和诊断修正，第二组真实对照仍是902.512秒流内error，完整生成恢复尚未得到新的真实调用验证。两次收费授权已用完，本轮不发第三次、不替用户点击重试、保存不完整候选或自动入库。参见SESSION_CONTEXT最新运行/检查条目。

## 2026-10-22：生成流失败对照调查（新版保留，未临时恢复）

用户反馈“其他分析可用，只有用例生成改了之后才用不了”。记录1371/批次687在09:57:49、09:58:25、10:00:26三次调用分别约2.315/2.005/1.850秒收到HTTP200流内response.failed/server_error，安全类别overloaded、正文输出0。该分类不能证明具体原因或排除请求相关问题。本人actor30、gpt-6.1-sol、配置7/high；需求分析374同模型/配置在10:09完成，不能把所有通道归为不可用。新指令48,804字节、同资料请求156,046字节，旧指令22,922字节/请求129,845字节；静态逐项断言除指令外新旧内容和参数一致，未发现JSON或字段构造错误。

用户明确允许最多两次真实收费对照，同一固定资料、本人配置，不审核入库/自动重试。第一组旧2.0.4指令成功，736.468秒、response.completed、71,806字符、契约3校验88条、PARTIAL；按初始授权只保存安全诊断，未保存模型正文。第二组保留全部新版规则，SKILL+contract顶层instructions14,332字节，十份references为同请求developer消息，资料仍user；请求156,402字节。902.512秒、输出67,012字符后收到error而非完成，安全类别unknown，终判ai_stream_failed。约15分钟的持续时长支持调查中转长请求处理，但没有明确超时原文，不能断言已证明900秒硬限制；不同时间的两次对照也不能证明长度门槛或排除上游状态变化。

用户在第二组进行中明确若完整完成就保存系统，避免重复分析。已仅对独立第二诊断进程临时设置完整响应保留（Python3.14 sys.remote_exec），只有正常completed且output_text成功时才写私有候选；armed证据generation-comparison-capture-armed JSON。最终无completed，未触发保存，不将流中片段或部分JSON当有效报告，也未插入用例生成记录或审核用例。恢复脚本recover-generation-comparison-20261022.py只在valid_report后允许通过现有imports校验写记录，本次未运行--save。另一次只读GET按第一组response_id取回，404；没有额外模型POST，不能恢复初始未留存正文。诊断没有输出密钥、提示词或公司正文。

候选发送修复一度在工作区实现：model_context从原固定快照拆消息，共用responses.analyze可选instruction_messages，资料/规则/参数/完整指令哈希不变；40项协议/快照/生成/架构检查通过，含6项真实PostgreSQL回滚。第二组未通过完整真实验证，因此未上线，9份源代码/测试/说明精确恢复至写前备份，候选归档outputs/generation-stream-fix-unapplied-20261022/。API/Worker没有因此重启，当前仍原2.1.0完整拼接方式。准备了旧版恢复zip及rollback-preview，独立目录确认原2.0.4指令22,922字节/哈希d772036b8c9e23b6d670d337f95de0e962be9f5ffa618a8b6105d8c52523c4ac。询问是否临时恢复时用户追问“为什么要临时恢复”，没有批准，不能当作恢复授权；新版完整包保留，原1371及三次失败历史未改。

证据：outputs/generation-skill-comparison-{old,split}-20261022.json、generation-skill-incident-comparison、generation-skill-static-comparison、generation-stream-fix-production-payload、generation-old-read-only-retrieval和generation-skill-rollback-preview同日JSON；两次真实对照已经用完授权，不再发起第三次收费请求或原业务重试。官方Responses指令/消息映射已核对https://developers.openai.com/api/docs/guides/migrate-to-responses，但官方合法消息方式不能证明当前中转兼容。后续应继续定位并处理新版请求的失败/长耗时兼容；若要停用已确认新版规则或追加真实验证，需取得对应授权，不能把临时回退或离线测试称为根因修复。

## 2026-10-22：用例生成 Skill 2.1.0 多文件规则

用户确认参考本地testcase深入优化后要求实施。skill/case-generation采用主指令、十份references和resources.json有序清单，覆盖依据/缺失复查、原文反查、角色状态、过程态和移动中断、准备最小化、计算统计、粒度去重、字段语言、优先级及维护澄清。同一次本人AI调用内按范围→当前依据→适用路径→具体设计→已有用例匹配→粒度/优先级→原文反查→契约输出执行；不增加前置AI、自动补生成或中间规则树/场景树。契约3仍只cases/notes/complete，十二个字符串设计字段、真实来源/摘录、四类动作、14列、人工字段保护及同步逐条入库保持；原2.0.4输入/报告/固定重试不改写。

skills/files统一读取清单内12份Markdown正文，按文件边界拼接并保存实际清单、逐文件正文/原字节SHA-256及完整指令哈希；无清单的其他四类Skill保持原双文件拼接和快照形状。清单声明后缺失、重复、顺序错误、越界、非Markdown、空内容及读中变化明确拦截，不静默漏掉规则。清单/契约/参考规则仍只读，管理员仅可编辑主文件正文。Skill管理将运行参考文件标为参与当前AI调用，编辑助手默认携带全部运行规则且不可取消；其他参考可选。长文件名按行换行显示，原布局/权限不变。新准备才使用新版，旧任务使用原快照。

新增完全合成design-quality双JSON，9条建议演示名称边界/空格、填单后下架、汇总最小修改和失败收入排除，执行准备及受理后下架的业务问题分开，complete=false。evaluation补参考映射和反例验收；不运行参考项目脚本、不复制其业务资料，不引入MainBasis、自动改需求、全局扫描或新表/依赖/迁移。完整case-generation文件夹可复制，离线调用者同样须提供清单实际正文，Markdown链接不会自行加载。

2026-10-14读取优化：用户限定Skill管理，已接入浏览专用的进程内内容缓存、整包批量读取、已读文件直接切换、后台校验及Markdown/JSON预览复用。保存、编辑前校验、AI发送和分析快照保持直接读取最新文件；不使用数据库正文或浏览器持久化缓存。细节与验证见下方「读取性能与缓存」。

2026-10-14预览高度调整：用户要求拉长右侧预览，正式页面及两份总原型同步正文最小560px、上限max(560px,100vh−220px)；900px高桌面实际增加160px至680px。窄屏仍自然展开，1440/390px合成组件浏览器核对通过；UI规范4项、双份原型专项、check/build及样式一致检查通过，既有大包提示保持。截图outputs/skills-taller-preview-desktop-20261014.png。仅样式，不改变读取、编辑、权限或AI调用。

2026-10-14：用户选择继续读取本地文件，确认系统中管理员保存后由后端直接写回，并要求「可以，开发功能吧」。正式 `/skills` 已接入真实文件查看、管理员正文保存及本人AI辅助修改。此前仅设计/HTML、数据库正文覆盖建议由本次授权替代。
