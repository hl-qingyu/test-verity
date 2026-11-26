# 本地运行日志

## 现行规则

日志保留请求路径模板、状态、时长和安全诊断。配置值、凭据和原文保持私有，故障定位使用受控字段与加密错误记录。

2026-10-15变更读取诊断写入当前log/chat-worker.log（API调用共享GitHub客户端时写log/api.log）：github_read_failed只记固定operation、1起始attempt、安全code与retry布尔值；change_source_read记source_id/side/tree或blob阶段及总数、完成/复用数量，正文读取耗尽重试时change_source_read_failed带所选清单内1起始index；change_execution_failed增加安全错误码。可据固定任务选择定位失败位置，不记录文件路径/名称、GitHub响应或异常消息、Token和代码正文。历史155日志未记录的位置/已读数不补造；读取重试不涉及AI或Git写入。

2026-09-15更新：需求分析已改为本地JSON风险报告导入，旧analysis_worker程序已移除并停止。当前导入、人工处理和请求事件写log/api.log，log/analysis-worker.log仅保留历史，不再启动旧Worker。目录轮转与敏感内容规则不变。


应用日志统一存放于项目根目录 `log/`，路径根据代码位置解析，不随启动工作目录变化。启动API或Worker时自动创建目录；目录不可写则启动明确失败。

| 文件 | 内容 |
| --- | --- |
| log/api.log | API启动/关闭、请求方法、注册路由模板、HTTP状态、返回响应头前的耗时、业务拒绝码、数据库及未处理异常 |
| log/analysis-worker.log | Worker启动/退出与锁、任务领取、分析阶段/耗时、模型传输状态、完成及失败原因 |

每条日志包含本机时间、级别、进程ID和模块名。分析记录带task编号，可与页面诊断/数据库任务关联。使用Python标准库RotatingFileHandler，INFO及以上写入，单文件10 MiB、保留5份历史（.log.1最新、.log.5最旧），两类日志最多约120 MiB，单条超大日志可能略超上限。沿用现有单API进程、单Worker部署，两个进程分别写不同文件；不要让多个同类服务共享轮转文件。

请求只记录注册路由模板（如 /api/projects/{project_id}/prototypes/upload），不记录实际路径参数、查询字符串、请求头、Cookie、请求/响应正文、文件名或客户端IP。未知路由记unmatched。业务日志仅允许固定文字和安全错误码/数量/耗时/任务ID；不记录密码、Token、资料原文、完整提示词、模型正文或数据库连接串。异常保留类型及文件/函数/行号，不输出异常消息、源代码行、局部变量和SQL参数；忽略其他handler缓存的异常正文。

仅app命名空间写入这两类文件，不收集第三方库的原始请求/SQL日志，不把进程stdout/stderr重定向文件当作脱敏应用日志。Uvicorn自身控制台输出沿用启动方式；原backend目录旧日志保留，本轮不搬迁、不清空，也不能补录新机制启用前的请求。根目录/log/已整体加入Git忽略，轮转文件同样不提交。

API仍使用原启动命令，Worker仍使用 `python -m app.analysis_worker`，不需要新增依赖或数据库迁移。应用正常关闭会记录停止；强制结束进程无法保证有关闭记录。分析取消、失败人工重试规则不变，不因记录日志重发模型请求。

验证使用临时目录，覆盖轮转上限、重复配置不重复写入、API实际路由/状态/耗时、异常格式，以及敏感查询/路径/请求正文/SQL参数不落盘。后端整体回归使用真实PostgreSQL外层回滚和模拟上游；未向真实AI发送资料。

本轮交付：日志专项3项与后端全量81项通过，Ruff通过；重载后API/Worker文件实际写入、ready与Worker锁已验证。
