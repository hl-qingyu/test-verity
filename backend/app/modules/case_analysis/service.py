import copy
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import (
    CaseAnalysisApplication,
    CaseAnalysisChatTurn,
    CaseAnalysisRun,
)
from app.modules.ai.service import (
    analysis_configuration,
    configuration_snapshot,
    current_metadata,
)
from app.modules.case_analysis import contract
from app.modules.case_generation import sources
from app.modules.cases import service as cases
from app.modules.cases.schemas import EditScope
from app.modules.documents import service as documents
from app.modules.projects.record_deletion import require_visible
from app.modules.skills import files as skill_files

ACTIVE = ("QUEUED", "RUNNING")
SUMMARY_FIELDS = (
    "id",
    "project_id",
    "title",
    "mode",
    "actor_id",
    "parent_id",
    "status",
    "revision",
    "error_code",
    "created_at",
    "updated_at",
)


def summary(project_id, run_id, actor, db):
    documents.access(project_id, actor, db)
    value = (
        db.execute(
            select(*[getattr(CaseAnalysisRun, k) for k in SUMMARY_FIELDS]).where(
                CaseAnalysisRun.project_id == project_id,
                CaseAnalysisRun.deleted_at.is_(None),
                CaseAnalysisRun.id == run_id,
            )
        )
        .mappings()
        .first()
    )
    if value is None:
        raise AppError(404, "case_analysis_not_found")
    return {**dict(value), "outcome": None}


def own(project_id, run_id, actor, db, lock=False):
    documents.access(project_id, actor, db, lock=lock)
    query = (
        select(CaseAnalysisRun)
        .where(CaseAnalysisRun.project_id == project_id, CaseAnalysisRun.id == run_id)
        .execution_options(populate_existing=True)
    )
    row = db.scalar(query.with_for_update() if lock else query)
    if not row:
        raise AppError(404, "case_analysis_not_found")
    require_visible(row)
    return row


def items(row):
    return (
        row.report.get("findings", [])
        + row.report.get("notes", [])
        + row.handling.get("manual", [])
    )


def outcome(row):
    if row.status != "COMPLETED":
        return None
    return (
        "COMPLETE"
        if row.report.get("complete")
        and set(row.report.get("checked_case_ids", []))
        == {c["id"] for c in row.input_snapshot["cases"]}
        else "PARTIAL"
    )


def view(row, summary=False):
    require_visible(row)
    result = {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "mode": row.mode,
        "actor_id": row.actor_id,
        "parent_id": row.parent_id,
        "status": row.status,
        "outcome": outcome(row),
        "revision": row.revision,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
    if not summary:
        result.update(
            input=row.input_snapshot,
            report=row.report,
            handling={k: v for k, v in row.handling.items() if k != "manual"},
            manual=row.handling.get("manual", []),
            ai_config=row.ai_config,
            attempts=row.attempts,
            notice=sources.input_notice(
                row.input_snapshot,
                row.metadata_snapshot["skill"]["instructions"],
                row.metadata_snapshot.get("attachment_bytes", 0),
            ),
        )
    return result


def detail(project_id, run_id, actor, db):
    row = own(project_id, run_id, actor, db)
    result = view(row)
    config = current_metadata(
        actor, db, mode=row.ai_config.get("call_mode") if row.parent_id else None
    )
    if config and row.parent_id:
        config = {k: v for k, v in config.items() if k != "preference_version"}
    result["personal_ai"] = config
    result["chat"] = [
        {
            "id": t.id,
            "actor_id": t.actor_id,
            "finding_key": t.finding_key,
            "function_key": t.function_key,
            "question": t.question,
            "answer": t.answer,
            "status": t.status,
            "error_code": t.error_code,
        }
        for t in db.scalars(
            select(CaseAnalysisChatTurn)
            .where(CaseAnalysisChatTurn.run_id == run_id)
            .order_by(CaseAnalysisChatTurn.id)
        )
    ]
    result["applications"] = [
        {"id": a.id, "status": a.status, "items": a.items, "error_code": a.error_code}
        for a in db.scalars(
            select(CaseAnalysisApplication)
            .where(CaseAnalysisApplication.run_id == run_id)
            .order_by(CaseAnalysisApplication.id)
        )
    ]
    return result


def listing(project_id, actor, db, page):
    documents.access(project_id, actor, db)
    rows = list(
        db.execute(
            select(
                *[
                    getattr(CaseAnalysisRun, k)
                    for k in (
                        "id",
                        "project_id",
                        "title",
                        "mode",
                        "actor_id",
                        "parent_id",
                        "status",
                        "revision",
                        "error_code",
                        "created_at",
                        "updated_at",
                    )
                ]
            )
            .where(CaseAnalysisRun.project_id == project_id, CaseAnalysisRun.deleted_at.is_(None))
            .order_by(CaseAnalysisRun.id.desc())
            .offset((page - 1) * 20)
            .limit(21)
        ).mappings()
    )
    return {"items": [{**dict(r), "outcome": None} for r in rows[:20]], "has_more": len(rows) > 20}


def prepare(project_id, payload, actor, db):
    documents.access(project_id, actor, db, lock=True)
    fingerprint = contract.digest(sources.preparation_request(payload))
    prior = db.scalar(
        select(CaseAnalysisRun).where(
            CaseAnalysisRun.project_id == project_id,
            CaseAnalysisRun.request_id == str(payload.request_id),
        )
    )
    if prior:
        contract.require(
            prior.metadata_snapshot["request_hash"] == fingerprint, "case_analysis_request_conflict"
        )
        return detail(project_id, prior.id, actor, db)
    if payload.parent_id:
        own(project_id, payload.parent_id, actor, db)
    contract.require(payload.search.lifecycle == "ACTIVE")
    if payload.case_ids == []:
        chosen = []
    else:
        scope = cases.edit_scope(
            project_id,
            EditScope(**payload.search.model_dump(), case_ids=payload.case_ids),
            actor,
            db,
        )
        chosen = scope["items"]
        contract.require(
            payload.library_revision is None or payload.library_revision == scope["revision"],
            "case_analysis_target_changed",
        )
    contract.require(
        payload.case_versions is None
        or payload.case_versions == {str(c["id"]): c["version"] for c in chosen},
        "case_analysis_target_changed",
    )
    contract.require(
        bool(chosen) or payload.mode == "COMPARE" and payload.zero_confirmed,
        "case_analysis_cases_required",
    )
    contract.require(
        payload.mode == "QUALITY" or payload.materials, "case_analysis_materials_required"
    )
    contract.require(payload.mode != "QUALITY" or not payload.materials)
    contract.require(len({m.document_id for m in payload.materials}) == len(payload.materials))
    fixed, bindings = [], []
    for i, m in enumerate(payload.materials, 1):
        contract.require(not m.before and not m.baseline_run_id and not m.update)
        material, binding = sources.read_material(project_id, m, "CURRENT", f"M{i}", actor, db)
        contract.require(
            material["read_state"] != "UNREADABLE", "case_analysis_material_unreadable"
        )
        material["version"] = material["version_ref"]
        fixed.append(material)
        bindings.append(binding)
    skill = skill_files.snapshot("case-analysis")
    data = {
        "type": "CASE_REVIEW",
        "contract_version": 1,
        "project_id": project_id,
        "request_id": str(payload.request_id),
        "mode": payload.mode,
        "scope": payload.search.model_dump(mode="json"),
        "focus": payload.focus,
        "materials": fixed,
        "cases": chosen,
    }
    metadata = {
        "bindings": bindings,
        "request_hash": fingerprint,
        "skill": skill,
    }
    attachment_bytes = sum(
        p.stat().st_size for p, _, _, _ in sources.binaries(project_id, metadata, actor, db)
    )
    metadata["attachment_bytes"] = attachment_bytes
    documents.access(project_id, actor, db, lock=True)
    row = CaseAnalysisRun(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        parent_id=payload.parent_id,
        title=payload.title.strip(),
        mode=payload.mode,
        input_snapshot=data,
        metadata_snapshot=metadata,
        report={},
        handling={},
        ai_config={},
        attempts=[],
        status="PREPARED",
    )
    db.add(row)
    db.commit()
    return detail(project_id, row.id, actor, db)


def start(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    contract.require(row.revision == payload.revision, "case_analysis_revision_conflict")
    contract.require(row.status == "PREPARED", "case_analysis_already_started")
    sources.recheck(project_id, row.metadata_snapshot, actor, db)
    config, _ = analysis_configuration(
        actor,
        db,
        payload.ai_version,
        mode=row.ai_config.get("call_mode", "RESPONSES_API")
        if row.parent_id
        else payload.ai_call_mode or "RESPONSES_API",
        preference_version=None if row.parent_id else payload.ai_preference_version,
    )
    row.ai_config, row.actor_id, row.status = (
        configuration_snapshot(config),
        actor.id,
        "QUEUED",
    )
    row.updated_at = datetime.now(UTC)
    db.commit()
    return detail(project_id, run_id, actor, db)


def cancel(project_id, run_id, actor, db):
    row = own(project_id, run_id, actor, db, True)
    contract.require(row.actor_id == actor.id, "case_analysis_cancel_forbidden")
    contract.require(row.status in ACTIVE)
    row.status = "CANCELLED"
    row.updated_at = datetime.now(UTC)
    db.commit()
    return detail(project_id, run_id, actor, db)


def retry(project_id, run_id, request_id, actor, db):
    original = own(project_id, run_id, actor, db, True)
    prior = db.scalar(
        select(CaseAnalysisRun).where(
            CaseAnalysisRun.project_id == project_id,
            CaseAnalysisRun.request_id == str(request_id),
        )
    )
    if prior:
        contract.require(prior.parent_id == run_id)
        return detail(project_id, prior.id, actor, db)
    contract.require(original.status in ("FAILED", "CANCELLED"))
    sources.recheck(project_id, original.metadata_snapshot, actor, db)
    data = copy.deepcopy(original.input_snapshot)
    data["request_id"] = str(request_id)
    row = CaseAnalysisRun(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(request_id),
        parent_id=run_id,
        title=original.title,
        mode=original.mode,
        status="PREPARED",
        input_snapshot=data,
        metadata_snapshot=copy.deepcopy(original.metadata_snapshot),
        report={},
        handling={},
        ai_config={"call_mode": original.ai_config.get("call_mode", "RESPONSES_API")},
        attempts=[],
    )
    db.add(row)
    db.commit()
    return detail(project_id, row.id, actor, db)


def handling(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    contract.require(row.revision == payload.revision, "case_analysis_revision_conflict")
    f = next((f for f in items(row) if f["key"] == payload.key), None)
    contract.require(f is not None and (payload.state == "待确认" or payload.comment.strip()))
    data = copy.deepcopy(row.handling)
    h = data.setdefault(payload.key, {"history": [], "draft_revision": 0})
    if payload.draft:
        contract.require(not h.get("applied"), "case_analysis_already_applied")
        contract.require(payload.evidence_checked and f["kind"] not in ("QUESTION", "SETUP"))
        contract.require(
            all(getattr(payload.draft, k).strip() for k in ("title", "steps", "expected"))
        )
        target = None
        if f["case_ids"]:
            contract.require(len(f["case_ids"]) == 1, "case_analysis_choose_single_target")
            c = (
                db.execute(
                    cases.case_query(project_id).where(cases.ManagedCase.id == f["case_ids"][0])
                )
                .mappings()
                .first()
            )
            contract.require(
                c and c["version"] == payload.target_version and c["lifecycle"] == "ACTIVE",
                "case_analysis_target_changed",
            )
            target = dict(c)
        cases.category(project_id, payload.category_id or None, db)
        h.update(
            draft=payload.draft.model_dump(),
            target=target,
            category_id=payload.category_id or None,
            draft_revision=h["draft_revision"] + 1,
        )
    h.update(state=payload.state, comment=payload.comment)
    h["history"].append(
        {
            "actor_id": actor.id,
            "time": datetime.now(UTC).isoformat(),
            "state": payload.state,
            "comment": payload.comment,
        }
    )
    row.handling, row.revision, row.updated_at = data, row.revision + 1, datetime.now(UTC)
    db.commit()
    return detail(project_id, run_id, actor, db)


def chat(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    prior = db.scalar(
        select(CaseAnalysisChatTurn).where(
            CaseAnalysisChatTurn.run_id == run_id,
            CaseAnalysisChatTurn.request_id == str(payload.request_id),
        )
    )
    if prior:
        contract.require(
            prior.actor_id == actor.id
            and prior.question == payload.question
            and prior.finding_key == payload.finding_key
            and prior.function_key == payload.function_key
        )
        return detail(project_id, run_id, actor, db)
    contract.require(
        not payload.finding_key or any(f["key"] == payload.finding_key for f in items(row))
    )
    contract.require(
        not payload.function_key
        or payload.function_key in {c["module"] for c in row.input_snapshot["cases"]}
    )
    contract.require(
        not db.scalar(
            select(CaseAnalysisChatTurn.id).where(
                CaseAnalysisChatTurn.run_id == run_id,
                CaseAnalysisChatTurn.function_key == payload.function_key,
                CaseAnalysisChatTurn.status.in_(ACTIVE),
            )
        ),
        "case_analysis_chat_busy",
    )
    sources.recheck(project_id, row.metadata_snapshot, actor, db)
    config, _ = analysis_configuration(actor, db)
    messages = []
    for t in db.scalars(
        select(CaseAnalysisChatTurn)
        .where(
            CaseAnalysisChatTurn.run_id == run_id,
            CaseAnalysisChatTurn.function_key == payload.function_key,
            CaseAnalysisChatTurn.status == "COMPLETED",
        )
        .order_by(CaseAnalysisChatTurn.id)
    ):
        messages.extend(
            [{"role": "user", "content": t.question}, {"role": "assistant", "content": t.answer}]
        )
    context = {
        "input": row.input_snapshot,
        "report": row.report,
        "handling": row.handling,
        "finding_key": payload.finding_key,
        "messages": messages,
    }
    contract.require(
        len(json.dumps(context, ensure_ascii=False).encode()) <= contract.LIMIT,
        "case_analysis_input_too_large",
    )
    db.add(
        CaseAnalysisChatTurn(
            run_id=run_id,
            actor_id=actor.id,
            request_id=str(payload.request_id),
            function_key=payload.function_key,
            finding_key=payload.finding_key,
            question=payload.question,
            context=context,
            ai_config=configuration_snapshot(config),
            status="QUEUED",
        )
    )
    db.commit()
    return detail(project_id, run_id, actor, db)


def from_chat(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    contract.require(row.revision == payload.revision, "case_analysis_revision_conflict")
    turn = db.get(CaseAnalysisChatTurn, payload.turn_id)
    contract.require(turn and turn.run_id == run_id and turn.status == "COMPLETED")
    f = payload.finding.model_dump(mode="json")
    report = {
        "findings": [f] if f["kind"] not in ("SETUP", "QUESTION") else [],
        "notes": [f] if f["kind"] in ("SETUP", "QUESTION") else [],
        "checked_case_ids": [],
        "complete": False,
    }
    contract.validate(row.input_snapshot, report)
    contract.require(f["key"] not in {x["key"] for x in items(row)})
    h = copy.deepcopy(row.handling)
    h.setdefault("manual", []).append({**f, "origin_turn_id": turn.id})
    row.handling, row.revision = h, row.revision + 1
    db.commit()
    return detail(project_id, run_id, actor, db)


def import_report(project_id, payload, actor, db):
    documents.access(project_id, actor, db)
    contract.require(payload.input.get("project_id") == project_id)
    row = db.scalar(
        select(CaseAnalysisRun).where(
            CaseAnalysisRun.project_id == project_id,
            CaseAnalysisRun.request_id == payload.input.get("request_id"),
        )
    )
    contract.require(
        row and row.input_snapshot == payload.input, "case_analysis_fixed_input_required"
    )
    sources.recheck(project_id, row.metadata_snapshot, actor, db)
    report = contract.validate(payload.input, payload.report)
    row = own(project_id, row.id, actor, db, True)
    if row.report:
        contract.require(row.report == report, "case_analysis_import_conflict")
    else:
        contract.require(row.status not in ACTIVE)
        row.report, row.status, row.error_code = report, "COMPLETED", ""
        db.commit()
    return detail(project_id, row.id, actor, db)
