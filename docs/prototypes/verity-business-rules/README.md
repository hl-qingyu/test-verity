# 总原型业务规则说明栏

总原型为项目根目录的 [verity-prototype.html](../../../verity-prototype.html)。后续页面、弹窗、交互和业务说明都在此文件修改，不再写回项目外旧文件。`docs/prototypes/verity-requirement-risk-review.html` 仅作为审阅副本。

说明栏维护源在本目录；更新时以根目录主文件为准，再按需同步审阅副本。总原型不依赖外部脚本或真实业务数据。

覆盖13个菜单页、51组操作规则：新建分析、输入准备与确认、历史版本、来源读取、导入导出、人工处理、审核应用、重复处理、失败修订、取消重试、分组迁移、启停及删除等。每组规则分别列出条件、字段/数量限制、数据影响和失败边界。右栏不显示实现入口；代码追溯记录保留在 [RULES.md](RULES.md) 与 `catalog.json` 的 sources 字段。

规则来自当前前后端代码核对，并非运行时自动推导。业务代码变化后应重新核对相关规则，不能仅重新运行生成器就宣称已经同步业务。

说明采用业务用语：一条写清一个要求，字段和状态名称用中文，不展示程序字段名或状态码。保留具体限制、操作条件和处理结果；产品名、文件后缀和实际文件名沿用原名。

在仓库根目录执行：

```powershell
python docs/prototypes/verity-business-rules/build_catalog.py
node docs/prototypes/verity-business-rules/sync.cjs
node docs/prototypes/verity-business-rules/verify.cjs
```

`build_catalog.py` 维护结构化规则；`runtime.js` 根据当前页面、弹窗标题、表单ID和弹窗上下文定位规则，提供搜索与展开收起；`styles.css` 管理右栏及窄屏布局。说明栏不调用业务接口，不读写业务存储，不触发AI。弹窗打开时说明栏挂入当前模态框并以手动popover置于顶层，以免被模态背景禁用或裁剪。

同步脚本仅替换自己的样式/脚本块，保留业务原型其他内容；首次修改前备份至 `outputs/business-rules-detailed-before-20261113/`。离线验证覆盖22个具体弹窗定位场景、两份原型同步、脚本语法和来源路径。

本轮前端check/build及UI控件检查通过。浏览器工具拒绝访问本地file协议原型，未完成实际截图、窄屏、键盘/焦点及popover视觉验收；离线检查不能代替这些验收。
