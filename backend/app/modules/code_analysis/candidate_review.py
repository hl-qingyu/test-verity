"""Saved candidate review; permissions and report validation remain module-owned."""

from datetime import UTC, datetime

from app.core.errors import AppError
from app.modules.candidate_results import service as candidates
from app.modules.code_analysis import artifacts, contract, service, sources
from app.modules.requirements.risk_service import json_object


def review(project_id, task_id, actor, db, payload=None):
    row = service.own(project_id, task_id, actor, db, lock=payload is not None)
    if row.actor_id != actor.id:
        raise AppError(403, "candidate_review_owner_only")
    metadata = row.metadata_snapshot or {}
    if row.status in service.ACTIVE or metadata.get("origin") != "AI":
        raise AppError(422, "candidate_review_not_ready")
    try:
        original = artifacts.candidate_path(task_id).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AppError(404, "code_candidate_not_found") from None
    if payload and not candidates.replay(metadata, payload):
        if row.status != "FAILED":
            raise AppError(409, "candidate_review_not_ready")
        sources.recheck(
            project_id, metadata, actor, db, shared_snapshot=metadata.get("shared_snapshot", False)
        )
        data = service.parse(contract.AnalysisInput, row.input_snapshot)

        def validate(raw):
            output = service.parse(contract.Report, json_object(raw))
            output, corrections = contract.normalize_code_evidence(data, output)
            contract.validate_report(data, output)
            return output.model_dump(by_alias=True), corrections

        result, updated, error = candidates.evaluate(
            "code_analysis",
            task_id,
            original,
            metadata,
            payload,
            actor.id,
            validate,
            previous_error=row.error_code,
        )
        if result is not None:
            row.report, corrections = result
            updated["evidence_corrections"] = corrections
            updated["revalidation"] = {"actor_id": actor.id, "at": datetime.now(UTC).isoformat()}
            row.status, row.error_code = "COMPLETED", ""
        else:
            row.error_code = error
        row.metadata_snapshot = updated
        row.updated_at = datetime.now(UTC)
        row.revision += 1
        db.commit()
    return {
        **candidates.view(
            "code_analysis",
            task_id,
            original,
            row.metadata_snapshot,
            row.error_code,
            can_edit=row.status == "FAILED",
        ),
        "published": row.status == "COMPLETED",
    }
