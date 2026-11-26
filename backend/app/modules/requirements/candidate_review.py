"""Review immutable requirement-analysis candidates without invoking a model."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import RequirementRiskAnalysis
from app.modules.candidate_results import service as candidates
from app.modules.documents import service as documents
from app.modules.projects.record_deletion import require_visible
from app.modules.requirements import artifacts, risk_service
from app.modules.requirements import risk_analysis_service as service


def review(project_id, task_id, actor, db, payload=None):
    documents.access(project_id, actor, db, lock=payload is not None)
    query = (
        select(RequirementRiskAnalysis)
        .where(
            RequirementRiskAnalysis.id == task_id, RequirementRiskAnalysis.project_id == project_id
        )
        .execution_options(populate_existing=True)
    )
    row = db.scalar(query.with_for_update() if payload else query)
    require_visible(row)
    if row is None:
        raise AppError(404, "risk_analysis_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "candidate_review_owner_only")
    if row.status in service.ACTIVE or not row.context.get("input"):
        raise AppError(422, "candidate_review_not_ready")
    try:
        original = artifacts.candidate_path(task_id).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AppError(404, "risk_candidate_not_found") from None
    if payload and not candidates.replay(row.context, payload):
        if row.status != "FAILED":
            raise AppError(409, "candidate_review_not_ready")
        service.frozen_materials(project_id, row, actor, db)
        data = service.candidate_input(row.context)

        def validate(raw):
            return risk_service.validate_candidate(raw, data, project_id)

        result, updated, error = candidates.evaluate(
            "requirements",
            task_id,
            original,
            row.context,
            payload,
            actor.id,
            validate,
            previous_error=row.error_code,
        )
        if result is not None:
            output, corrections, comparison, warnings = result
            saved = risk_service.store_report(
                project_id,
                row.title,
                "input.json",
                "risk-report.json",
                data,
                output,
                row.context["bindings"],
                actor,
                db,
                commit=False,
            )
            row.report_id = saved["id"]
            updated.update(
                comparison_text_corrections=comparison,
                function_risk_corrections=corrections,
                review_warnings=warnings,
                revalidation={
                    "actor_id": actor.id,
                    "at": datetime.now(UTC).isoformat(),
                    "contract_version": data["contract_version"],
                },
            )
            row.status, row.error_code = "COMPLETED", ""
        else:
            row.error_code = error
        row.context = updated
        row.updated_at = datetime.now(UTC)
        db.commit()
    return {
        **candidates.view(
            "requirements",
            task_id,
            original,
            row.context,
            row.error_code,
            can_edit=row.status == "FAILED",
        ),
        "published": row.status == "COMPLETED",
    }
