from sqlalchemy import literal, select

from app.db.models import (
    RequirementManualRisk,
    RequirementRiskAnalysis,
    RequirementRiskReport,
    UserAccount,
)
from app.modules.documents.service import access
from app.modules.projects.analysis_summary import item_counts, keys, record, states


def project_summary(project_id, actor, db):
    access(project_id, actor, db)
    report = RequirementRiskReport
    reports = {}
    query = (
        select(
            report.id,
            report.title,
            report.created_at,
            UserAccount.display_name.label("actor"),
            keys(report.report, "$.risks[*].key").label("keys"),
            states(report.handling).label("handling"),
            report.report["outcome"].astext.label("outcome"),
        )
        .outerjoin(UserAccount, UserAccount.id == report.created_by)
        .where(report.project_id == project_id, report.deleted_at.is_(None))
    )
    for row in db.execute(query).mappings():
        counts = {
            f"risks:{state}": count
            for state, count in item_counts(row["keys"], row["handling"], "PENDING").items()
        }
        item = record(
            {**row, "status": "COMPLETED", "origin": "IMPORT"},
            "requirements",
            counts,
            outcome=row["outcome"],
        )
        item["record_type"] = "report"
        reports[row["id"]] = item
    for report_id, state in db.execute(
        select(RequirementManualRisk.report_id, RequirementManualRisk.status)
        .join(report, report.id == RequirementManualRisk.report_id)
        .where(report.project_id == project_id, report.deleted_at.is_(None))
    ):
        if report_id in reports:
            counts = reports[report_id]["counts"]
            key = f"risks:{state}"
            counts[key] = counts.get(key, 0) + 1
    task = RequirementRiskAnalysis
    query = (
        select(
            task.id,
            task.title,
            task.status,
            task.created_at,
            task.report_id,
            UserAccount.display_name.label("actor"),
            literal("AI").label("origin"),
        )
        .outerjoin(UserAccount, UserAccount.id == task.actor_id)
        .where(task.project_id == project_id, task.deleted_at.is_(None))
        .order_by(task.created_at.desc(), task.id.desc())
    )
    result, linked = [], set()
    for row in db.execute(query).mappings():
        related = reports.get(row["report_id"])
        item = record(row, "requirements", {}, outcome=related["outcome"] if related else None)
        if related:
            item["record_type"], item["record_id"] = "report", row["report_id"]
            if row["report_id"] not in linked:
                item["counts"] = related["counts"]
                linked.add(row["report_id"])
            else:
                continue
        result.append(item)
    result.extend(item for report_id, item in reports.items() if report_id not in linked)
    return result
