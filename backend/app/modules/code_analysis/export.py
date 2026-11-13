"""Export one complete record independently of UI pagination/filters."""

import json

from app.core.errors import AppError
from app.modules.code_analysis import artifacts, service

TARGETS = {
    "BUG": "代码Bug",
    "REQUIREMENT_DEVIATION": "需求符合性",
    "FRONTEND_BACKEND_MISMATCH": "前后端一致性",
}


def candidate(project_id, task_id, actor, db):
    row = service.own(project_id, task_id, actor, db)
    if row.metadata_snapshot.get("origin") != "AI" or row.status in service.ACTIVE:
        raise AppError(404, "code_candidate_not_found")
    path = artifacts.candidate_path(task_id)
    if not path.is_file():
        raise AppError(404, "code_candidate_not_found")
    return path


def download(project_id, task_id, format, actor, db):
    row = service.own(project_id, task_id, actor, db)
    if row.status != "COMPLETED" or row.report.get("contract_version") != 2:
        raise AppError(422, "code_report_not_ready")
    if format in ("input", "report"):
        value = row.input_snapshot if format == "input" else row.report
        return json.dumps(value, ensure_ascii=False, indent=2).encode(), "application/json", "json"
    report = row.report
    lines = [
        f"# {row.title}",
        "",
        "> 固定输入的静态代码分析，未运行验证；人工处理不代表测试通过。",
        "",
        report["summary"]["conclusion"],
        "",
        "## 检查目标",
    ]
    for target in report["target_results"]:
        lines.extend([f"- {TARGETS[target['target']]}：{target['status']}；{target['scope']}"])
    lines.extend(["", "## 固定来源"])
    for source in row.input_snapshot["sources"]:
        lines.extend(
            [
                f"- {source['name']} · {source['source_kind']} · {source['repository_kind']}"
                f" · {source['snapshot_ref']}"
            ]
        )
    for finding in report["findings"]:
        lines.extend(
            [
                "",
                f"## {finding['key']} · {finding['title']}",
                f"{finding['severity']} · {finding['evidence_state']}",
            ]
        )
        for title, key in (("触发条件", "trigger"), ("实际行为", "actual"), ("影响范围", "impact")):
            lines.extend(["", f"### {title}", finding[key]])
        for view in finding["target_views"]:
            lines.extend(
                [
                    "",
                    f"### {TARGETS[view['target']]}",
                    f"预期：{view['expected']}",
                    f"依据：{view['basis']}",
                    view["explanation"],
                ]
            )
            for comparison in view["comparison_rows"]:
                lines.append(
                    f"- {comparison['label']}：{comparison['left']['statement']}"
                    f" → {comparison['right']['statement']}"
                )
        for title, key in (("修复建议", "fix_suggestion"), ("验证建议", "verification_suggestion")):
            lines.extend(["", f"### {title}", finding[key]])
        for missing in finding["missing_evidence"]:
            lines.append(f"待补充：{missing['needed']}；{missing['reason']}；{missing['effect']}")
        handling = row.handling.get(finding["key"], {})
        lines.extend(
            ["", f"人工处理：{handling.get('status', 'PENDING')}；{handling.get('note', '')}"]
        )
    lines.extend(["", "## 固定证据"])
    source_map = {s["source_id"]: s for s in row.input_snapshot["sources"]}
    for evidence in report["evidence"]:
        if evidence["kind"] == "CODE":
            source = source_map[evidence["source_id"]]
            file = next(f for f in source["files"] if f["file_id"] == evidence["file_id"])
            location = (
                f"{source['name']} / {file['path']}"
                f" L{evidence['start_line']}-L{evidence['end_line']}"
            )
        else:
            location = f"资料 {evidence['source_id']} / {evidence['segment_id']}"
        lines.extend(
            [
                "",
                f"### {evidence['key']} · {location}",
                evidence["observation"],
                "",
                *["    " + line for line in evidence["excerpt"].splitlines()],
            ]
        )
    lines.extend(["", "## 调用关系"])
    for chain in report["chains"]:
        lines.append(f"- {chain['key']}：" + " → ".join(n["label"] for n in chain["nodes"]))
        lines.extend(
            f"  - {edge['from']} → {edge['to']} · {edge['relation']}：{edge['note']}"
            for edge in chain["edges"]
        )
    lines.extend(["", "## 范围与限制"])
    lines.extend(f"- {item['detail']}：{item['effect']}" for item in report["limitations"])
    return "\n".join(lines).encode(), "text/markdown", "md"
