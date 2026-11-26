"""Project records, fixed plans and independent human review/audit."""

import copy
import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select

from app.core.errors import AppError
from app.db.models import (
    CaseGenerationApplication,
    CaseGenerationBatch,
    CaseGenerationRun,
    DocumentVersion,
)
from app.integrations.response_diagnostics import safe_snapshot
from app.modules.ai.service import (
    analysis_configuration,
    configuration_revision,
    configuration_snapshot,
    current_metadata,
)
from app.modules.case_generation import contract, delivery_files, native_rounds, sources
from app.modules.cases.schemas import DESIGN_FIELDS
from app.modules.documents import service as documents
from app.modules.projects.record_deletion import require_visible

ACTIVE = {"QUEUED", "RUNNING"}


def own(project_id, run_id, actor, db, lock=False):
    documents.access(project_id, actor, db, lock=lock)
    query = select(CaseGenerationRun).where(
        CaseGenerationRun.id == run_id, CaseGenerationRun.project_id == project_id
    )
    if lock:
        query = query.with_for_update()
    row = db.scalar(query.execution_options(populate_existing=True))
    if row is None:
        raise AppError(404, "generation_not_found")
    require_visible(row)
    return row


def batches(row, db):
    return list(
        db.scalars(
            select(CaseGenerationBatch)
            .where(CaseGenerationBatch.run_id == row.id)
            .order_by(CaseGenerationBatch.id)
        )
    )


def reports(row, db, fixed_batches=None):
    bs = batches(row, db) if fixed_batches is None else fixed_batches
    return [(b.input_snapshot, b.report) for b in bs if b.status == "COMPLETED"]


def suggestion_map(row, db, fixed_batches=None):
    mapping = {
        s["key"]: (i, s) for i, r in reports(row, db, fixed_batches) for s in r["suggestions"]
    }
    mapping.update(
        {
            key: (value["input"], value["suggestion"])
            for key, value in row.handling.get("manual_suggestions", {}).items()
        }
    )
    return mapping


def question_map(row, db):
    return {q["key"]: (i, q) for i, r in reports(row, db) for q in r["requirement_questions"]}


def function_views(row, db, fixed_batches=None):
    functions, keys = {}, {}
    for data, report in reports(row, db, fixed_batches):
        for f in data["scope"]["functions"]:
            functions[f["function_ref"]] = f["name"]
        for q in report["requirement_questions"]:
            keys[q["key"]] = q["function_ref"]
    for data, s in suggestion_map(row, db, fixed_batches).values():
        label = design_for(data, s)["module"] or functions[s["function_ref"]]
        key = "module-" + contract.digest([s["function_ref"], label])[:24]
        functions[key], keys[s["key"]] = label, key
    return functions, keys


def design_for(data, suggestion):
    if suggestion["kind"] == "NEW":
        return copy.deepcopy(suggestion["design"])
    target = next(c for c in data["cases"] if c["case_ref"] == suggestion["case_ref"])
    design = copy.deepcopy(target["design"])
    for patch in suggestion["changes"]:
        design[patch["field"]] = patch["after"]
    return design


def bundle(row, db, kind, fixed_batches=None):
    bs = batches(row, db) if fixed_batches is None else fixed_batches
    if len(bs) == 1 and (kind == "input" or bs[0].status == "COMPLETED"):
        return bs[0].input_snapshot if kind == "input" else bs[0].report
    return {
        "analysis_type": "CASE_GENERATION_BUNDLE",
        "contract_version": row.input_snapshot["contract_version"],
        "project_id": row.project_id,
        "request_id": row.request_id,
        "batches": [
            {
                "batch_ref": b.batch_ref,
                "request_id": b.request_id,
                "status": b.status,
                kind: b.input_snapshot if kind == "input" else b.report,
            }
            for b in bs
        ],
    }


def collision_keys(row, db, fixed_batches=None):
    identities = {}
    for _, report in reports(row, db, fixed_batches):
        if report.get("contract_version") == 3:
            for s in report["suggestions"]:
                identity = (s["kind"], s["case_ref"], contract.digest(design_for(_, s)))
                identities.setdefault(identity, []).append(s["key"])
            continue
        scenario_keys = {s["key"]: s["semantic_key"] for s in report["scenarios"]}
        for s in report["suggestions"]:
            identity = tuple(sorted(scenario_keys[k] for k in s["scenario_refs"]))
            identities.setdefault(identity, []).append(s["key"])
    return {key for keys in identities.values() if len(keys) > 1 for key in keys}


def batch_progress(batch):
    attempt = next((a for a in batch.attempts if a["request_id"] == batch.request_id), {})
    return {
        "startedAt": attempt.get("started_at"),
        "progressAt": attempt.get("progress_at"),
        "diagnostics": {
            k: v for k, v in safe_snapshot(attempt.get("diagnostics", {})).items() if k != "events"
        },
    }


def batch_timing(request_id, status, attempt):
    current = attempt if attempt.get("request_id") == request_id else {}
    # Cancelled/interrupted attempts only have saved progress, never use later review timestamps.
    finished = None if status == "RUNNING" else current.get("progress_at")
    return {
        "startedAt": current.get("started_at") if status == "RUNNING" or finished else None,
        "finishedAt": finished,
    }


def projection(row, actor, db):
    require_visible(row)
    data = row.input_snapshot
    bs = batches(row, db)
    personal = current_metadata(actor, db)
    pair_for = {p["after_ref"]: p for p in data.get("update_pairs", [])}
    bindings = {b["snapshot_ref"]: b for b in row.metadata_snapshot.get("bindings", [])}
    version_ids = {
        binding["version_id"] for binding in bindings.values() if binding.get("version_id")
    }
    versions = (
        {
            v.id: v
            for v in db.scalars(select(DocumentVersion).where(DocumentVersion.id.in_(version_ids)))
        }
        if version_ids
        else {}
    )
    materials = []
    for m in data.get("materials", []):
        b = bindings.get(m["snapshot_ref"], {})
        p = pair_for.get(m["snapshot_ref"])
        version = versions.get(b.get("version_id"))
        before = next(
            (v for v in data["materials"] if p and v["snapshot_ref"] == p["before_ref"]), None
        )
        materials.append(
            {
                "sourceId": m["snapshot_ref"],
                "documentId": b.get("document_id"),
                "name": m["name"],
                "purpose": m["kind"],
                "kind": b.get("kind", "FILE"),
                "version": m["version_ref"].removeprefix("version-"),
                "versionName": f"v{version.number} · {version.filename}"
                if version
                else m["version_ref"],
                "side": m["side"],
                "before": before["version_ref"].removeprefix("version-") if before else "",
                "update": "增量补充"
                if p and p["update_mode"] == "INCREMENTAL_SUPPLEMENT"
                else "完整替换"
                if p
                else "",
                "paths": b.get("paths", []),
                "readState": m["read_state"],
                "segments": [
                    {
                        "id": s["segment_id"],
                        "location": s["location"],
                        "text": s["text"] or "实际附件；本页不重做图像解读",
                    }
                    for s in m["segments"]
                ],
            }
        )
    suggestions, questions, details = [], [], []
    round_by_ref = {b.batch_ref: native_rounds.info(b) for b in bs if native_rounds.info(b)}
    function_labels, function_keys = function_views(row, db, bs)
    render_pairs = reports(row, db, bs) + [
        (
            m["input"],
            {
                "suggestions": [m["suggestion"]],
                "evidence": m["evidence"],
                "requirement_questions": [],
                "limitations": [],
            },
        )
        for m in row.handling.get("manual_suggestions", {}).values()
    ]
    for i, r in render_pairs:
        ev = {e["key"]: e for e in r["evidence"]}
        fs = {f["function_ref"]: f["name"] for f in i["scope"]["functions"]}
        cs = {c["case_ref"]: c for c in i["cases"]}
        for s in r["suggestions"]:
            c = cs.get(s["case_ref"])
            suggestions.append(
                {
                    "key": s["key"],
                    **(
                        {"nativeResultId": round_by_ref[r["batch_ref"]]["id"]}
                        if r.get("batch_ref") in round_by_ref
                        else {}
                    ),
                    "kind": s["kind"],
                    "function": function_labels[function_keys[s["key"]]],
                    "functionRef": function_keys[s["key"]],
                    "design": design_for(i, s),
                    "before": c["design"] if c else None,
                    "generated": c["baseline"]["design"] if c and c["baseline"] else None,
                    "caseId": c["case_id"] if c else None,
                    "baseVersion": s["base_version"],
                    "reason": s["reason"],
                    "blocked": s["basis_status"] == "NEEDS_REVIEW",
                    "evidence": [
                        {
                            "source": ev[k]["target_ref"],
                            "segment": ev[k]["segment_id"] or ev[k]["field"] or ev[k]["kind"],
                            "side": ev[k]["side"],
                            "quote": ev[k]["quote"] or ev[k]["note"],
                            "verifiedQuote": ev[k]["kind"] == "MATERIAL"
                            and bool(ev[k]["quote"])
                            and ev[k].get("quote_verified") is not False,
                            **(
                                {"quoteWarning": ev[k]["note"]}
                                if ev[k].get("quote_verified") is False
                                else {}
                            ),
                        }
                        for k in s["evidence_refs"]
                    ],
                }
            )
        for q in r["requirement_questions"]:
            questions.append(
                {
                    "key": q["key"],
                    **(
                        {"nativeResultId": round_by_ref[r["batch_ref"]]["id"]}
                        if r.get("batch_ref") in round_by_ref
                        else {}
                    ),
                    "function": fs[q["function_ref"]],
                    "functionRef": q["function_ref"],
                    "title": q["question"],
                    "text": q["impact"],
                    "evidence": "\n".join(
                        ev[k]["quote"] or ev[k]["note"] for k in q["evidence_refs"]
                    ),
                }
            )
        if r.get("contract_version") in {2, 3}:
            details.append(r)
    # Old semantic mappings and compact exact duplicates both remain reviewable.
    collisions = collision_keys(row, db, bs)
    for s in suggestions:
        if s["key"] in collisions:
            s["blocked"] = True
            s["reason"] += "；跨批存在同场景候选，需人工核对重复。"
    handling = copy.deepcopy(row.handling.get("suggestions", {}))
    outcome = (
        "COMPLETE"
        if bs
        and all(b.status == "COMPLETED" and b.report.get("outcome") == "COMPLETE" for b in bs)
        and not collisions
        else "PARTIAL"
        if details
        else "BLOCKED"
        if row.status in {"FAILED", "COMPLETED", "CANCELLED"}
        else ""
    )
    if (
        data.get("contract_version") == 2
        and data.get("scope", {}).get("full_scope")
        and any(
            m["read_state"] != "READABLE"
            for m in data.get("materials", [])
            if m["kind"] in {"REQUIREMENT", "PROTOTYPE"}
        )
        and outcome == "COMPLETE"
    ):
        outcome = "PARTIAL"
    return {
        "id": str(row.id),
        "projectId": row.project_id,
        "ownerId": row.actor_id,
        "title": row.title,
        "createdAt": row.created_at.isoformat(),
        "timings": [
            batch_timing(b.request_id, b.status, b.attempts[-1] if b.attempts else {}) for b in bs
        ],
        "mode": row.mode,
        "origin": "SERVER",
        "cancelled": row.status == "CANCELLED",
        "status": row.status,
        "serverRevision": row.revision,
        "canCancel": any(b.actor_id == actor.id and b.status in ACTIVE | {"PREPARED"} for b in bs),
        "scope": data.get("scope", {}).get("name", ""),
        "focus": data.get("focus", ""),
        "materials": materials,
        "cases": [],
        "caseScope": data.get("scope", {}).get("case_scope", {}).get("description", ""),
        "libraryRevision": data.get("scope", {}).get("case_scope", {}).get("library_revision"),
        "baselineId": "",
        "suggestions": suggestions,
        "questions": questions,
        "candidateIssues": [
            {
                **problem,
                **(
                    {"nativeResultId": native_rounds.info(batch)["id"]}
                    if native_rounds.info(batch)
                    else {}
                ),
            }
            for batch in bs
            for problem in delivery_files.views(batch, actor)
        ],
        "nativeRounds": native_rounds.summaries(bs),
        "handling": handling,
        "decisions": row.handling.get("decisions", []),
        "failures": row.handling.get("failures", []),
        "failureHistory": row.handling.get("failure_history", []),
        "chatDrafts": {},
        "batches": [
            {
                "key": b.batch_ref,
                "id": b.id,
                **(
                    {"nativeResultId": native_rounds.info(b)["id"]} if native_rounds.info(b) else {}
                ),
                "terminalAvailable": bool(
                    b.ai_config.get("generation_terminal") and b.actor_id == actor.id
                ),
                "function": b.input_snapshot["scope"]["name"],
                "status": b.status,
                "attempts": len(b.attempts)
                + (
                    1
                    if b.status not in {"PREPARED", "QUEUED"}
                    and not any(a["request_id"] == b.request_id for a in b.attempts)
                    else 0
                ),
                "attemptHistory": [
                    {k: v for k, v in a.items() if k != "input_snapshot"} for a in b.attempts
                ],
                "reason": b.error_code,
                "requestId": b.request_id,
                "candidateAvailable": bool(b.attempts and b.attempts[-1].get("candidate")),
                "inputBytes": len(json.dumps(b.input_snapshot, ensure_ascii=False).encode()),
                **batch_progress(b),
            }
            for b in bs
        ],
        "limitations": data.get("input_limitations", [])
        + [
            f"{b.batch_ref}：平台已兼容修正{len(a['format_repairs']['fields'])}处字段格式，原始响应保留；业务内容仍需人工审阅。"
            for b in bs
            for a in b.attempts
            if a.get("request_id") == b.request_id and a.get("format_repairs")
        ]
        + [
            limitation
            for r in details
            for limitation in r["limitations"]
            if limitation not in data.get("input_limitations", [])
        ],
        "outcome": outcome,
        "inputText": json.dumps(
            row.metadata_snapshot.get("original_input") or bundle(row, db, "input", bs),
            ensure_ascii=False,
            indent=2,
        ),
        "reportText": json.dumps(
            row.metadata_snapshot.get("original_report") or bundle(row, db, "report", bs),
            ensure_ascii=False,
            indent=2,
        ),
        "rawReports": details,
        "applications": [
            {
                "id": a.id,
                "requestId": a.request_id,
                "status": a.status,
                "items": a.items,
                "error": a.error_code,
            }
            for a in db.scalars(
                select(CaseGenerationApplication)
                .where(CaseGenerationApplication.run_id == row.id)
                .order_by(CaseGenerationApplication.id)
            )
        ],
        "planNote": sources.input_notice(
            data,
            row.metadata_snapshot.get("skill", {}).get("instructions", ""),
            row.metadata_snapshot.get("attachment_bytes", 0),
        )
        if len(bs) == 1
        else "同一对话保留各轮候选及独立审核记录。"
        if round_by_ref
        else "历史分批记录：保留已完成成果；失败仅人工重试原固定输入。",
        "skillVersion": row.metadata_snapshot.get("skill", {}).get("version", ""),
        "aiPreview": personal,
        "ai_config": bs[0].ai_config if bs else {},
    }


def detail(project_id, run_id, actor, db):
    return projection(own(project_id, run_id, actor, db), actor, db)


def listing(project_id, actor, db, page=1, summary=False):
    documents.access(project_id, actor, db)
    if summary:
        return list_summaries(project_id, actor, db, page)
    rows = list(
        db.scalars(
            select(CaseGenerationRun)
            .where(
                CaseGenerationRun.project_id == project_id, CaseGenerationRun.deleted_at.is_(None)
            )
            .order_by(CaseGenerationRun.id.desc())
            .offset((page - 1) * 20)
            .limit(21)
        )
    )
    return {"items": [projection(r, actor, db) for r in rows[:20]], "has_more": len(rows) > 20}


def read_summary(project_id, run_id, actor, db):
    documents.access(project_id, actor, db)
    result = list_summaries(project_id, actor, db, 1, run_id)
    if not result["items"]:
        raise AppError(404, "generation_not_found")
    return result


def list_summaries(project_id, actor, db, page, run_id=None):
    # Select scalar metadata only: historical attempt snapshots can be many MiB.
    rows = list(
        db.execute(
            select(
                CaseGenerationRun.id,
                CaseGenerationRun.project_id,
                CaseGenerationRun.actor_id,
                CaseGenerationRun.title,
                CaseGenerationRun.created_at,
                CaseGenerationRun.updated_at,
                CaseGenerationRun.mode,
                CaseGenerationRun.status,
                CaseGenerationRun.revision,
                func.jsonb_array_length(CaseGenerationRun.input_snapshot["materials"]).label(
                    "material_count"
                ),
            )
            .where(
                CaseGenerationRun.project_id == project_id,
                CaseGenerationRun.deleted_at.is_(None),
                CaseGenerationRun.id == run_id if run_id is not None else True,
            )
            .order_by(CaseGenerationRun.id.desc())
            .offset((page - 1) * 20)
            .limit(21)
        )
    )
    selected = rows[:20]
    if not selected:
        return {"items": [], "has_more": False}
    ids = [r.id for r in selected]
    progress = {i: [] for i in ids}
    timings = {i: [] for i in ids}
    active = set()
    for b in db.execute(
        select(
            CaseGenerationBatch.run_id,
            CaseGenerationBatch.id,
            CaseGenerationBatch.status,
            CaseGenerationBatch.request_id,
            CaseGenerationBatch.updated_at,
            CaseGenerationBatch.error_code,
            CaseGenerationBatch.attempts[-1]["progress_at"].astext.label("progress_at"),
            CaseGenerationBatch.attempts[-1]["candidate"].astext,
            CaseGenerationBatch.attempts[-1]["request_id"].astext.label("attempt_request_id"),
            CaseGenerationBatch.attempts[-1]["started_at"].astext.label("started_at"),
        )
        .where(CaseGenerationBatch.run_id.in_(ids))
        .order_by(CaseGenerationBatch.id)
    ):
        progress[b.run_id].append(list(b)[1:])
        timings[b.run_id].append(
            batch_timing(
                b.request_id,
                b.status,
                {
                    "request_id": b.attempt_request_id,
                    "started_at": b.started_at,
                    "progress_at": b.progress_at,
                },
            )
        )
        if b.status in ACTIVE:
            active.add(b.run_id)
    for a in db.execute(
        select(
            CaseGenerationApplication.run_id,
            CaseGenerationApplication.id,
            CaseGenerationApplication.status,
            CaseGenerationApplication.updated_at,
            CaseGenerationApplication.error_code,
        )
        .where(CaseGenerationApplication.run_id.in_(ids))
        .order_by(CaseGenerationApplication.id)
    ):
        progress[a.run_id].append(list(a)[1:])
        if a.status in ACTIVE:
            active.add(a.run_id)
    personal_version = configuration_revision(actor, db)
    return {
        "items": [
            {
                "id": str(r.id),
                "projectId": r.project_id,
                "ownerId": r.actor_id,
                "title": r.title,
                "createdAt": r.created_at.isoformat(),
                "timings": timings[r.id],
                "mode": r.mode,
                "status": r.status,
                "serverRevision": r.revision,
                "hasMaterials": bool(r.material_count),
                "active": r.id in active or r.status in ACTIVE,
                "refreshKey": contract.digest(
                    [r.revision, r.status, str(r.updated_at), str(progress[r.id]), personal_version]
                ),
            }
            for r in selected
        ],
        "has_more": len(rows) > 20,
    }


def prepare(project_id, payload, actor, db):
    documents.access(project_id, actor, db, lock=True)
    request_query = select(CaseGenerationRun).where(
        CaseGenerationRun.project_id == project_id,
        CaseGenerationRun.actor_id == actor.id,
        CaseGenerationRun.request_id == str(payload.request_id),
    )
    previous = db.scalar(request_query)
    fingerprint = contract.digest(sources.preparation_request(payload))
    if previous:
        require_visible(previous)
        contract.require(
            previous.metadata_snapshot.get("request_hash") == fingerprint,
            "generation_request_conflict",
        )
        return projection(previous, actor, db)
    data, metadata = sources.prepare(project_id, payload, actor, db)
    planned = sources.plan(data)
    sources.recheck(project_id, metadata, actor, db)
    # Remote reads release the initial lock; another request may have finished meanwhile.
    documents.access(project_id, actor, db, lock=True)
    previous = db.scalar(request_query.execution_options(populate_existing=True))
    if previous:
        require_visible(previous)
        contract.require(
            previous.metadata_snapshot.get("request_hash") == fingerprint,
            "generation_request_conflict",
        )
        return projection(previous, actor, db)
    row = CaseGenerationRun(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        title=payload.title.strip(),
        mode=payload.mode,
        input_snapshot=data,
        metadata_snapshot=metadata,
        handling={},
    )
    contract.require(row.title)
    db.add(row)
    db.flush()
    for value in planned:
        db.add(
            CaseGenerationBatch(
                run_id=row.id,
                batch_ref=value["batch"]["batch_ref"],
                request_id=value["request_id"],
                actor_id=actor.id,
                input_snapshot=value,
                report={},
                ai_config={},
                attempts=[],
            )
        )
    db.commit()
    return projection(row, actor, db)


def start(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    if row.status in ACTIVE | {"COMPLETED"}:
        return projection(row, actor, db)
    contract.require(
        row.status == "PREPARED" and row.revision == payload.revision, "generation_changed"
    )
    contract.require(row.actor_id == actor.id, "generation_owner_only")
    sources.recheck(project_id, row.metadata_snapshot, actor, db)
    config, _ = analysis_configuration(
        actor,
        db,
        payload.ai_version,
        mode=payload.ai_call_mode or "RESPONSES_API",
        preference_version=payload.ai_preference_version,
    )
    for b in batches(row, db):
        b.ai_config = configuration_snapshot(config)
        if config.get("call_mode") == "CODEX_EXEC":
            b.ai_config = {
                **b.ai_config,
                "generation_terminal": {
                    "identity": str(uuid4()),
                    "execution": -b.id,
                    "version": 1,
                },
            }
        b.status = "QUEUED"
    row.status = "QUEUED"
    row.updated_at = datetime.now(UTC)
    db.commit()
    return projection(row, actor, db)


def cancel(project_id, run_id, actor, db):
    row = own(project_id, run_id, actor, db, True)
    bs = batches(row, db)
    contract.require(any(b.actor_id == actor.id for b in bs), "generation_owner_only")
    if row.status in ACTIVE | {"PREPARED"}:
        for b in bs:
            if b.actor_id == actor.id and b.status in ACTIVE | {"PREPARED"}:
                b.status = "CANCELLED"
        row.status = "RUNNING" if any(b.status in ACTIVE for b in bs) else "CANCELLED"
        row.updated_at = datetime.now(UTC)
        db.commit()
    return projection(row, actor, db)


def retry(project_id, run_id, batch_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    b = db.get(CaseGenerationBatch, batch_id, with_for_update=True)
    contract.require(b and b.run_id == row.id)
    if b.input_snapshot.get("contract_version") == 2:
        raise AppError(409, "generation_legacy_contract_retry_unsupported")
    if native_rounds.info(b):
        raise AppError(422, "generation_native_round_retry_forbidden")
    if b.request_id == str(payload.request_id):
        return projection(row, actor, db)
    contract.require(
        b.status in {"FAILED", "CANCELLED"} and row.metadata_snapshot.get("origin") == "AI",
        "generation_retry_invalid",
    )
    contract.require(
        not db.scalar(
            select(CaseGenerationApplication.id).where(
                CaseGenerationApplication.run_id == run_id,
                CaseGenerationApplication.status.in_(ACTIVE),
            )
        ),
        "generation_application_busy",
    )
    sources.recheck(project_id, row.metadata_snapshot, actor, db)
    config, _ = analysis_configuration(
        actor, db, mode=b.ai_config.get("call_mode", "RESPONSES_API")
    )
    previous = {
        "request_id": b.request_id,
        "status": b.status,
        "error": b.error_code,
        "actor_id": b.actor_id,
        "input_snapshot": copy.deepcopy(b.input_snapshot),
        "ai_config": copy.deepcopy(b.ai_config),
    }
    attempts = copy.deepcopy(b.attempts)
    for attempt in attempts:
        if attempt.get("request_id") == b.request_id:
            attempt.setdefault("ai_config", copy.deepcopy(b.ai_config))
    if not attempts or attempts[-1].get("request_id") != b.request_id:
        attempts.append(previous)
    b.attempts = attempts
    b.input_snapshot = {**b.input_snapshot, "request_id": str(payload.request_id)}
    b.request_id, b.actor_id, b.status, b.error_code = (
        str(payload.request_id),
        actor.id,
        "QUEUED",
        "",
    )
    b.ai_config = configuration_snapshot(config)
    if config.get("call_mode") == "CODEX_EXEC":
        b.ai_config = {
            **b.ai_config,
            "generation_terminal": {
                "identity": str(uuid4()),
                "execution": -b.id,
                "version": 1,
            },
        }
    row.status = "QUEUED"
    row.updated_at = datetime.now(UTC)
    db.commit()
    return projection(row, actor, db)


def handle(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    contract.require(row.revision == payload.revision, "generation_changed")
    mapping = suggestion_map(row, db)
    contract.require(payload.key in mapping)
    i, s = mapping[payload.key]
    h = copy.deepcopy(row.handling)
    history = h.setdefault("suggestions", {}).setdefault(payload.key, [])
    contract.require(
        not history or history[-1]["status"] not in {"已应用", "已复用"},
        "generation_already_applied",
    )
    contract.require(payload.ignored or payload.evidence_checked)
    contract.require(
        not (payload.ignored or s["basis_status"] == "NEEDS_REVIEW") or payload.note.strip(),
        "generation_note_required",
    )
    draft = payload.draft.model_dump()
    if payload.category_id:
        from app.modules.cases import service as case_service

        case_service.category(project_id, payload.category_id, db)
    contract.require(
        payload.ignored
        or s["kind"] not in {"NEW", "UPDATE"}
        or all(draft[k].strip() for k in ("title", "steps", "expected"))
    )
    if s["kind"] in {"REUSE", "RETIRE"}:
        contract.require(draft == design_for(i, s))
    reviewed = None
    if payload.target_version:
        from app.modules.cases import service as case_service

        c = next(c for c in i["cases"] if c["case_ref"] == s["case_ref"])
        actual = case_service.detail(project_id, c["case_id"], actor, db)
        current = actual["versions"][0]
        contract.require(current["number"] == payload.target_version, "generation_case_changed")
        reviewed = {
            "id": c["case_id"],
            "version": current["number"],
            "design": {f: current[f] for f in DESIGN_FIELDS},
        }
        original = design_for(i, s)
        requested = (
            {p["field"] for p in s["changes"]}
            | set(payload.edited_fields)
            | {f for f in DESIGN_FIELDS if draft[f] != original[f]}
        )
        for field in DESIGN_FIELDS:
            if field not in requested:
                draft[field] = current[field]
    history.append(
        {
            "draft": draft,
            "note": payload.note,
            "status": "已忽略" if payload.ignored else "待审阅",
            "actor": actor.display_name,
            "actor_id": actor.id,
            "time": datetime.now(UTC).isoformat(),
            "revision": (history[-1]["revision"] if history else 0) + 1,
            "evidenceChecked": payload.evidence_checked,
            "resolved": payload.resolved and payload.evidence_checked and not payload.ignored,
            **({"reviewedTarget": reviewed} if reviewed else {}),
            **({"categoryId": payload.category_id} if payload.category_id is not None else {}),
            "editedFields": payload.edited_fields,
        }
    )
    row.handling, row.revision, row.updated_at = h, row.revision + 1, datetime.now(UTC)
    db.commit()
    return projection(row, actor, db)


def decide(project_id, run_id, payload, actor, db):
    row = own(project_id, run_id, actor, db, True)
    contract.require(row.revision == payload.revision, "generation_changed")
    qs = question_map(row, db)
    contract.require(payload.question_key in qs)
    _, q = qs[payload.question_key]
    h = copy.deepcopy(row.handling)
    history = h.setdefault("decisions", [])
    version = (
        max((d["version"] for d in history if d["questionKey"] == payload.question_key), default=0)
        + 1
    )
    history.append(
        {
            "key": f"{payload.question_key}-D{version}",
            "questionKey": q["key"],
            "function": q["function_ref"],
            "conclusion": payload.conclusion.strip(),
            "basis": payload.basis.strip(),
            "affected": payload.affected.strip(),
            "actor": actor.display_name,
            "actor_id": actor.id,
            "time": datetime.now(UTC).isoformat(),
            "version": version,
        }
    )
    contract.require(all(history[-1][k] for k in ("conclusion", "basis", "affected")))
    row.handling, row.revision = h, row.revision + 1
    db.commit()
    return projection(row, actor, db)


def supplement(project_id, run_id, payload, actor, db):
    old = own(project_id, run_id, actor, db, True)
    prior = db.scalar(
        select(CaseGenerationRun).where(
            CaseGenerationRun.project_id == project_id,
            CaseGenerationRun.actor_id == actor.id,
            CaseGenerationRun.request_id == str(payload.request_id),
        )
    )
    if prior:
        contract.require(
            prior.metadata_snapshot.get("parent_id") == old.id
            and prior.metadata_snapshot.get("decision_key") == payload.decision_key
        )
        return projection(prior, actor, db)
    contract.require(old.revision == payload.revision, "generation_changed")
    d = next(
        (d for d in old.handling.get("decisions", []) if d["key"] == payload.decision_key), None
    )
    contract.require(d, "generation_decision_required")
    original, q = question_map(old, db)[d["questionKey"]]
    data = copy.deepcopy(original)
    # Supplement is a new task; keep parent evidence while using today's compact protocol.
    data["contract_version"] = 3
    data["request_id"], data["revision"] = str(payload.request_id), data["revision"] + 1
    data["scope"]["name"] = d["affected"]
    data["scope"]["full_scope"] = False
    data["scope"]["functions"] = [
        f for f in data["scope"]["functions"] if f["function_ref"] == q["function_ref"]
    ]
    data["batch"].update(
        plan_ref=str(payload.request_id),
        batch_ref="supplement",
        namespace="supplement",
        index=1,
        total=1,
        function_refs=[q["function_ref"]],
    )
    decision = {
        "decision_ref": d["key"],
        "version": d["version"],
        "statement": d["conclusion"],
        "scope_note": d["affected"] + "；" + d["basis"],
        "function_refs": [q["function_ref"]],
        "actor": d["actor"],
        "confirmed_at": d["time"],
        "applicability": "VERIFIED_CURRENT",
        "supersedes": [],
        "origin": {"request_id": original["request_id"], "question_key": q["key"]},
        "basis_refs": [m["snapshot_ref"] for m in data["materials"]],
    }
    # Carry earlier confirmations; make replacement of this question's older decision explicit.
    older = [
        c
        for c in old.handling.get("decisions", [])
        if c["questionKey"] == d["questionKey"] and c["version"] < d["version"]
    ]
    decision["supersedes"] = [
        x["decision_ref"]
        for x in data["decisions"]
        if any(o["key"] == x["decision_ref"] for o in older)
    ]
    data["decisions"].append(decision)
    data["supplement"] = {
        "parent_request_id": original["request_id"],
        "decision_refs": [d["key"]],
        "affected_scenario_refs": q.get("scenario_refs", []),
        "scope_note": d["affected"],
    }
    data["focus"] += "\n仅补原问题关联场景及直接依赖，不重做已确认无关场景。"
    contract.validate_input(data)
    metadata = {
        k: copy.deepcopy(v)
        for k, v in old.metadata_snapshot.items()
        if k not in {"original_input", "original_report", "source_hash", "bindings_hash"}
    }
    metadata["origin"] = "AI"
    metadata["skill"] = sources.skill()
    metadata.update(
        parent_id=old.id,
        decision_key=d["key"],
        request_hash=contract.digest(payload.model_dump(mode="json")),
    )
    sources.recheck(project_id, metadata, actor, db)
    row = CaseGenerationRun(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        title=old.title[:190] + " · 澄清补生成",
        mode=old.mode,
        input_snapshot=data,
        metadata_snapshot=metadata,
        handling={},
    )
    db.add(row)
    db.flush()
    db.add(
        CaseGenerationBatch(
            run_id=row.id,
            batch_ref="supplement",
            request_id=data["request_id"],
            actor_id=actor.id,
            input_snapshot=data,
            report={},
            ai_config={},
            attempts=[],
        )
    )
    db.commit()
    return projection(row, actor, db)


async def read_payload(chunks, model):
    body = bytearray()
    async for chunk in chunks:
        if len(body) + len(chunk) > 3 * contract.LIMIT:
            raise AppError(413, "generation_input_too_large")
        body.extend(chunk)
    try:
        return model.model_validate(contract.json_object(body.decode("utf-8-sig")))
    except (UnicodeError, ValueError):
        raise AppError(422, "generation_contract_invalid") from None
