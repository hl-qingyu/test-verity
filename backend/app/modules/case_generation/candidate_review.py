"""Human correction of saved response candidates. Never calls AI or applies library cases."""

import copy
from datetime import UTC, datetime

from app.core.errors import AppError
from app.db.models import CaseGenerationBatch
from app.modules.case_generation import delivery, delivery_files, service, sources


def resolve(project_id, run_id, batch_id, issue_id, payload, actor, db):
    run = service.own(project_id, run_id, actor, db, True)
    batch = db.get(CaseGenerationBatch, batch_id, with_for_update=True, populate_existing=True)
    if not batch or batch.run_id != run.id or batch.actor_id != actor.id:
        raise AppError(403, "generation_owner_only")
    saved = delivery_files.read(batch)
    if not saved:
        raise AppError(404, "generation_candidate_issue_not_found")
    identity = str(payload.request_id)
    historical = delivery_files.current_attempt(batch).get("candidate_delivery_history", [])
    previous = [
        delivery_files.read(batch, entry)
        for entry in historical
        if entry.get("resolution_request_id") == identity
    ]
    for record in (saved, *previous):
        if record.get("audit", {}).get("request_id") == identity:
            prior = record.get("resolutions", {}).get(issue_id, {})
            if (
                record["audit"].get("issue_id") != issue_id
                or prior.get("reason") != payload.reason
                or prior.get("ignored") != payload.ignored
                or prior.get("corrected_json", "")
                != ("" if payload.ignored else payload.corrected_json)
            ):
                raise AppError(409, "generation_request_conflict")
            return service.projection(run, actor, db)
    if payload.revision != run.revision:
        raise AppError(409, "generation_changed")
    if batch.status not in ("FAILED", "COMPLETED") or run.status in service.ACTIVE:
        raise AppError(409, "generation_changed")
    problem = next((i for i in saved["issues"] if i["key"] == issue_id), None)
    if not problem:
        raise AppError(404, "generation_candidate_issue_not_found")
    if problem["status"] == "RESOLVED":
        raise AppError(409, "generation_candidate_already_resolved")
    sources.recheck(project_id, run.metadata_snapshot, actor, db)
    path = delivery_files.folder() / f"batch-{batch.id}-{batch.request_id}.txt"
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AppError(404, "generation_candidate_unavailable") from None
    resolutions = copy.deepcopy(saved.get("resolutions", {}))
    resolutions[issue_id] = {
        "ignored": payload.ignored,
        "corrected_json": "" if payload.ignored else payload.corrected_json,
        "reason": payload.reason,
    }
    result = delivery.process(
        batch.input_snapshot,
        raw,
        resolutions,
        preserve_partition=bool(batch.report.get("source_indices")),
    )
    updated = next((i for i in result.issues if i["key"] == issue_id), None)
    if not payload.ignored and (not result.report or (updated and updated["status"] != "RESOLVED")):
        raise AppError(422, "generation_candidate_fix_invalid")
    # Valid suggestions already reviewed must keep the same identities and contents.
    before = {s["key"]: s for s in batch.report.get("suggestions", [])}
    after = {s["key"]: s for s in (result.report or {}).get("suggestions", [])}
    if any(after.get(key) != value for key, value in before.items()):
        raise AppError(409, "generation_candidate_prior_result_changed")
    delivery_files.save(
        batch,
        result,
        resolutions=resolutions,
        audit={
            "request_id": identity,
            "issue_id": issue_id,
            "actor_id": actor.id,
            "at": datetime.now(UTC).isoformat(),
            "action": "IGNORE" if payload.ignored else "CORRECT",
            "reason": payload.reason,
            "previous_artifact": delivery_files.current_attempt(batch).get("candidate_delivery"),
        },
    )
    batch.report = result.report or {}
    batch.status = "COMPLETED" if result.report else "FAILED"
    batch.error_code = "" if result.report else result.error_code
    batch.updated_at = datetime.now(UTC)
    run.revision += 1
    # The response operation is finished even when some candidates remain unresolved.
    all_batches = service.batches(run, db)
    run.status = "COMPLETED" if any(b.status == "COMPLETED" for b in all_batches) else "FAILED"
    run.updated_at = datetime.now(UTC)
    db.commit()
    return service.projection(run, actor, db)
