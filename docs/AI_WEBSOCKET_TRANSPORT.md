# 完整变更分析WebSocket尝试结果（已撤下，2026-10-26）

<!-- document-status:start -->
> **历史资料，不再作为当前开发或运行规则。** 失败方案已撤下，仅留排障记录，不是生产通道。 当前说明见[AI_SERVICE.md](AI_SERVICE.md)。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

本说明的候选已真实验证失败并撤下，不是当前生产通道。用户另行明确允许仅一次真实验证，已新建610/retry_of413（request_id446d127e-3c06-51f9-9e73-f1fb144ae757），同本人配置7/gpt-6.1-sol/high、完整固定输入仅request_id不同。16:06:34发送唯一response.create，49,626,506字节，7.302秒后以1013/no available account关闭，未收到模型事件/候选；没有HTTP回退、重发或第二次调用。原始关闭说明已私有加密保留，安全结果见outputs/change-413-websocket-one-result-20261026.json。

公开实现将此原因用于WS入口选不到合格账号，HTTP调度能力不同；未发现客户端字段可以绕过账号能力/路由/并发准入。实际部署版本未知，不能断言某个具体配置错误。平台没有中转管理权限，无法单边修复；服务提供方排障说明见[AI_RELAY_SUPPORT.md](AI_RELAY_SUPPORT.md)。

失败后已撤掉WS生产客户端/调用参数/测试及新依赖，卸载本项目无其他依赖者的websockets。所有分析保持原共用HTTP/timeout=None。8份候选源码/测试/说明归档outputs/change-websocket-failed-candidate-20261026.zip，不留不可用默认通道。共用HTTP/流内错误增加no available account受控分类与中文提示；610经原私有错误免费准确分类、保留先前错误码审计，固定输入/Skill/report/handling及原关闭错误保持。没有再调用AI。

撤下后55项后端、25项前端回归及check/build/Ruff/pip check通过。活动任务为0时重载本地原API/Worker，16:19:35 Worker就绪，8000/5173代理健康200；加载前后413/467/556/610所有状态/输入/metadata/报告/人工处理指纹相同。当前无成功完整分析报告。

用户要求“改到能用”，随后明确不允许访问中转管理站且本人没有该权限。停止管理入口访问，不使用其他工具绕过。当前中转HTTP `/responses` 已实际返回OpenResty HTML504；本机没有对应网关配置，不能从平台取消对方的超时。

正常模型接口的无生成连接探测确认同一已配置地址`wss://sub2api.geekuat.com/responses`返回101并响应ping/pong。仅连接和控制帧，没有发送公司输入或response.create，因此没有新增模型生成调用。完整空连接测试被服务端1008关闭，原因是缺少首条response.create；这只能证明其首消息要求，不是分析期间保活成功，也不能证明已绕过全部中转内部HTTP时限。

## 候选实现（已归档，当前生产不使用）

共用responses.analyze增加可选transport，默认HTTP保持；FULL_INPUT变更分析选择WebSocket。原Skill、模型/high/32000、固定根输入及全部附件保持，公共无损引用和同请求文本片段仍保留；事件只发送一个response.create，移除仅HTTP使用的stream字段，store=false。不是分批分析、摘要替代或背景存储。

新增integrations/response_websocket，继续复用原read_stream/output_text完成门槛及错误私有加密捕获；adapter仅把一个WebSocket JSON事件转换给原事件校验，不另造业务结果协议。ping_interval15秒、ping_timeout/open_timeout=None，无平台总分析期限；recv的1秒等待只用于检查取消/权限，不在安静时终止分析。连接TLS默认校验，禁止环境代理和压缩，固定同来源wss路径；所用同步客户端不跟随重定向，凭据不转其他来源。

发送开始前标generation_sent，即使部分写入失败也不能自动重发。只有服务器在握手阶段以400/404/405/426/501明确拒绝升级且尚未发送response.create时，才回退原HTTP作为唯一首次生成；鉴权/重定向/服务器失败不猜回退。发送以后断开、流内错误或不完整结果全部失败，没有HTTP回退或重试。safe_snapshot保留transport/generation_sent/握手状态/关闭码，关闭原因只入原私有加密诊断，不进公开日志。

依赖新增固定websockets15.0.1，原项目没有WebSocket客户端依赖，stdlib没有完整同步客户端。该库负责TLS/握手/控制帧/碎片/线程保活，避免在业务中手写协议。无新表/字段/迁移、后台Worker、UI控件或中转配置写入。

## 候选阶段验证与限制

无生成真实探测：目标正常API握手101/正确Sec-WebSocket-Accept，ping收到匹配pong；未访问管理API、没有新增权限或模型请求。

本地29项变更流程回归通过，26项WebSocket/共用传输/完整输入/架构检查通过。包含完整JSON与Unicode重组、一个create、原参数/角色/store=false、取消安静连接、真实本地WebSocket服务延迟输出期间保活、仅握手不支持可回退、发送失败无重试、重定向/鉴权失败不转发凭据。真实模型全部mock，不能据此称49.6MB输入成功。

公开Sub2API源码的入口默认64MiB首消息限制、30秒首消息等待，以及大包约15MiB进入HTTP桥接都是参考，不证明现网站点同版本/配置。桥接等待上游时是否及时回复客户端ping存在额外限制；只握手和空闲探测不足以证明真实业务等待能保持。WebSocket也不扩大模型上下文或取消服务端自己的期限，完整分析实际成功仍需获授权的一次模型验证。

HTTP556及本次另行明确授权的WS610均已各调用一次，两个单次授权均消费完；没有自动重试，当前无成功报告。网关管理访问已被用户拒绝，不能继续索取或绕过。

加载前核对所有状态表QUEUED/RUNNING为0，原API及chat_worker按项目脚本重载；15:58:13 Worker ready，API应用35696、Worker应用40148（各一组虚拟环境父子进程），8000及5173代理健康200。加载后任务413/467/556的状态、输入、metadata含Skill、报告和人工处理指纹与加载前相同，活动任务仍0；没有新建或重试分析。只读结果见outputs/change-websocket-readiness-20261026.json。

依据：[OpenAI WebSocket模式](https://developers.openai.com/api/docs/guides/websocket-mode)、[websockets同步客户端](https://websockets.readthedocs.io/en/15.0.1/reference/sync/client.html)、[Sub2API公开配置](https://github.com/Wei-Shaw/sub2api/blob/main/deploy/config.example.yaml)。
