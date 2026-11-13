from sqlalchemy import select

from app.db.models import CaseAnalysisApplication, CaseAnalysisRun
from app.modules.documents.service import access
from app.modules.projects.analysis_summary import item_counts, keys, metadata, record, states


def project_summary(project_id, actor, db):
    access(project_id, actor, db)
    model = CaseAnalysisRun
    query = metadata(model, project_id).add_columns(
        keys(model.report, "$.findings[*].key").label("findings"),
        keys(model.report, "$.notes[*].key").label("notes"),
        keys(model.handling, "$.manual[*].key").label("manual"),
        states(model.handling, "state").label("handling"),
        keys(model.report, "$.checked_case_ids[*]").label("checked"),
        keys(model.input_snapshot, "$.cases[*].id").label("cases"),
        model.report["complete"].as_boolean().label("complete"),
    )
    result = []
    for row in db.execute(query).mappings():
        done = row["status"] == "COMPLETED"
        counts = (
            item_counts(
                [*(row["findings"] or []), *(row["notes"] or []), *(row["manual"] or [])],
                row["handling"],
                "待确认",
            )
            if done
            else {}
        )
        result.append(
            record(
                row,
                "coverage",
                {f"findings:{state}": count for state, count in counts.items()},
                outcome=(
                    "COMPLETE"
                    if row["complete"] and set(row["checked"] or []) == set(row["cases"] or [])
                    else "PARTIAL"
                )
                if done
                else None,
            )
        )
    failed, succeeded = {}, {}
    app = CaseAnalysisApplication
    for run_id, failures, successes in db.execute(
        select(
            app.run_id,
            keys(app.items, '$[*] ? (@.status == "FAILED").key'),
            keys(app.items, '$[*] ? (@.status == "SUCCESS").key'),
        ).where(app.project_id == project_id)
    ):
        failed.setdefault(run_id, set()).update(failures or [])
        succeeded.setdefault(run_id, set()).update(successes or [])
    for item in result:
        item["application_failed"] = bool(
            failed.get(item["record_id"], set()) - succeeded.get(item["record_id"], set())
        )
    return result
