from collections import defaultdict

from sqlalchemy import select

from app.db.models import CaseGenerationBatch, CaseGenerationRun
from app.modules.documents.service import access
from app.modules.projects.analysis_summary import keys, metadata, record, states


def project_summary(project_id, actor, db):
    access(project_id, actor, db)
    model = CaseGenerationRun
    query = metadata(model, project_id).add_columns(
        states(model.handling["suggestions"], history=True).label("handling"),
        keys(model.handling, "$.manual_suggestions.*.suggestion.key").label("manual"),
        keys(model.handling, "$.decisions[*].questionKey").label("decided"),
        keys(model.handling, "$.failures[*].key").label("failures"),
    )
    batch = CaseGenerationBatch
    by_run = defaultdict(list)
    for row in db.execute(
        select(
            batch.run_id,
            batch.status,
            keys(batch.report, "$.suggestions[*].key").label("suggestions"),
            keys(batch.report, "$.requirement_questions[*].key").label("questions"),
            batch.report["outcome"].astext.label("outcome"),
        )
        .join(model, model.id == batch.run_id)
        .where(model.project_id == project_id, model.deleted_at.is_(None))
    ).mappings():
        by_run[row["run_id"]].append(row)
    result = []
    for row in db.execute(query).mappings():
        batches = by_run[row["id"]]
        suggestions, questions = set(row["manual"] or []), set()
        for b in batches:
            if b["status"] == "COMPLETED":
                suggestions.update(b["suggestions"] or [])
                questions.update(b["questions"] or [])
        handled = row["handling"] or {}
        successful = {key for key, state in handled.items() if state in {"已应用", "已复用"}}
        waiting = {
            key for key in suggestions if handled.get(key) not in {"已应用", "已复用", "已忽略"}
        }
        counts = {
            "suggestions:PENDING": int(bool(waiting)),
            "questions:PENDING": int(bool(questions - set(row["decided"] or []))),
        }
        # Complete needs the original module's collision checks; a metadata summary cannot prove it.
        outcome = (
            "PARTIAL"
            if any(b["status"] == "COMPLETED" for b in batches)
            and any(b["status"] != "COMPLETED" or b["outcome"] != "COMPLETE" for b in batches)
            else None
        )
        item = record(row, "generate", counts, outcome=outcome)
        item["application_failed"] = bool(set(row["failures"] or []) - successful)
        result.append(item)
    return result
