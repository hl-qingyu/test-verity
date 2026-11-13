# 本机 CLI 浏览器直连最小 Demo

<!-- document-status:start -->
> **历史资料，不再作为当前开发或运行规则。** 旧浏览器直连实验，未用于正式业务；现有演示代码未删除。 当前说明见[AI_CODEX_CLI_IMPLEMENTATION.md](AI_CODEX_CLI_IMPLEMENTATION.md)。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

2026-09-16用户授权最小Demo验证，限定浏览器直接连接用户本机CLI。这不代表正式接入、业务资料外发或运行任意命令的授权。

## 结果

实测 Codex CLI 0.144.1 的 `ws://127.0.0.1:4500`：无Origin的程序连接能完成initialize；带 `Origin: http://127.0.0.1:5173` 的WebSocket握手返回HTTP 403。浏览器自动携带Origin，因此当前版本的直接连接路径受阻。

没有创建AI会话、读取用户历史、调用模型或发送项目资料。Node协议检查不能称为浏览器视觉实点。本Demo的按钮直接调用浏览器WebSocket，未做代理或剥除Origin；浏览器错误事件不暴露HTTP状态，页面正确区分现场错误与开发时403记录。

## 打开与重现

前端运行后访问 http://127.0.0.1:5173/codex-demo.html ，点击“测试浏览器直连”。总HTML及审阅副本的需求分析页提供“CLI直连Demo”链接。

本机CLI服务已为本次检查在127.0.0.1:4500启动。以后手动重现可在新空目录启动：

```powershell
codex app-server --listen ws://127.0.0.1:4500
```

不要监听公网地址。Demo未建设多用户设备配对与本地连接鉴权，不能用作正式部署。

在frontend目录运行协议验证（仅连接本地，不调用AI）：

```powershell
node tests/codex-direct-probe.cjs
```

页面复用现有主题；无新依赖、无后端业务/数据库变化。构建包含独立的codex-demo.html入口。

验证：本地协议检查成功复现403；Demo HTTP入口200；前端37项测试、类型/ESLint/格式及build通过，两份HTML会话回归通过。浏览器自动化仍被 `unsupported Codex auth method: apikey` 阻断，未完成视觉实点，未把Node协议结果称为浏览器实测。

## 后续边界

当前路径不能继续验证总/功能会话的创建和恢复。需要用户决定是否允许一个经过身份校验、限制操作范围的本地连接层，通过官方stdio接口连接CLI。不能用剥除Origin或关闭浏览器安全限制作为解决方案。

参考：https://learn.chatgpt.com/docs/app-server （WebSocket listener拒绝携带Origin的请求）。
