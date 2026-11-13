from app.db.models import CodeAnalysisTask
from app.modules.documents.service import access
from app.modules.projects.analysis_summary import item_counts, keys, metadata, record, states


def project_summary(project_id, actor, db):
    access(project_id, actor, db)
    model = CodeAnalysisTask
    query = metadata(model, project_id).add_columns(
        keys(model.report, "$.findings[*].key").label("keys"),
        states(model.handling).label("handling"),
        model.report["outcome"].astext.label("outcome"),
    )
    return [
        record(
            row,
            "code",
            {
                f"findings:{state}": count
                for state, count in item_counts(row["keys"], row["handling"], "PENDING").items()
            }
            if row["status"] == "COMPLETED"
            else {},
            outcome=row["outcome"],
        )
        for row in db.execute(query).mappings()
    ]
