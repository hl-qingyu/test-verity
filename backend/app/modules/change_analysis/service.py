"""Project records, idempotent requests and review separate from immutable reports."""

import copy
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import load_only

from app.core.errors import AppError
from app.core.json_data import json_object as read_json_object
from app.db.models import ChangeAnalysisTask, UserAccount
from app.modules.ai import native_terminal
from app.modules.ai.service import (
    analysis_configuration,
    configuration_snapshot,
)
from app.modules.change_analysis import (
    artifacts,
    contract,
    evidence,
    legacy_batches,
    presentation,
    report_v3,
    schemas,
    sources,
)
from app.modules.code_analysis import sources as code_sources
from app.modules.documents import service as documents
from app.modules.projects.record_deletion import require_visible

ACTIVE = ("QUEUED", "RUNNING")
RESULT_GROUPS = (
    "changes",
    "function_impacts",
    "code_impacts",
    "case_impacts",
    "risks",
    "historical_reviews",
    "regression_scope",
)


def json_object(text):
    return read_json_object(text, "change_contract_invalid")


def parse(model, value):
    try:
        return model.model_validate(value)
    except (ValidationError, TypeError, ValueError, RecursionError):
        raise AppError(422, "change_contract_invalid") from None


async def read_payload(chunks, model):
    body = bytearray()
    async for chunk in chunks:
        body.extend(chunk)
    try:
        return parse(model, json_object(body.decode("utf-8-sig")))
    except (UnicodeError, RecursionError):
        raise AppError(422, "change_json_invalid") from None
    except AppError as exc:
        if exc.detail == "change_contract_invalid":
            raise AppError(422, "change_request_invalid") from None
        raise


def validate_candidate(raw, data, *, version=None, mode="CODEX_EXEC", normalize=True):
    contract.require(isinstance(raw, dict), "change_contract_invalid")
    version = version if version is not None else raw.get("contract_version")
    if version == 3:
        try:
            return report_v3.validate(raw, data, mode, normalize=normalize)
        except ValidationError:
            raise AppError(422, "change_contract_invalid") from None
    output = parse(contract.Report, raw)
    output, corrections = (
        evidence.normalize_coordinates(data, output) if normalize else (output, [])
    )
    contract.validate_report(data, output)
    return output.model_dump(by_alias=True), corrections


def own(project_id, task_id, actor, db, *, lock=False, state_only=False, page_view=False):
    documents.access(project_id, actor, db, lock=lock)
    query = (
        select(ChangeAnalysisTask)
        .where(ChangeAnalysisTask.project_id == project_id, ChangeAnalysisTask.id == task_id)
        .execution_options(populate_existing=True)
    )
    if state_only:
        query = query.options(
            load_only(
                ChangeAnalysisTask.id,
                ChangeAnalysisTask.status,
                ChangeAnalysisTask.deleted_at,
                ChangeAnalysisTask.actor_id,
                ChangeAnalysisTask.project_id,
            )
        )
    if page_view:
        model = ChangeAnalysisTask
        query = select(
            *[
                c
                for c in model.__table__.columns
                if c.name not in {"input_snapshot", "metadata_snapshot"}
            ],
            presentation.page_input(model.input_snapshot).label("input_snapshot"),
            presentation.page_metadata(model.metadata_snapshot).label("metadata_snapshot"),
        ).where(model.project_id == project_id, model.id == task_id)
        result = db.execute(query).mappings().one_or_none()
        row = SimpleNamespace(**result) if result is not None else None
    else:
        row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise AppError(404, "change_analysis_not_found")
    require_visible(row)
    return row


def items(report):
    return {item["key"]: (group, item) for group in RESULT_GROUPS for item in report.get(group, [])}


def view(row, actor, *, detail=False):
    require_visible(row)
    metadata, report = row.metadata_snapshot or {}, row.report or {}
    plan = metadata.get("batch_plan")
    result = {
        "id": row.id,
        "project_id": row.project_id,
        "actor_id": row.actor_id,
        "title": row.title,
        "mode": row.mode,
        "targets": row.targets,
        "focus": row.focus,
        "status": row.status,
        "error_code": row.error_code,
        "revision": row.revision,
        "retry_of": row.retry_of,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "origin": metadata.get("origin", "AI"),
        "ai": native_terminal.public_snapshot(row.ai_config),
        "terminal_available": native_terminal.available(row.ai_config, row.actor_id, actor.id),
        "can_cancel": row.actor_id == actor.id and row.status in (*ACTIVE, "PREPARED"),
        "can_retry": metadata.get("origin") == "AI"
        and (
            row.status in {"FAILED", "CANCELLED"}
            or row.status == "PREPARED"
            and bool(plan)
            or row.status == "COMPLETED"
            and bool((metadata.get("batch_summary") or {}).get("failed"))
        ),
        "retry_preparation": not bool(row.input_snapshot),
        "retry_replan": bool(plan),
        "outcome": report.get("outcome"),
        "changes_count": len(report.get("changes", [])),
        "risks_count": len(report.get("risks", [])),
    }
    if detail:
        plan = metadata.get("batch_plan")
        batch_candidates = bool(plan) and any(
            b.get("candidate_task_id") == row.id
            and artifacts.batch_candidate_path(row.id, b["id"]).is_file()
            for b in plan["batches"]
        )
        available = (
            metadata.get("origin") == "AI"
            and row.status not in ACTIVE
            and (artifacts.candidate_path(row.id).is_file() or batch_candidates)
        )
        available = available and row.actor_id == actor.id
        result.update(
            input=row.input_snapshot,
            report=report,
            handling=row.handling,
            bindings=metadata.get("bindings") or [],
            selections={
                "pairs": [
                    {k: v for k, v in p.items() if k not in {"before_local", "after_local"}}
                    for p in metadata.get("selections", {}).get("pairs", [])
                ]
            }
            if not row.input_snapshot
            else {},
            skill={k: v for k, v in metadata.get("skill", {}).items() if k != "instructions"},
            candidate_available=available,
            batches=legacy_batches.summary(plan),
            evidence_corrections=metadata.get("evidence_corrections") or [],
            can_revalidate=bool(
                row.actor_id == actor.id
                and (row.status == "FAILED" or plan and row.status == "COMPLETED")
                and (
                    row.error_code in {"change_contract_invalid", "change_evidence_invalid"}
                    or plan
                    and any(
                        b["status"] != "COMPLETED"
                        and b.get("candidate_task_id") == row.id
                        and artifacts.batch_candidate_path(row.id, b["id"]).is_file()
                        for b in plan["batches"]
                    )
                )
                and available
            ),
        )
    return result


def detail(project_id, task_id, actor, db, *, page_view=False):
    result = view(own(project_id, task_id, actor, db, page_view=page_view), actor, detail=True)
    if page_view:
        result["input_projected"] = True
    return result


def listing(project_id, actor, db, page=1, *, page_view=False):
    documents.access(project_id, actor, db)
    model = ChangeAnalysisTask
    columns = [
        getattr(model, k)
        for k in (
            "id",
            "project_id",
            "actor_id",
            "title",
            "mode",
            "targets",
            "focus",
            "status",
            "error_code",
            "revision",
            "retry_of",
            "created_at",
            "updated_at",
            "ai_config",
        )
    ]
    if not page_view:
        columns.append(
            model.input_snapshot["contract_version"].as_integer().label("input_contract_version")
        )
    rows = (
        db.execute(
            select(
                *columns,
                model.metadata_snapshot["origin"].astext.label("origin"),
                model.metadata_snapshot["batch_summary"].label("batches"),
                model.metadata_snapshot["batch_plan"]["version"]
                .as_integer()
                .label("batch_version"),
                model.report["outcome"].astext.label("outcome"),
                func.coalesce(func.jsonb_array_length(model.report["changes"]), 0).label(
                    "changes_count"
                ),
                func.coalesce(func.jsonb_array_length(model.report["risks"]), 0).label(
                    "risks_count"
                ),
            )
            .where(model.project_id == project_id, model.deleted_at.is_(None))
            .order_by(model.id.desc())
            .offset((page - 1) * 50)
            .limit(51)
        )
        .mappings()
        .all()
    )
    result = []
    for r in rows[:50]:
        v = dict(r)
        v["can_cancel"] = v["actor_id"] == actor.id and v["status"] in (*ACTIVE, "PREPARED")
        if not page_view:
            v["retry_preparation"] = v.pop("input_contract_version") != 2
        v["retry_replan"] = v.pop("batch_version") in {1, 2}
        v["can_retry"] = v["origin"] == "AI" and (
            v["status"] in {"FAILED", "CANCELLED"}
            or v["status"] == "PREPARED"
            and v["retry_replan"]
            or v["status"] == "COMPLETED"
            and bool((v["batches"] or {}).get("failed"))
        )
        ai = v.pop("ai_config")
        v["ai"] = native_terminal.public_snapshot(ai)
        v["terminal_available"] = native_terminal.available(ai, v["actor_id"], actor.id)
        for k in ("created_at", "updated_at"):
            v[k] = v[k].isoformat()
        result.append(v)
    return {"items": result, "has_more": len(rows) > 50}


def enqueue(project_id, payload, actor, db):
    documents.access(project_id, actor, db, lock=True)
    raw = payload.model_dump(mode="json")
    fingerprint = sources.digest(raw)
    previous = db.scalar(
        select(ChangeAnalysisTask).where(
            ChangeAnalysisTask.project_id == project_id,
            ChangeAnalysisTask.actor_id == actor.id,
            ChangeAnalysisTask.request_id == str(payload.request_id),
        )
    )
    if previous:
        if previous.metadata_snapshot["request_hash"] != fingerprint:
            raise AppError(409, "change_request_conflict")
        return view(previous, actor, detail=True)
    if not payload.title.strip():
        raise AppError(422, "change_title_required")
    skill = sources.skill_snapshot()
    metadata = {
        "origin": "AI",
        "selections": raw,
        "request_hash": fingerprint,
        "skill": skill,
        "execution_mode": "DIFF_FIRST" if skill["contract_version"] == 3 else "FULL_INPUT",
    }
    sources.recheck(project_id, metadata, actor, db)
    config, _ = analysis_configuration(
        actor,
        db,
        payload.ai_version,
        mode=payload.ai_call_mode or "RESPONSES_API",
        preference_version=payload.ai_preference_version,
    )
    row = ChangeAnalysisTask(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        title=payload.title.strip(),
        mode=payload.mode,
        targets=payload.targets,
        focus=payload.focus,
        input_snapshot={},
        metadata_snapshot=metadata,
        handling={},
        ai_config=native_terminal.bind_snapshot(configuration_snapshot(config)),
    )
    db.add(row)
    db.commit()
    return view(row, actor, detail=True)


def cancel(project_id, task_id, actor, db):
    row = own(project_id, task_id, actor, db, lock=True)
    if row.actor_id != actor.id:
        raise AppError(403, "change_cancel_owner_only")
    if row.status in (*ACTIVE, "PREPARED"):
        row.status, row.updated_at = "CANCELLED", datetime.now(UTC)
        db.commit()
    return view(row, actor, detail=True)


def retry(project_id, task_id, payload, actor, db):
    old = own(project_id, task_id, actor, db, lock=True)
    previous = db.scalar(
        select(ChangeAnalysisTask).where(
            ChangeAnalysisTask.project_id == project_id,
            ChangeAnalysisTask.actor_id == actor.id,
            ChangeAnalysisTask.request_id == str(payload.request_id),
        )
    )
    if previous:
        if previous.retry_of != task_id:
            raise AppError(409, "change_request_conflict")
        return view(previous, actor, detail=True)
    if not view(old, actor)["can_retry"]:
        raise AppError(422, "change_retry_invalid")
    metadata = copy.deepcopy(old.metadata_snapshot)
    metadata["execution_mode"] = (
        "DIFF_FIRST" if metadata.get("skill", {}).get("contract_version") == 3 else "FULL_INPUT"
    )
    if metadata.get("batch_plan"):
        metadata["previous_batch_execution"] = {
            "task_id": old.id,
            "plan": metadata.pop("batch_plan"),
            "handling": copy.deepcopy(old.handling),
        }
        metadata.pop("batch_summary", None)
    metadata.pop("batch_authorized", None)
    metadata.pop("batch_authorized_at", None)
    metadata.pop("batch_replanned", None)
    if not old.input_snapshot:
        try:
            schemas.AnalysisRequest.model_validate(metadata.get("selections"))
        except (ValidationError, TypeError, ValueError):
            raise AppError(422, "change_retry_scope_unavailable") from None
        skill = metadata.get("skill")
        if not isinstance(skill, dict) or not skill.get("instructions"):
            raise AppError(422, "change_retry_scope_unavailable")
        # Rebuild both sides in a new task; never mix a partial input with a live side.
        metadata.pop("bindings", None)
    sources.recheck(project_id, metadata, actor, db, shared_snapshot=True)
    config, _ = analysis_configuration(
        actor, db, mode=old.ai_config.get("call_mode", "RESPONSES_API")
    )
    snapshot = copy.deepcopy(old.input_snapshot)
    if snapshot:
        snapshot["request_id"] = str(payload.request_id)
    metadata["shared_snapshot"] = True
    metadata["request_hash"] = sources.digest(
        {"request_id": str(payload.request_id), "retry_of": task_id}
    )
    row = ChangeAnalysisTask(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        retry_of=task_id,
        title=old.title,
        mode=old.mode,
        targets=old.targets,
        focus=old.focus,
        input_snapshot=snapshot,
        metadata_snapshot=metadata,
        handling={},
        ai_config=native_terminal.bind_snapshot(configuration_snapshot(config)),
    )
    db.add(row)
    db.commit()
    return view(row, actor, detail=True)


def revalidate_candidate(project_id, task_id, actor, db):
    row = own(project_id, task_id, actor, db, lock=True)
    if row.actor_id != actor.id:
        raise AppError(403, "change_revalidate_owner_only")
    if (
        row.status == "COMPLETED"
        and row.metadata_snapshot.get("revalidation")
        and not row.metadata_snapshot.get("batch_plan")
    ):
        return view(row, actor, detail=True)
    if not view(row, actor, detail=True)["can_revalidate"]:
        raise AppError(422, "change_revalidation_invalid")
    if row.metadata_snapshot.get("batch_plan"):
        sources.recheck(
            project_id,
            row.metadata_snapshot,
            actor,
            db,
            shared_snapshot=row.metadata_snapshot.get("shared_snapshot", False),
        )
        legacy_batches.revalidate(row)
        row.metadata_snapshot = {
            **row.metadata_snapshot,
            "batch_summary": legacy_batches.summary(row.metadata_snapshot["batch_plan"]),
            "revalidation": {"actor_id": actor.id, "at": row.updated_at.isoformat()},
        }
        row.revision += 1
        db.commit()
        return view(row, actor, detail=True)
    try:
        candidate = artifacts.candidate_path(row.id).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise AppError(503, "change_candidate_storage_unavailable") from None
    data = parse(contract.AnalysisInput, row.input_snapshot)
    output, corrections = validate_candidate(
        json_object(candidate),
        data,
        version=row.metadata_snapshot.get("skill", {}).get("contract_version", 2),
        mode=row.ai_config.get("call_mode", "RESPONSES_API"),
    )
    sources.recheck(
        project_id,
        row.metadata_snapshot,
        actor,
        db,
        shared_snapshot=row.metadata_snapshot.get("shared_snapshot", False),
    )
    analysis_configuration(actor, db, row.ai_config)
    row.report, row.status, row.error_code, row.updated_at = (
        output,
        "COMPLETED",
        "",
        datetime.now(UTC),
    )
    row.metadata_snapshot = {
        **row.metadata_snapshot,
        "revalidation": {"actor_id": actor.id, "at": row.updated_at.isoformat()},
        "evidence_corrections": corrections,
    }
    row.revision += 1
    db.commit()
    return view(row, actor, detail=True)


async def import_report(project_id, chunks, actor, db):
    documents.access(project_id, actor, db)
    actor_id = actor.id
    db.rollback()
    payload = await read_payload(chunks, schemas.ImportRequest)
    for name in (payload.input_filename, payload.report_filename):
        contract.require(
            name.lower().endswith(".json") and not any(c in name for c in "/\\\x00"),
            "change_import_file_invalid",
        )
    data = parse(contract.AnalysisInput, json_object(payload.input_json.lstrip("\ufeff")))
    raw = json_object(payload.report_json.lstrip("\ufeff"))
    if isinstance(raw, dict) and raw.get("contract_version") == 3:
        raw = {k: v for k, v in raw.items() if k not in ("outcome", "platform_coverage")}
    contract.require(data.project_id == project_id, "change_project_mismatch")
    output, _ = validate_candidate(raw, data, mode="IMPORT", normalize=False)
    actor = db.get(UserAccount, actor_id, populate_existing=True)
    documents.access(project_id, actor, db, lock=True)
    mapping = {b.snapshot_ref: b for b in payload.bindings}
    contract.require(
        len(mapping) == len(payload.bindings)
        and set(mapping) == {s.snapshot_ref for s in data.snapshots},
        "change_bindings_required",
    )
    bindings = []
    for s in data.snapshots:
        b = mapping[s.snapshot_ref].model_dump()
        if s.kind == "CODE":
            contract.require(b["source_id"] and b["source_version"] and not b["document_id"])
            # Bind imported code roles to project registration.
            kind = (
                s.provenance.source_kind
                if s.provenance.source_kind in {"LOCAL", "GITHUB"}
                else b["kind"]
            )
            contract.require(kind in {"LOCAL", "GITHUB"}, "change_bindings_required")
            b["kind"] = kind
            row, _ = code_sources.source_authorization(project_id, b, actor, db)
            contract.require(row.kind == s.repository_kind, "change_binding_mismatch")
        else:
            contract.require(b["document_id"] and not b["source_id"], "change_bindings_required")
            row = sources.document(project_id, b["document_id"], actor, db)
            contract.require(row.purpose == s.kind, "change_binding_mismatch")
            if row.kind == "FILE":
                path, v = documents.stored_version(project_id, b["version_id"], actor, db)
                contract.require(v.document_id == row.id, "change_binding_mismatch")
                b["binary_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                actual = sources.analysis_materials.file_material(
                    path, v.extension, s.snapshot_ref, v.filename
                )
                contract.require(actual["snapshot_ref"] == v.sha256, "change_source_changed")
                actual_text = "\n".join(seg["text"] for seg in actual["segments"])
                supplied_text = "\n".join(seg.text for u in s.units for seg in u.segments)
                if supplied_text:
                    contract.require(
                        all(
                            seg.text in actual_text
                            for u in s.units
                            for seg in u.segments
                            if seg.text
                        ),
                        "change_binding_mismatch",
                    )
                    if s.scope_complete and all(u.read_state == "READABLE" for u in s.units):
                        contract.require(supplied_text == actual_text, "change_binding_mismatch")
                for unit in s.units:
                    for seg in unit.segments:
                        if seg.image_ref:
                            contract.require(
                                seg.image_ref == s.snapshot_ref
                                and v.extension in {"pdf", "png", "jpg", "jpeg", "webp"},
                                "change_attachment_mismatch",
                            )
            elif row.kind == "DIRECTORY":
                actual, binding, _ = sources.directory_snapshot(
                    project_id,
                    {
                        "source_id": row.id,
                        "before_version_id": b["version_id"],
                        "paths": [u.path for u in s.units],
                    },
                    "before",
                    s.snapshot_ref,
                    actor,
                    db,
                )
                contract.require(
                    actual["units"] == [u.model_dump() for u in s.units]
                    and s.provenance.version_ref == actual["provenance"]["version_ref"],
                    "change_binding_mismatch",
                )
                b.update(binding)
            else:
                contract.require(
                    not b["version_id"]
                    and not any(seg.image_ref for u in s.units for seg in u.segments),
                    "change_binding_mismatch",
                )
        bindings.append(b)
    # Selected cases and histories must belong to this project; no imported actor/status is trusted.
    from app.modules.cases import service as case_service
    from app.modules.code_analysis import service as code_service
    from app.modules.requirements import risk_service

    for c in data.cases:
        existing = case_service.detail(project_id, c.case_id, actor, db)
        matched = next((v for v in existing["versions"] if v["number"] == c.design_version), None)
        contract.require(
            matched is not None,
            "change_case_version_invalid",
        )
        contract.require(
            c.title == matched["title"]
            and all(matched[k] == value for k, value in c.design.model_dump().items()),
            "change_case_version_invalid",
        )
    for h in data.historical_items:
        r = (
            risk_service.detail(project_id, h.report_id, actor, db)
            if h.module == "REQUIREMENT_ANALYSIS"
            else code_service.detail(project_id, h.report_id, actor, db)
        )
        group = "risks" if h.module == "REQUIREMENT_ANALYSIS" else "findings"
        contract.require(
            any(item["key"] == h.item_key for item in r["report"].get(group, [])),
            "change_history_unavailable",
        )
    snapshot, report = data.model_dump(), output
    fingerprint = sources.digest({"input": snapshot, "report": report, "bindings": bindings})
    prior = db.scalar(
        select(ChangeAnalysisTask).where(
            ChangeAnalysisTask.project_id == project_id,
            ChangeAnalysisTask.metadata_snapshot["import_hash"].astext == fingerprint,
        )
    )
    if prior:
        return {**view(prior, actor, detail=True), "duplicate": True}
    if not payload.title.strip():
        raise AppError(422, "change_title_required")
    row = ChangeAnalysisTask(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(uuid5(NAMESPACE_URL, fingerprint)),
        title=payload.title.strip(),
        mode=data.mode,
        focus=data.focus,
        targets=data.targets,
        input_snapshot=snapshot,
        report=report,
        status="COMPLETED",
        ai_config={},
        handling={},
        metadata_snapshot={
            "origin": "IMPORT",
            "import_hash": fingerprint,
            "bindings": bindings,
            "input_filename": payload.input_filename,
            "report_filename": payload.report_filename,
            "provenance": "用户导入固定快照；未与真实仓库自动比对",
        },
    )
    db.add(row)
    db.commit()
    return {**view(row, actor, detail=True), "duplicate": False}


def handle(project_id, task_id, payload, actor, db):
    row = own(project_id, task_id, actor, db, lock=True)
    if row.revision != payload.revision:
        raise AppError(409, "change_handling_changed")
    match = items(row.report).get(payload.item_key)
    if row.status != "COMPLETED" or not match:
        raise AppError(422, "change_item_unavailable")
    group, _ = match
    allowed = (
        {"PENDING", "ACCEPTED", "DEFERRED", "REJECTED"}
        if group == "regression_scope"
        else {"PENDING", "CONFIRMED", "RESOLVED", "FALSE_POSITIVE", "NEEDS_EVIDENCE"}
    )
    if group == "changes" or payload.status not in allowed:
        raise AppError(422, "change_handling_invalid")
    if payload.status != "PENDING" and not payload.note.strip():
        raise AppError(422, "change_handling_note_required")
    handling = copy.deepcopy(row.handling)
    previous = handling.get(payload.item_key, {})
    entry = {
        "status": payload.status,
        "note": payload.note.strip(),
        "actor_id": actor.id,
        "actor_name": actor.display_name,
        "at": datetime.now(UTC).isoformat(),
    }
    handling[payload.item_key] = {
        **entry,
        "history": [
            *previous.get("history", []),
            {**entry, "previous_status": previous.get("status", "PENDING")},
        ],
    }
    row.handling, row.revision, row.updated_at = handling, row.revision + 1, datetime.now(UTC)
    db.commit()
    return view(row, actor, detail=True)
