from app.db.models import ChangeAnalysisTask
from app.modules.documents.service import access
from app.modules.projects.analysis_summary import item_counts, keys, metadata, record, states


def project_summary(project_id, actor, db):
    access(project_id, actor, db)
    model = ChangeAnalysisTask
    query = metadata(model, project_id).add_columns(
        *[
            keys(model.report, f"$.{group}[*].key").label(group)
            for group in (
                "function_impacts",
                "code_impacts",
                "case_impacts",
                "risks",
                "historical_reviews",
                "regression_scope",
            )
        ],
        states(model.handling).label("handling"),
        model.report["outcome"].astext.label("outcome"),
    )
    result = []
    for row in db.execute(query).mappings():
        counts = {}
        if row["status"] == "COMPLETED":
            findings = [
                key
                for group in (
                    "function_impacts",
                    "code_impacts",
                    "case_impacts",
                    "risks",
                    "historical_reviews",
                )
                for key in row[group] or []
            ]
            for group, ids in (("impacts", findings), ("regressions", row["regression_scope"])):
                counts.update(
                    {
                        f"{group}:{state}": count
                        for state, count in item_counts(ids, row["handling"], "PENDING").items()
                    }
                )
        result.append(record(row, "changes", counts, outcome=row["outcome"]))
    return result
