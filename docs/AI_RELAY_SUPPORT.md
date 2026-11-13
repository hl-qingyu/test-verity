# 中转服务排障说明（2026-10-26）

<!-- document-status:start -->
> **专项运行参考，使用前核对实际环境。** 服务方排障材料，处理前重核现场，旧失败不代表当前状态。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

需要中转服务提供方处理。平台用户没有管理权限，平台未修改中转配置。本说明不含密钥、公司资料或分析输入。

目标：`https://sub2api.geekuat.com/responses`，个人配置模型`gpt-6.1-sol`、reasoning high。需完整输入一次整体分析，不能通过删资料或多次独立分析替代。

| 验证 | 观察到的实际结果 |
| --- | --- |
| HTTP，记录556，2026-10-26 15:12:23–15:13:25 +08:00 | 单次POST，49,626,495字节。62.631秒后返回164字节HTML，标题504 Gateway Time-out，footer openresty；没有SSE头或模型事件。平台socket timeout为None。 |
| WebSocket，记录610，16:06:34–16:06:41 +08:00 | 握手101后只发一个完整response.create，49,626,506字节。7.302秒关闭1013，原始reason为no available account；零模型事件。中转请求ID为d4365059-3af3-4769-9990-a3f3da104ba2。 |

请按上述时间和请求ID核对HTTP链路实际超时层/阶段、等待首响应头期间的保活，以及WS入口的账号能力、路由和并发准入。HTTP可用账号与WS可选账号并非必然相同；仅握手成功不代表账号可用。

公开Sub2API实现的WS账号调度失败分支与1013/no available account吻合，但现网版本未知，不能据此断言某个开关未启用。HTTP返回的HTML也不能单独证明哪个代理层、哪一阶段或确切超时配置值；两种故障不能合并为同一个已证实根因。输入大小是已记录的条件，尚无容量拒绝证据。

HTTP代理修复候选及不调用AI的延迟首包/心跳测试见[AI_RELAY_504_FIX.md](AI_RELAY_504_FIX.md)。先核对实际配置和版本，再应用；不直接覆盖现有鉴权、upstream或TLS。平台没有相应权限，尚未应用这些远端改动。

平台已撤下失败的WS候选，恢复所有分析共用HTTP、无限分析等待、完整结果校验和不自动重试。两次单次真实验证授权均已使用，不通过额外收费试验替代中转侧排障。

参考：[Sub2API WS调度分支](https://github.com/Wei-Shaw/sub2api/blob/main/backend/internal/handler/openai_gateway_handler.go#L2663)、[协议能力解析](https://github.com/Wei-Shaw/sub2api/blob/main/backend/internal/service/openai_ws_protocol_resolver.go#L33)。公开main仅供核查，不当现网版本事实。
