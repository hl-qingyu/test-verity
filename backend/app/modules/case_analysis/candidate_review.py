"""Expose and resolve saved case-analysis candidates without model calls."""

from datetime import UTC, datetime

from app.core.errors import AppError
from app.core.json_data import json_object
from app.modules.candidate_results import service as candidates
from app.modules.case_analysis import contract, service
from app.modules.case_generation import sources


def review(project_id, run_id, actor, db, payload=None):
    row = service.own(project_id, run_id, actor, db, lock=payload is not None)
    if row.actor_id != actor.id:
        raise AppError(403, "candidate_review_owner_only")
    original = next(
        (
            entry["raw_response"]
            for entry in reversed(row.attempts or [])
            if entry.get("raw_response")
        ),
        "",
    )
    if row.status in service.ACTIVE or not original:
        raise AppError(404, "candidate_review_not_ready")
    if payload and not candidates.replay(row.metadata_snapshot, payload):
        if row.status != "FAILED":
            raise AppError(409, "candidate_review_not_ready")
        sources.recheck(project_id, row.metadata_snapshot, actor, db)
        result, metadata, error = candidates.evaluate(
            "case_analysis",
            run_id,
            original,
            row.metadata_snapshot,
            payload,
            actor.id,
            lambda raw: contract.validate(
                row.input_snapshot, json_object(raw, "case_analysis_invalid")
            ),
            previous_error=row.error_code,
        )
        if result is not None:
            row.report = result
            row.status, row.error_code = "COMPLETED", ""
        else:
            row.error_code = error
        row.metadata_snapshot = metadata
        row.revision += 1
        row.updated_at = datetime.now(UTC)
        db.commit()
    return {
        **candidates.view(
            "case_analysis",
            run_id,
            original,
            row.metadata_snapshot,
            row.error_code,
            can_edit=row.status == "FAILED",
        ),
        "published": row.status == "COMPLETED",
    }
