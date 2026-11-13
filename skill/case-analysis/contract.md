# CASE_REVIEW 契约1

输入包含type=CASE_REVIEW、contract_version=1、project_id、request_id、mode、scope、focus、完整materials（source_id/name/version/segments.text及location）、cases（id/number/version/lifecycle和12设计字段）。用例ID是内部身份，展示number可重复。

输出仅findings、notes、checked_case_ids、complete。findings为MISMATCH不符合需求、MISSING本次范围缺失、QUALITY设计质量；notes为SETUP执行准备/未完成说明、QUESTION业务待澄清。没有问题可空数组。

每项字段：key（报告内唯一）、kind、title、severity（高/中/低）、reason（等级理由）、description、impact、suggestion、case_ids（输入内部ID数组，缺失场景为空）、fields（相关设计字段数组）、evidence（source与quote数组）。字段名称为module/structure/case_type/priority/description/title/preconditions/steps/expected/remark/data_requirements/cleanup。

英文仅用于JSON结构和fields定位，读者说明用中文名称和简短句子。例如fields=["preconditions","expected"]，description写“前置条件缺少订单状态，预期结果也没有说明核销记录是否增加”。正文不堆平台字段名或内部ID；实际资料原文和业务名不改写。文字表达要求不新增拒绝历史合法报告的硬校验。

checked_case_ids仅输入中实际检查的唯一ID。complete为AI范围声明，平台与人工还需核对，不能称覆盖已证明。引用不存在或原文不匹配不得编造。草案与审核结果由平台人工界面保存，不要求模型返回入库指令。

图片/PDF附件仅有视觉证据时，evidence使用source与observation，不填写quote。observation是AI观察、待人工核对，不是连续原文；平台核对该来源确有已固定且实际发送的附件。文字来源继续使用quote，二者只选一个。
