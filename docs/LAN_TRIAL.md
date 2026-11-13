# 同 Wi-Fi 临时 HTTP 试用

<!-- document-status:start -->
> **专项运行参考，使用前核对实际环境。** 仅局域网临时试用时查阅，不是正式部署方案。 查阅分类见[文档整理清单](DOCUMENT_REVIEW.md)。
<!-- document-status:end -->

2026-10-16 用户明确允许暂不考虑 HTTPS 加密，仅供同事试用。2026-10-19 新增无证书服务启动脚本，用户明确不需要浏览器启动器。当前示例地址为 `http://192.168.0.63:5173`；每次以脚本实际显示的地址为准。

## 服务启动脚本

在项目根目录的 pwsh 中直接执行，无需手动切换终端或传入启动参数：

```powershell
.\start-lan.ps1
```

如果本机有多个活动网络，脚本会要求明确选择，执行：

```powershell
.\start-lan.ps1 -Address 192.168.0.63
```

`-Address` 只能是本机已激活的局域网 IPv4。脚本复用已有 Python/Node 依赖，不安装依赖或执行数据库迁移，启动步骤为：

1. 自动识别单个具有默认网关的活动网络，或校验明确指定的本机 IP。
2. 保留 `.env` 原凭据、其他配置和已允许来源，追加该 IP 的精确 HTTP 来源，将 `AUTH_COOKIE_SECURE` 设为 `false`；不输出其他配置内容。
3. 复用 `start-dev.ps1 -Lan` 启动 API、单 Worker 和前端。只在本项目前端仍监听本机时重启前端；已有局域网前端、API 和 Worker 不重复启动。其他程序占用端口时拒绝启动，不按端口结束程序。
4. 本机检查局域网入口的数据库就绪状态和登录来源校验，并显示访问 URL。

脚本只启动服务，不打开浏览器或生成浏览器启动器，不更改防火墙或持久执行策略。2026-10-23 针对 pwsh 内 `New-CimSession` / `Get-CimInstance` 的初始化异常增加宿主兼容：在 PowerShell Core 中，脚本会先将自身交给 Windows 自带的 `System32\WindowsPowerShell\v1.0\powershell.exe`，之后的 IP、端口、进程检查和启动流程均在该宿主执行。`-NoProfile`、`-NonInteractive`、`-ExecutionPolicy Bypass`、`-File` 由脚本内部传递，仅对这个子进程生效；可选 `-Address` 原样传递，不递归重启。子进程失败时保留原错误并让外层明确报错。

2026-10-21 曾在 pwsh 7.6.5 直接运行成功；2026-10-23 用户 pwsh 7.6.7 截图出现 CIM 初始化异常，干净子进程没有复现，不能断定为该版本普遍缺陷。现通过固定系统宿主避免依赖调用方的 CIM 加载环境，并已在两种 pwsh 版本下验证入口。若脚本在执行前就被策略阻止，仍不能靠脚本内部代码解除限制。窗口运行结束后服务继续在后台运行，使用原 `stop-dev.ps1` 按需停止；Worker 停止前核对活动任务。

HTTP 仍不提供传输加密；每位试用者的浏览器需按下文设置该地址。访问被阻挡时核对 Windows 防火墙的 Node/TCP 5173 规则和无线客户端隔离，不能以本机检查通过代替跨电脑验证。

脚本只启动服务，不打开浏览器或生成浏览器启动器，不更改防火墙或持久执行策略。PowerShell Core 下，局域网脚本、`start-dev.ps1` 和 `stop-dev.ps1` 都会自动交给 Windows 自带 PowerShell 执行 Windows 网络/进程检查；`-Address`、`-Service`、`-Lan` 参数保持不变，子进程失败会向外报告。`stop-dev.ps1` 会按已核验的项目进程命令结束进程树，并等待对应端口释放，因此同一个停止脚本可停止 `start-lan.ps1` 和 `start-dev.ps1` 启动的前端。原调用方式无需切换终端或增加参数。

## 同事电脑操作

### 历史浏览器启动器（本次不使用）

本机可双击 `outputs/open-lan-trial.cmd`。启动器使用已核对的 `C:\Program Files\Google\Chrome\Application\chrome.exe`，以 `%LOCALAPPDATA%\TestVerityLanTrial` 作为独立试用配置目录，只为 `http://192.168.0.63:5173` 传入 `--unsafely-treat-insecure-origin-as-secure`。该目录与日常 Chrome 的账号、会话、设置独立，需在新窗口登录；不要将自己的配置目录分发给同事。

2026-10-16 用户在原 Chrome 的 flags 操作后仍无法登录，使用此启动器打开新窗口后明确反馈“已能登录”。同事可复制启动器使用，但 Chrome 安装路径和服务器 IP 需与脚本一致；任一变化须更新脚本。启动器由用户手动运行，本轮没有自动更改浏览器全局安全设置。

### 手动设置方式

使用 Chrome：

1. 在地址栏打开 `chrome://flags/#unsafely-treat-insecure-origin-as-secure`。
2. 在 **Insecure origins treated as secure** 中填写且仅填写 `http://192.168.0.63:5173`，设为 **Enabled**。
3. 按页面的 **Relaunch** 重启浏览器，再访问 `http://192.168.0.63:5173`，使用平台账号登录。

注意：**Web Authentication Enterprise Attestation** / `#web-authentication-permit-enterprise-attestation` 是另一项，不用于开放 HTTP 安全上下文。若误启用，应恢复为 **Default**。须核对选项名称和 `#unsafely-treat-insecure-origin-as-secure` 标识；仅刷新业务网页不会使启动参数生效。

这是浏览器提供的开发设置，使指定 HTTP 来源可使用安全上下文 API，并不加密网络传输。当前密码封装、随机编号和本地代码目录能力依赖这些 API，因此每位试用者都要配置。公司浏览器策略可能禁用该设置；不能将未配置客户端视为已验证可用。

试用结束后移除该地址，将选项恢复 **Default** 并重启浏览器。依据：[Chromium 开发测试说明](https://www.chromium.org/Home/chromium-security/deprecating-powerful-features-on-insecure-origins/)。

若使用独立启动器，试用结束后关闭独立窗口，不再使用该启动器。独立目录属于本机浏览器数据，删除前需由用户确认其中是否有要保留的信息。

## 本机配置与运行

- 前端通过原 Vite 入口运行，启动参数为 `--host 0.0.0.0 --port 5173 --strictPort`，同时保留本机访问。
- API 继续只监听 `127.0.0.1:8000`，由原 `/api` 代理访问；后台继续使用单个 `app.chat_worker`。
- 现有 `backend/.env` 的 `AUTH_ALLOWED_ORIGINS` 追加上述精确 HTTP 来源，保留两条原本机来源；`AUTH_COOKIE_SECURE` 保持 `false`。其余配置及原加密密钥保持，不将配置文件写入文档或发布记录。
- WLAN 当前为 Public，已有指向 `D:\nodejs\node.exe` 的 Public 入站允许规则。本次复用现有规则，没有新增或修改防火墙规则。
- 前端输出位于 `log/lan-frontend-20261016.log` 与 `.err.log`，API/Worker 日志沿用 `log/api.log`、`log/chat-worker.log`。

现有 `start-dev.ps1` 和 `npm run dev` 的默认值仍是本机监听。2026-10-19 起优先运行上面的 `start-lan.ps1`。以下是此前的手动前台启动方式：

```powershell
.\start-dev.ps1 -Service api
.\start-dev.ps1 -Service worker
.\stop-dev.ps1 -Service frontend
$trialVite = (Resolve-Path .\frontend\node_modules\vite\bin\vite.js).Path
Set-Location .\frontend
node $trialVite --host 0.0.0.0 --port 5173 --strictPort
```

最后一条为前台运行，需保持终端打开。不要在未核对活动任务时停止 Worker；停止可能中断已计费的调用。

## 恢复仅本机访问

在项目根目录执行：

```powershell
.\stop-dev.ps1 -Service frontend
.\start-dev.ps1 -Service frontend
```

从 `backend/.env` 的 `AUTH_ALLOWED_ORIGINS` 移除本次添加的局域网来源，保留其余配置，再在合适时机仅重启 API。同事浏览器也移除前述开发设置。

若原先通过 HTTPS 使用 `AUTH_COOKIE_SECURE=true`，试用结束后还需恢复该值；脚本不会自动恢复它。已有 API 每次请求读取 Origin/Cookie 配置；若进程另有 `AUTH_*` 环境变量覆盖 `.env`，脚本的实际来源检查会报错，需核对并在合适时机重新启动 API。

## 已验证边界

配置前只读核对数据库所有具有文本 status 的表，`QUEUED`/`RUNNING` 合计为 0；当时 API/Worker 均无本项目进程。仅重启本项目前端并启动 API/Worker，没有新建或重试分析任务。

本机经 `127.0.0.1:5173` 和 `192.168.0.63:5173` 两个入口分别验证：首页和 `/api/health/ready` 为 200，未登录 `/api/auth/me`、`/api/projects` 为 401，精确来源的密码挑战为 200，未授权 Origin 为 403。只读取挑战响应字段，没有实际登录、AI 调用或业务写入。Worker 日志出现新的 `analysis_chat_worker_ready`。

未从另一台电脑验证无线设备互访或浏览器登录，没有代改用户或同事浏览器设置。同 Wi-Fi 仍可能存在访客网络/客户端隔离；电脑休眠、服务退出或地址变化也会影响访问。本次仅运行配置和说明变化，无业务源码、依赖、模型、迁移、前端 UI 或原型变化，未运行与这些未改部分有关的全量测试。

后续登录排障补充：原 `Auth.tsx` 将 Web Crypto 不可用和网络异常都显示为“连接失败”。现仅在该 catch 中区分缺少 `crypto.subtle` 的情况，明确提示浏览器能力与临时设置，真实网络异常仍沿用原提示；不修改密码封装、登录接口或权限。新增合成测试验证缺能力时 0 请求、无登录回调、忙状态释放，以及有能力但网络失败仍显示原网络错误。前端 173 项全量、check 和生产构建通过，构建保留既有 500kB 提示；日志为 `log/lan-login-frontend-{tests,check,build}-20261016.log`。

已通过真实 Chrome 的临时页面提交合成账号复现原提示，并在热更新后确认出现准确环境提示；缺能力的执行没有到达登录接口。默认桌面和 390px 宽度读取均无横向溢出，桌面错误区截图在 `outputs/lan-login-environment-20261016.png`。Chrome 随后断开连接，窄屏截图、临时视口恢复和检查标签主动关闭未完成，不据此声称完整窄屏视觉验收；用户成功登录是其对独立试用窗口的反馈，不是助手代输真实账号的测试，也不证明另一台电脑已登录。
