# 用例生成简化输出契约 v3

2026-10-26 · Skill 2.1.1。新任务使用 CASE_GENERATION 契约3；历史契约2见 [legacy-contract.md](legacy-contract.md)，旧固定输入/指令/报告不重写，旧严格校验按原版本保留。本文只规定模型输出，平台固定输入和来源绑定继续保存完整版本信息。

## 输入

调用方提供完整所选需求/原型正文、对应及公共批注，按资料和页面标题保持边界；提供 snapshot_ref、侧别、功能范围、关注点、已确认结论及 decision_ref，需要比较时提供选定用例的 case_ref 和固定设计。保留旧新配对/增量关系和补生成范围。无已有用例时为空，不要求前置AI规则提取，也不按文本行数限定业务任务。

材料引用只允许真实 snapshot_ref；人工结论引用只允许经平台核实有效的 decision_ref。当前材料指 side=CURRENT 的需求或原型实际正文，不能用旧材料、用例、代码或报告线索单独充当当前业务依据。

## 模型只返回一个 JSON 对象

```json
{
  "cases": [
    {
      "action": "NEW",
      "target": null,
      "design": {
        "module": "订单",
        "structure": "取消订单",
        "case_type": "业务流程",
        "priority": "P1",
        "description": "验证取消待处理订单后释放本订单占用库存。",
        "title": "取消待处理订单后，订单变为已取消并释放占用库存",
        "preconditions": "当前账号有权取消该订单；该订单为待处理，且占用库存。",
        "steps": "1. 打开该待处理订单的详情。\n2. 取消该订单。\n3. 查看该订单的状态和库存占用数量。",
        "expected": "1. 该订单状态变为‘已取消’。\n2. 该订单占用的库存已释放。",
        "data_requirements": "准备有权取消订单的账号和一条占用库存的待处理订单。",
        "remark": "执行前需确认库存占用数量的查看位置和权限。优先级为AI建议，待人工审核：P1，取消订单涉及重要状态和库存占用，属于重要业务操作；影响范围待核对。"
      },
      "sources": ["M1-current"],
      "evidence_quotes": [{"source": "M1-current", "quote": "门店操作员在订单详情页取消“待处理”订单，订单状态变为“已取消”，并释放该订单占用库存"}],
      "note": ""
    }
  ],
  "notes": [
    {
      "kind": "EXECUTION_SETUP",
      "text": "取消订单用例执行前需确认：在哪里查看该订单的库存占用数量，以及查看所需的权限。",
      "sources": ["M1-current"]
    }
  ],
  "complete": true
}
```

cases、notes、complete 必需。cases/notes 可为空；无可用正文或业务预期时不造占位用例，说明原因且 complete=false。不要返回 Markdown、外围解释或额外分析结构。

| 字段 | 约定 |
| --- | --- |
| action | NEW、REUSE、UPDATE、RETIRE |
| target | NEW 为 null；其余必须是选入的真实 case_ref，例如 case-1；不能按展示编号猜目标 |
| design | 仅下方12个设计字段；Skill要求NEW提供title、steps、expected及structure、case_type、priority、description非空字符串；UPDATE仅提供必要变化并保留已有人工字段；REUSE/RETIRE可省略 |
| sources | 非空字符串数组，至少一个有效当前材料或确认结论；仅合法引用，不要求精确摘录/片段覆盖 |
| evidence_quotes | 本条需求/原型文字证据摘录数组，通常1–2条；每条仅source和quote，source必须为本条sources中的需求或原型snapshot_ref。生成时准确摘取该固定正文/批注中的连续原文，不用用例描述或改写摘要代替。平台最多5条、每条最多1000字符，新Skill建议每条≤300字符；匹配与未匹配时的保存方式见下方“保存、审核和历史”。旧响应缺此字段保持兼容；没有可摘录文字时可为空并说明 |
| note | 可省略，简短原因、比较边界或人工改动待核对，不重复分析正文 |
| notes[].kind | BUSINESS_QUESTION：缺决定性业务预期；EXECUTION_SETUP：账号/数据/权限/观察方法待补；UNFINISHED：确实未完成范围 |
| notes[].text / sources | 简短说明及有效来源引用；说明具体受影响范围，不能泛写尚未建模 |
| complete | AI对本次范围的完成声明，不是平台证明；有 BUSINESS_QUESTION/UNFINISHED 必须 false；仅 EXECUTION_SETUP 可 true |

design 仅包含字符串字段：module、structure、case_type、priority、description、title、preconditions、steps、expected、remark、data_requirements、cleanup。新版Skill生成NEW时priority必须选择P0–P4；测试优先级未明确时提出待审核建议并在remark注明理由。structure写子功能/业务操作，case_type写验证类型，description写业务场景/目的，不与具体title混为同一字段。

priority具体等级和判断顺序按同时提供的[优先级规则](references/priority.md)：明确项目规则优先，其次核对失败后果、业务路径、已知影响与恢复方式，按P0–P4选择有依据的等级。P0需要核心主流程/重大后果依据，类型/关键词/执行准备不单独决定等级；缺影响信息可给暂定建议并在remark说明。优先级为测试顺序建议，不等于缺陷严重度、已测试结果或发布决定。

平台兼容保存仍允许priority为空及历史NEW字段缺失，并将缺失字段保留为空，不新增拒绝保存门槛或擅自填默认值；title、steps、expected仍执行原必需校验。这是保存兼容边界，不是新版Skill可以省略四字段的指令。UPDATE省略字段保留目标当前值，空字符串是明确清空；不为补齐新增字段而覆盖人工值。平台由固定当前版本生成差异补丁，不要求模型重复before或全部未改字段。

12设计字段中的10列映射既有14列；序号、正式编号、测试结果和人员由平台管理。data_requirements/cleanup 保留详情和JSON，不新增第15列，也不要求步骤与预期行数相等。

文字按同时提供的[字段与表达规则](references/fields-and-language.md)编写：标题点明条件和结果，步骤写具体操作，预期写可检查的表现或变化，准备缺口写清执行前要补什么。此为生成质量要求，不改变JSON结构，也不以固定措辞拒绝保存AI响应。

## 保存、审核和历史

平台按固定材料核对新摘录，唯一匹配时关联保存位置，多个相同位置不猜测精确段落。契约3中的摘录未逐字匹配时，保留AI返回的quote，标为“AI摘录（待核对）”，不作为已核对原文或业务正确性证明，也不因此阻止其他结构和身份校验通过的完整候选保存。平台不模糊替换文字、不把摘录改绑到其他资料、不替模型补字；是否支持本条业务预期仍由人工对照固定来源审阅。提示只反映摘录匹配状态，不新增业务待确认事项、改变模型的complete声明或自动发起补生成。

来源仍须属于本条sources、指向输入真实的需求/原型材料，并通过既有结构、字段类型/长度、项目权限及目标身份校验。无效来源、资料类型或身份不能借“待核对”通过；只有逐字匹配从保存门槛改为提示。历史契约2仍按原严格规则读取和校验。原始响应先保存，旧成功报告和固定指令不改写，不额外调用AI总结；旧报告仅资料级引用时继续明确提示缺本条摘录。

平台保留完整原始响应，校验基本结构、字段/长度、真实项目来源和目标身份。无歧义的格式差异可规范化并审计；不修补业务预期、目标或引用。规范化后的待审阅建议key、补丁、来源映射、人工审核和应用信息由平台生成，不由AI填写。

业务规则明确而准备待补可保存设计；业务冲突/决定缺失不写确定预期。生成或 complete=true 不等于审核、入库或测试通过。人工草稿、澄清和逐条应用保持独立；旧报告继续可读，严格契约2导入不套用简化v3校验，固定输入重试仍使用当时指令。
