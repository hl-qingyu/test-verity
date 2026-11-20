"""Persistent v3 requirement-risk analysis queue and project access rules."""

import hashlib
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import defer

from app.core.errors import AppError
from app.db.models import (
    DocumentVersion,
    RequirementRiskAnalysis,
    SourceDocument,
    UserAccount,
)
from app.modules.ai import native_terminal
from app.modules.ai.service import (
    analysis_configuration,
    configuration_snapshot,
)
from app.modules.documents import service as documents
from app.modules.projects.record_deletion import require_visible, requirement_permissions
from app.modules.prototypes import directories
from app.modules.requirements import artifacts, risk_schemas, risk_service
from app.modules.skills import files as skill_files

ACTIVE = ("QUEUED", "RUNNING")


def view(
    row: RequirementRiskAnalysis,
    db,
    viewer=None,
    *,
    can_delete=None,
    created_by=None,
    function_risk_corrections=None,
):
    require_visible(row)
    if can_delete is None and viewer:
        can_delete = requirement_permissions(row.project_id, [row], viewer, db)[row.id]
    if created_by is None:
        creator = db.get(UserAccount, row.actor_id)
        created_by = creator.display_name if creator else "已删除账号"
    if function_risk_corrections is None:
        function_risk_corrections = row.context.get("function_risk_corrections", [])
    candidate_available = row.status not in ACTIVE and artifacts.candidate_path(row.id).is_file()
    return {
        "id": row.id,
        "project_id": row.project_id,
        "request_id": row.request_id,
        "retry_of": row.retry_of,
        "title": row.title,
        "focus": row.focus,
        "selections": row.selections,
        "status": row.status,
        "error_code": row.error_code,
        "report_id": row.report_id,
        "ai": native_terminal.public_snapshot(row.ai_config),
        "terminal_available": bool(
            viewer and native_terminal.available(row.ai_config, row.actor_id, viewer.id)
        ),
        "created_by": created_by,
        "can_cancel": bool(viewer and row.actor_id == viewer.id and row.status in ACTIVE),
        "candidate_available": candidate_available,
        "can_delete": bool(can_delete),
        "can_revalidate": bool(
            candidate_available and viewer and row.actor_id == viewer.id and row.status == "FAILED"
        ),
        "function_risk_corrections": function_risk_corrections,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def listing(project_id, actor, db):
    documents.access(project_id, actor, db)
    # Keep the frozen input/Skill in the database during entry and status polling.
    entries = db.execute(
        select(
            RequirementRiskAnalysis,
            UserAccount.display_name,
            RequirementRiskAnalysis.context["function_risk_corrections"],
        )
        .options(defer(RequirementRiskAnalysis.context))
        .outerjoin(UserAccount, UserAccount.id == RequirementRiskAnalysis.actor_id)
        .where(
            RequirementRiskAnalysis.project_id == project_id,
            RequirementRiskAnalysis.deleted_at.is_(None),
        )
        .order_by(RequirementRiskAnalysis.id.desc())
    ).all()
    rows = [row for row, _, _ in entries]
    allowed = requirement_permissions(project_id, rows, actor, db)
    return {
        "items": [
            view(
                row,
                db,
                actor,
                can_delete=allowed[row.id],
                created_by=creator or "已删除账号",
                function_risk_corrections=corrections or [],
            )
            for row, creator, corrections in entries
        ]
    }


def enqueue(project_id, payload, actor, db):
    documents.access(project_id, actor, db, lock=True)
    request_id = str(payload.request_id)
    prior = db.scalar(
        select(RequirementRiskAnalysis).where(
            RequirementRiskAnalysis.project_id == project_id,
            RequirementRiskAnalysis.actor_id == actor.id,
            RequirementRiskAnalysis.request_id == request_id,
        )
    )
    selections = [item.model_dump() for item in payload.selections]
    if prior:
        if (
            prior.title != payload.title
            or prior.focus != payload.focus
            or prior.selections != selections
        ):
            raise AppError(409, "risk_analysis_request_conflict")
        return view(prior, db, actor)
    if payload.retry_of:
        retried = db.scalar(
            select(RequirementRiskAnalysis).where(
                RequirementRiskAnalysis.id == payload.retry_of,
                RequirementRiskAnalysis.project_id == project_id,
                RequirementRiskAnalysis.status.in_(("FAILED", "CANCELLED")),
            )
        )
        require_visible(retried)
        if retried is None:
            raise AppError(422, "risk_analysis_retry_invalid")
        if [
            {
                **item,
                "paths": item.get("paths", []),
                "snapshot": item.get("snapshot", ""),
                "url": item.get("url"),
            }
            for item in retried.selections
        ] != selections:
            raise AppError(422, "risk_analysis_retry_invalid")
        frozen = retried
        visited = set()
        while "input" not in frozen.context and frozen.retry_of:
            if frozen.id in visited:
                raise AppError(422, "risk_analysis_retry_invalid")
            visited.add(frozen.id)
            frozen = db.get(RequirementRiskAnalysis, frozen.retry_of)
            if (
                frozen is None
                or frozen.project_id != project_id
                or frozen.selections != retried.selections
            ):
                raise AppError(422, "risk_analysis_retry_invalid")
        if "skill" not in frozen.context:
            raise AppError(409, "skill_snapshot_missing")
        frozen_context = {"skill": deepcopy(frozen.context["skill"])}
        if "input" in frozen.context and "bindings" in frozen.context:
            frozen_context.update(
                {key: deepcopy(frozen.context[key]) for key in ("input", "bindings")}
            )
    else:
        frozen_context = {"skill": skill_files.snapshot("requirement-analysis")}
    for selection in payload.selections:
        source = db.scalar(
            select(SourceDocument).where(
                SourceDocument.id == selection.document_id,
                SourceDocument.project_id == project_id,
                SourceDocument.deleted_at.is_(None),
            )
        )
        if source is None:
            raise AppError(422, "risk_source_unavailable")
        if source.kind == "FILE":
            version = db.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.id == selection.version_id,
                    DocumentVersion.project_id == project_id,
                    DocumentVersion.document_id == source.id,
                )
            )
            if version is None:
                raise AppError(422, "risk_version_required")
            if selection.paths or selection.snapshot or selection.url:
                raise AppError(422, "risk_source_unavailable")
        elif source.kind == "DIRECTORY":
            directories.checked(
                project_id, source.id, selection.version_id, selection.paths, actor, db
            )
            if selection.snapshot or selection.url:
                raise AppError(422, "risk_source_unavailable")
        elif source.kind == "LINK":
            if selection.version_id is not None:
                raise AppError(422, "risk_version_required")
            if selection.url != source.url and (selection.url is not None or not payload.retry_of):
                raise AppError(409, "prototype_link_changed")
            if not payload.retry_of and (not selection.paths or not selection.snapshot):
                raise AppError(422, "prototype_link_selection_required")
            if len(selection.paths) != len(set(selection.paths)):
                raise AppError(422, "prototype_link_selection_required")
        elif selection.paths or selection.snapshot or selection.url:
            raise AppError(422, "risk_source_unavailable")
        elif selection.version_id is not None:
            raise AppError(422, "risk_version_required")
    if payload.retry_of:
        meta, _ = analysis_configuration(
            actor, db, mode=retried.ai_config.get("call_mode", "RESPONSES_API")
        )
    else:
        meta, _ = analysis_configuration(
            actor,
            db,
            payload.ai_version,
            mode=payload.ai_call_mode or "RESPONSES_API",
            preference_version=payload.ai_preference_version,
        )
    row = RequirementRiskAnalysis(
        project_id=project_id,
        actor_id=actor.id,
        request_id=request_id,
        retry_of=payload.retry_of,
        title=payload.title,
        focus=payload.focus,
        selections=selections,
        context=frozen_context,
        ai_config=native_terminal.bind_snapshot(configuration_snapshot(meta)),
    )
    db.add(row)
    db.commit()
    return view(row, db, actor)


def cancel(project_id, task_id, actor, db):
    documents.access(project_id, actor, db, lock=True)
    row = db.scalar(
        select(RequirementRiskAnalysis)
        .where(
            RequirementRiskAnalysis.id == task_id,
            RequirementRiskAnalysis.project_id == project_id,
        )
        .with_for_update()
    )
    require_visible(row)
    if row is None:
        raise AppError(404, "risk_analysis_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "risk_analysis_cancel_owner_only")
    if row.status in ACTIVE:
        row.status, row.updated_at = "CANCELLED", datetime.now(UTC)
        db.commit()
    return view(row, db, actor)


def candidate(project_id, task_id, actor, db):
    documents.access(project_id, actor, db)
    row = db.get(RequirementRiskAnalysis, task_id)
    require_visible(row)
    if row is None or row.project_id != project_id:
        raise AppError(404, "risk_analysis_not_found")
    path = artifacts.candidate_path(task_id)
    if row.status in ACTIVE or not path.is_file():
        raise AppError(404, "risk_candidate_not_found")
    return path


def frozen_materials(project_id, task, actor, db):
    """Recheck project sources and resolve only immutable binary attachments."""
    binaries = []
    materials = task.context["input"]["materials"]
    for selection, binding, material in zip(
        task.selections, task.context["bindings"], materials, strict=True
    ):
        source = db.get(SourceDocument, selection["document_id"], populate_existing=True)
        if source is None or source.project_id != project_id or source.deleted_at is not None:
            raise AppError(422, "risk_source_unavailable")
        if (
            source.id != binding["document_id"]
            or source.kind != binding["kind"]
            or source.purpose != binding["purpose"]
            or source.purpose != material["origin"]
            or binding["source_id"] != material["source_id"]
        ):
            raise AppError(422, "risk_source_unavailable")
        if source.kind == "FILE":
            path, version = documents.stored_version(project_id, selection["version_id"], actor, db)
            if version.document_id != source.id:
                raise AppError(422, "risk_version_required")
            if version.extension in ("png", "jpg", "jpeg", "webp", "pdf"):
                if hashlib.sha256(path.read_bytes()).hexdigest() != material["snapshot_ref"]:
                    raise AppError(409, "risk_source_changed")
                binaries.append((path, version.extension, material["source_id"], version.filename))
        elif source.kind == "DIRECTORY":
            actual, attached = directories.material(
                project_id,
                source.id,
                selection["version_id"],
                selection["paths"],
                material["source_id"],
                actor,
                db,
            )
            if actual["snapshot_ref"] != material["snapshot_ref"]:
                raise AppError(409, "risk_source_changed")
            binaries.extend(attached)
        elif source.kind == "LINK" and selection.get("url") and selection["url"] != source.url:
            raise AppError(409, "prototype_link_changed")
    return binaries


def revalidate_candidate(project_id, task_id, actor, db):
    documents.access(project_id, actor, db, lock=True)
    row = db.scalar(
        select(RequirementRiskAnalysis)
        .where(
            RequirementRiskAnalysis.id == task_id, RequirementRiskAnalysis.project_id == project_id
        )
        .with_for_update()
    )
    require_visible(row)
    if row is None:
        raise AppError(404, "risk_analysis_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "risk_revalidation_owner_only")
    if row.status == "COMPLETED" and row.context.get("revalidation"):
        return view(row, db, actor)
    if row.status != "FAILED" or "input" not in row.context:
        raise AppError(422, "risk_revalidation_invalid")
    frozen_materials(project_id, row, actor, db)
    try:
        raw = artifacts.candidate_path(task_id).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AppError(404, "risk_candidate_not_found") from None
    except (OSError, UnicodeError):
        raise AppError(503, "risk_candidate_storage_unavailable") from None
    input_data = risk_service.parse(
        risk_schemas.AnalysisInput, deepcopy(row.context["input"]), "input"
    )
    candidate, comparison_corrections = risk_schemas.normalize_comparison_text(
        risk_service.json_object(raw)
    )
    output = risk_service.parse(risk_schemas.Report, candidate, "report")
    output, corrections = risk_schemas.normalize_function_risks(output)
    review_warnings = []
    risk_schemas.validate_report(output, input_data, project_id, review_warnings)
    result = risk_service.store_report(
        project_id,
        row.title,
        "input.json",
        "risk-report.json",
        input_data.model_dump(),
        output.model_dump(),
        row.context["bindings"],
        actor,
        db,
        commit=False,
    )
    row.report_id = result["id"]
    row.context = {
        **row.context,
        "function_risk_corrections": corrections,
        "comparison_text_corrections": comparison_corrections,
        "review_warnings": review_warnings,
        "revalidation": {"actor_id": actor.id, "at": datetime.now(UTC).isoformat()},
    }
    row.status, row.error_code, row.updated_at = "COMPLETED", "", datetime.now(UTC)
    db.commit()
    return view(row, db, actor)
