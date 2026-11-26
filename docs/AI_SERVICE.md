# AI 服务

## 个人配置与调用

每个账号分别保存 Responses API 和 Codex CLI 配置，并选择当前调用方式。连接地址、模型和推理强度由当前用户确认。平台加密保存密钥，通过已冻结的调用方式与配置版本复核授权。任务使用本次操作者的配置。人工重试沿用原任务的调用方式，重新核对来源权限和操作者当前配置。

平台设置中的 AI 服务页可测试表单、保存配置、切换已保存的配置。API 模型列表使用表单密钥或同地址下当前账号保存的密钥，固定读取模型目录。测试只发送固定文字。业务调用保留完整流式结果，平台保持单次请求语义。CLI 内部的多轮读取、重试和压缩按原生机制工作。

## 同源接口

| 路径 | 用途 |
| --- | --- |
| GET /api/ai-service | 读取当前账号的 API、CLI 配置摘要、活动方式及后端运行状态 |
| POST /api/ai-service/configuration | 保存个人配置，可同时启用 |
| POST /api/ai-service/activate | 启用已保存的配置 |
| POST /api/ai-service/test | 测试当前表单所选调用方式 |
| POST /api/ai-service/personal | 旧客户端保存个人 API 配置 |
| POST /api/ai-service/personal/test | 旧客户端测试个人 API 表单 |
| POST /api/ai-service/personal/models | 读取可用模型标识 |

业务分析和对话使用模块自己的接口。请求沿同源身份、来源与密文校验。只读取受信任的服务地址，错误日志保存有界、脱敏后的诊断。

## 用量和部署配置

Responses API 完成响应提供用量时，记录输入、缓存命中、输出、推理和总 Token 数。分析同时记录文本字符数、UTF-8 字节数、图片数和估算 Token 数。中日韩字符约计一个 Token，其余约每四字节一个 Token。CLI 记录估算输入规模，实际用量以其可验证诊断为准。

需求风险使用任务 context.ai_diagnostics，代码及变更分析使用 metadata_snapshot.ai_diagnostics。用例生成和用例分析沿用已有诊断位置。诊断只保存受控摘要。上游原始错误经密钥脱敏后加密保存至私有错误目录。

AI_ANALYSIS_MAX_OUTPUT_TOKENS 可按 requirement_analysis、code_analysis、change_analysis、case_generation、case_analysis 配置。单项须为 1024–200000 的整数，未配置时为 32000。该配置适用于 Responses API 分析请求。模型能力由配置使用者核对。

调度、Windows ConPTY、私有工作区和故障恢复详见 [API 与 CLI 实施契约](AI_CODEX_CLI_IMPLEMENTATION.md)。以往阶段与验证记录见 [历史记录](archive/AI_SERVICE_HISTORY.md)。
