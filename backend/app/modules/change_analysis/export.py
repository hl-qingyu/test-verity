import json

from sqlalchemy.orm import load_only

from app.core.errors import AppError
from app.db.models import ChangeAnalysisTask
from app.modules.change_analysis import artifacts, service


def candidate(project_id, task_id, actor, db):
    row = service.own(project_id, task_id, actor, db)
    if row.actor_id != actor.id:
        raise AppError(403, "change_candidate_owner_only")
    if row.metadata_snapshot.get("batch_plan") and row.status not in service.ACTIVE:
        candidates = []
        for b in row.metadata_snapshot["batch_plan"]["batches"]:
            origin = (
                db.get(
                    ChangeAnalysisTask,
                    b["candidate_task_id"],
                    options=[
                        load_only(
                            ChangeAnalysisTask.id,
                            ChangeAnalysisTask.actor_id,
                            ChangeAnalysisTask.project_id,
                            ChangeAnalysisTask.deleted_at,
                        )
                    ],
                )
                if b.get("candidate_task_id")
                else None
            )
            if (
                not origin
                or origin.project_id != project_id
                or origin.actor_id != actor.id
                or origin.deleted_at is not None
            ):
                continue
            path = artifacts.batch_candidate_path(origin.id, b["id"])
            if path.is_file():
                try:
                    candidates.append(
                        {
                            "batch_id": b["id"],
                            "task_id": origin.id,
                            "raw_response": path.read_text(encoding="utf-8"),
                        }
                    )
                except (OSError, UnicodeError):
                    raise AppError(503, "change_candidate_storage_unavailable") from None
        if not candidates:
            raise AppError(404, "change_candidate_not_found")
        return artifacts.save_candidate(
            task_id,
            json.dumps(
                {"kind": "CHANGE_BATCH_CANDIDATES", "batches": candidates},
                ensure_ascii=False,
                indent=2,
            ),
        )
    path = artifacts.candidate_path(task_id)
    if (
        row.metadata_snapshot.get("origin") != "AI"
        or not path.is_file()
        or row.status in service.ACTIVE
    ):
        raise AppError(404, "change_candidate_not_found")
    return path


def download(project_id, task_id, format, actor, db):
    row = service.own(project_id, task_id, actor, db)
    if row.status != "COMPLETED":
        raise AppError(422, "change_report_not_ready")
    if format in {"input", "report"}:
        value = row.input_snapshot if format == "input" else row.report
        return json.dumps(value, ensure_ascii=False, indent=2).encode(), "application/json", "json"
    if format != "markdown":
        raise AppError(422, "change_export_invalid")
    lines = [
        f"# {row.title}",
        "",
        "静态变更分析；建议及人工采纳不代表测试通过。",
        "",
        row.report["summary"]["conclusion"],
        row.report["summary"]["inheritance_note"],
    ]
    if row.metadata_snapshot.get("batch_summary"):
        lines.extend(
            [
                "",
                "## 分批执行记录、原批成果与调用审计",
                json.dumps(row.metadata_snapshot["batch_plan"], ensure_ascii=False, indent=2),
            ]
        )
    for group in service.RESULT_GROUPS:
        lines.extend(["", f"## {group}"])
        for item in row.report[group]:
            title = item.get("title", item.get("history_ref", item.get("case_ref", "")))
            lines.extend(
                [
                    "",
                    f"### {item['key']} · {title}",
                    json.dumps(item, ensure_ascii=False, indent=2),
                ]
            )
            if item["key"] in row.handling:
                lines.extend(
                    [
                        "人工处理（独立记录）：",
                        json.dumps(row.handling[item["key"]], ensure_ascii=False, indent=2),
                    ]
                )
    coverage = "platform_coverage" if row.report["contract_version"] == 3 else "coverage"
    for group in ("target_results", coverage, "evidence", "chains", "limitations"):
        lines.extend(
            ["", f"## {group}", json.dumps(row.report[group], ensure_ascii=False, indent=2)]
        )
    lines.extend(
        [
            "",
            "## 固定比较范围",
            json.dumps(row.input_snapshot["comparison_pairs"], ensure_ascii=False, indent=2),
            "",
            "## 固定来源",
            json.dumps(
                [
                    {k: v for k, v in s.items() if k != "units"}
                    for s in row.input_snapshot["snapshots"]
                ],
                ensure_ascii=False,
                indent=2,
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## 固定用例与历史问题快照",
            json.dumps(
                {
                    "cases": row.input_snapshot["cases"],
                    "historical_items": row.input_snapshot["historical_items"],
                    "input_limitations": row.input_snapshot["input_limitations"],
                },
                ensure_ascii=False,
                indent=2,
            ),
        ]
    )
    return "\n".join(lines).encode(), "text/markdown", "md"
