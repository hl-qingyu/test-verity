"""Project-owned risk reports; input/result validation and atomic human handling."""

import copy
import hashlib
import json
import logging
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, defer

from app.core.errors import AppError
from app.db.models import (
    DocumentVersion,
    RequirementChatTurn,
    RequirementManualRisk,
    RequirementRiskAnalysis,
    RequirementRiskReport,
    SourceDocument,
    UserAccount,
)
from app.modules.ai.native_terminal import TERMINAL_KEY
from app.modules.documents import service as documents
from app.modules.projects.record_deletion import require_visible, requirement_permissions
from app.modules.prototypes import directories
from app.modules.requirements import risk_schemas as schema

logger = logging.getLogger(__name__)
FILE_LIMIT = 16 * 1024 * 1024


def json_object(value: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError("invalid_number")

    try:
        result = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
        pending = [result]
        while pending:
            item = pending.pop()
            if isinstance(item, str):
                if "\x00" in item:
                    raise ValueError("null_character")
                item.encode("utf-8")
            elif isinstance(item, dict):
                pending.extend(item.keys())
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)
            elif isinstance(item, float) and not math.isfinite(item):
                raise ValueError("invalid_number")
        return result
    except (ValueError, UnicodeError, RecursionError):
        raise AppError(422, "risk_json_invalid") from None


def parse(model, data, prefix):
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        item = exc.errors(include_input=False, include_context=False)[0]
        # Extra field names are untrusted; never echo them into error responses/logs.
        allowed = set()
        for value in vars(schema).values():
            if isinstance(value, type) and issubclass(value, schema.Strict):
                allowed.update(value.model_fields)
        path = prefix
        for part in item["loc"]:
            path += (
                f"[{part}]" if type(part) is int else "." + (part if part in allowed else "field")
            )
        raise AppError(422, f"risk_report_invalid|{path}|{item['type']}") from None


def choices(project_id: int, actor: UserAccount, db: Session):
    documents.access(project_id, actor, db)
    sources = list(
        db.scalars(
            select(SourceDocument)
            .where(SourceDocument.project_id == project_id, SourceDocument.deleted_at.is_(None))
            .order_by(SourceDocument.id)
        )
    )
    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(DocumentVersion.project_id == project_id)
            .order_by(DocumentVersion.number.desc())
        )
    )
    return {
        "materials": [
            {
                "id": s.id,
                "name": s.name
                or next((v.filename for v in versions if v.document_id == s.id), "未命名资料"),
                "kind": s.kind,
                "url": s.url,
                "purpose": s.purpose,
                "versions": [
                    documents.version_view(v, db) for v in versions if v.document_id == s.id
                ],
            }
            for s in sources
        ]
    }


def own(project_id, report_id, actor, db, lock=False):
    documents.access(project_id, actor, db, lock=lock)
    report = db.scalar(
        select(RequirementRiskReport)
        .where(
            RequirementRiskReport.project_id == project_id, RequirementRiskReport.id == report_id
        )
        .execution_options(populate_existing=True)
        .with_for_update()
        if lock
        else select(RequirementRiskReport)
        .execution_options(populate_existing=True)
        .where(
            RequirementRiskReport.project_id == project_id, RequirementRiskReport.id == report_id
        )
    )
    if report is None:
        raise AppError(404, "risk_report_not_found")
    require_visible(report)
    return report


def review_warnings_by_report(project_id, db):
    rows = db.execute(
        select(
            RequirementRiskAnalysis.report_id,
            RequirementRiskAnalysis.context["review_warnings"],
        ).where(
            RequirementRiskAnalysis.project_id == project_id,
            RequirementRiskAnalysis.report_id.is_not(None),
        )
    )
    return {report_id: warnings or [] for report_id, warnings in rows}


def detail(project_id, report_id, actor, db, *, duplicate=False):
    row = own(project_id, report_id, actor, db)
    creator = db.get(UserAccount, row.created_by)
    terminal_task_id = db.scalar(
        select(RequirementRiskAnalysis.id)
        .where(
            RequirementRiskAnalysis.project_id == project_id,
            RequirementRiskAnalysis.report_id == report_id,
            RequirementRiskAnalysis.actor_id == actor.id,
            RequirementRiskAnalysis.deleted_at.is_(None),
            RequirementRiskAnalysis.ai_config.has_key(TERMINAL_KEY),
        )
        .order_by(RequirementRiskAnalysis.id.desc())
        .limit(1)
    )
    bindings = copy.deepcopy(row.bindings)
    for binding in bindings:
        source = db.get(SourceDocument, binding["document_id"])
        binding["deleted"] = source is None or source.deleted_at is not None
    return {
        "id": row.id,
        "project_id": row.project_id,
        "title": row.title,
        "created_by": creator.display_name if creator else "已删除账号",
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "revision": row.revision,
        "terminal_task_id": terminal_task_id,
        "input": row.input,
        "report": row.report,
        "review_warnings": review_warnings_by_report(project_id, db).get(row.id, []),
        "bindings": bindings,
        "handling": [{"risk_key": key, **value} for key, value in row.handling.items()],
        "manual_risks": [
            manual_view(item, db)
            for item in db.scalars(
                select(RequirementManualRisk)
                .where(RequirementManualRisk.report_id == row.id)
                .order_by(RequirementManualRisk.id)
            )
        ],
        "duplicate": duplicate,
    }


def listing(project_id, actor, db, page):
    documents.access(project_id, actor, db)
    rows = db.execute(
        select(
            RequirementRiskReport.id,
            RequirementRiskReport.title,
            RequirementRiskReport.created_at,
            RequirementRiskReport.report["outcome"].astext.label("outcome"),
            func.jsonb_array_length(RequirementRiskReport.report["functions"]).label("functions"),
            func.jsonb_array_length(RequirementRiskReport.report["risks"]).label("risks"),
            UserAccount.display_name.label("created_by"),
        )
        .join(UserAccount, UserAccount.id == RequirementRiskReport.created_by)
        .where(
            RequirementRiskReport.project_id == project_id,
            RequirementRiskReport.deleted_at.is_(None),
        )
        .order_by(RequirementRiskReport.id.desc())
        .limit(21)
        .offset((page - 1) * 20)
    ).all()
    return {
        "items": [
            {**dict(row._mapping), "created_at": row.created_at.isoformat()} for row in rows[:20]
        ],
        "has_more": len(rows) > 20,
    }


async def import_report(
    project_id: int, chunks: AsyncIterator[bytes], actor: UserAccount, db: Session
):
    documents.access(project_id, actor, db)
    actor_id = actor.id
    db.rollback()
    body = bytearray()
    async for chunk in chunks:
        if len(body) + len(chunk) > 4 * FILE_LIMIT:
            raise AppError(413, "risk_file_too_large")
        body.extend(chunk)
    try:
        payload = parse(schema.ImportPayload, json_object(body.decode("utf-8-sig")), "import")
    except (UnicodeError, RecursionError):
        raise AppError(422, "risk_json_invalid") from None
    for text in (payload.input_json, payload.report_json):
        if len(text.encode("utf-8")) > FILE_LIMIT:
            raise AppError(413, "risk_file_too_large")
    for filename in (payload.input_filename, payload.report_filename):
        schema.require(
            filename.lower().endswith(".json") and not any(c in filename for c in "/\\\x00"),
            "import",
            "invalid_filename",
        )
    schema.require(bool(payload.title.strip()), "import.title", "empty_title")
    input_data = parse(
        schema.AnalysisInput, json_object(payload.input_json.lstrip("\ufeff")), "input"
    )
    report = parse(schema.Report, json_object(payload.report_json.lstrip("\ufeff")), "report")
    schema.validate_report(report, input_data, project_id)
    mapping = schema.unique(payload.bindings, "source_id", "bindings")
    schema.require(
        set(mapping) == {m.source_id for m in input_data.materials},
        "bindings",
        "source_coverage_mismatch",
    )
    actor = db.get(UserAccount, actor_id, populate_existing=True)
    if actor is None:
        raise AppError(401, "not_authenticated")
    documents.access(project_id, actor, db, lock=True)
    bindings = []
    for material in input_data.materials:
        binding = mapping[material.source_id]
        source = db.scalar(
            select(SourceDocument).where(
                SourceDocument.id == binding.document_id,
                SourceDocument.project_id == project_id,
                SourceDocument.deleted_at.is_(None),
            )
        )
        if source is None or source.purpose != material.origin:
            raise AppError(422, "risk_source_unavailable")
        version = None
        if source.kind == "FILE":
            if binding.version_id is None:
                raise AppError(422, "risk_version_required")
            _, original = documents.stored_version(project_id, binding.version_id, actor, db)
            if original.document_id != source.id:
                raise AppError(422, "risk_source_unavailable")
            version = documents.version_view(original, db)
            if material.kind == "IMAGE" and original.extension not in (
                "png",
                "jpg",
                "jpeg",
                "webp",
            ):
                raise AppError(422, "risk_source_unavailable")
            if any(
                segment.image_ref for segment in material.segments
            ) and original.extension not in ("png", "jpg", "jpeg", "webp", "pdf"):
                raise AppError(422, "risk_source_unavailable")
        elif source.kind == "DIRECTORY":
            original, _ = directories.bind_material(
                project_id,
                source.id,
                binding.version_id,
                [s.model_dump() for s in material.segments],
                material.source_id,
                actor,
                db,
            )
            if original.sha256 != material.snapshot_ref:
                raise AppError(422, "risk_source_unavailable")
            version = documents.version_view(original, db)
        elif binding.version_id is not None or any(s.image_ref for s in material.segments):
            raise AppError(422, "risk_version_required")
        bindings.append(
            {
                "source_id": material.source_id,
                "document_id": source.id,
                "name": source.name or version["filename"],
                "kind": source.kind,
                "purpose": source.purpose,
                "version": version,
                "url": source.url,
                "branch": source.branch,
                "commit": source.latest_commit,
                "deleted": False,
            }
        )
    return store_report(
        project_id,
        payload.title,
        payload.input_filename,
        payload.report_filename,
        input_data.model_dump(),
        report.model_dump(),
        bindings,
        actor,
        db,
    )


def store_report(
    project_id,
    title,
    input_filename,
    report_filename,
    data,
    output,
    bindings,
    actor,
    db,
    *,
    commit=True,
):
    digest = hashlib.sha256(
        json.dumps(
            [data, output], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    prior = db.scalar(
        select(RequirementRiskReport).where(
            RequirementRiskReport.project_id == project_id, RequirementRiskReport.sha256 == digest
        )
    )
    if prior:
        if [
            (b["source_id"], b["document_id"], (b["version"] or {}).get("id"))
            for b in prior.bindings
        ] != [(b["source_id"], b["document_id"], (b["version"] or {}).get("id")) for b in bindings]:
            raise AppError(409, "risk_binding_conflict")
        return detail(project_id, prior.id, actor, db, duplicate=True)
    row = RequirementRiskReport(
        project_id=project_id,
        title=title.strip(),
        input_filename=input_filename,
        report_filename=report_filename,
        sha256=digest,
        input=data,
        report=output,
        bindings=bindings,
        handling={},
        created_by=actor.id,
    )
    db.add(row)
    if commit:
        db.commit()
    else:
        db.flush()
    logger.info("risk_report imported project=%s report=%s actor=%s", project_id, row.id, actor.id)
    return detail(project_id, row.id, actor, db)


def handle(project_id, report_id, payload: schema.HandlingInput, actor, db):
    row = own(project_id, report_id, actor, db, lock=True)
    if row.revision != payload.revision:
        raise AppError(409, "risk_report_changed")
    if not any(r["key"] == payload.risk_key for r in row.report["risks"]):
        raise AppError(404, "risk_item_not_found")
    old = row.handling.get(payload.risk_key, {"status": "PENDING", "note": "", "history": []})
    if old["status"] != payload.status or old["note"] != payload.note:
        now = datetime.now(UTC)
        handling = copy.deepcopy(row.handling)
        handling[payload.risk_key] = {
            "status": payload.status,
            "note": payload.note,
            "history": [
                *old["history"],
                {
                    "from": old["status"],
                    "to": payload.status,
                    "note": payload.note,
                    "actor": actor.display_name,
                    "actor_id": actor.id,
                    "time": now.isoformat(),
                },
            ],
        }
        row.handling = handling
        row.revision += 1
        row.updated_at = now
        db.commit()
        logger.info(
            "risk_report handled project=%s report=%s actor=%s revision=%s",
            project_id,
            row.id,
            actor.id,
            row.revision,
        )
    return detail(project_id, row.id, actor, db)


def manual_view(row: RequirementManualRisk, db: Session) -> dict:
    creator = db.get(UserAccount, row.created_by)
    return {
        "id": row.id,
        "report_id": row.report_id,
        "function_key": row.function_key,
        "message_turn_id": row.message_turn_id,
        "request_id": row.request_id,
        "title": row.title,
        "severity": row.severity,
        "type": row.risk_type,
        "description": row.description,
        "evidence": row.evidence,
        "impact": row.impact,
        "questions": row.questions,
        "improvement": row.improvement,
        "status": row.status,
        "note": row.note,
        "history": row.history,
        "revision": row.revision,
        "created_by": creator.display_name if creator else "已删除账号",
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def create_manual(project_id, report_id, payload: schema.ManualRiskInput, actor, db):
    report = own(project_id, report_id, actor, db, lock=True)
    prior = db.scalar(
        select(RequirementManualRisk).where(
            RequirementManualRisk.report_id == report_id,
            RequirementManualRisk.request_id == str(payload.request_id),
        )
    )
    if prior:
        same = (
            prior.message_turn_id == payload.message_turn_id
            and prior.function_key == payload.function_key
            and prior.title == payload.title.strip()
            and prior.severity == payload.severity
            and prior.risk_type == payload.risk_type
            and prior.description == payload.description.strip()
            and prior.evidence == [item.model_dump() for item in payload.evidence]
            and prior.impact == payload.impact.strip()
            and prior.questions == [item.strip() for item in payload.questions]
            and prior.improvement == payload.improvement.model_dump()
        )
        if not same:
            raise AppError(409, "risk_manual_request_conflict")
        return manual_view(prior, db)
    function = next(
        (f for f in report.report["functions"] if f["key"] == payload.function_key), None
    )
    if function is None:
        raise AppError(422, "risk_function_not_found")
    turn = db.scalar(
        select(RequirementChatTurn).where(
            RequirementChatTurn.id == payload.message_turn_id,
            RequirementChatTurn.report_id == report_id,
            RequirementChatTurn.status == "COMPLETED",
        )
    )
    if turn is None:
        raise AppError(422, "risk_message_not_found")
    materials = {item["source_id"]: item for item in report.input["materials"]}
    for evidence in payload.evidence:
        material = materials.get(evidence.source_id)
        segment = (
            next(
                (
                    item
                    for item in material["segments"]
                    if item["segment_id"] == evidence.segment_id
                ),
                None,
            )
            if material
            else None
        )
        if (
            segment is None
            or segment["location"] != evidence.location
            or (evidence.excerpt and evidence.excerpt not in segment["text"])
        ):
            raise AppError(422, "risk_manual_evidence_invalid")
    row = RequirementManualRisk(
        report_id=report_id,
        function_key=payload.function_key,
        message_turn_id=payload.message_turn_id,
        request_id=str(payload.request_id),
        title=payload.title.strip(),
        severity=payload.severity,
        risk_type=payload.risk_type,
        description=payload.description.strip(),
        evidence=[item.model_dump() for item in payload.evidence],
        impact=payload.impact.strip(),
        questions=[item.strip() for item in payload.questions],
        improvement=payload.improvement.model_dump(),
        created_by=actor.id,
    )
    db.add(row)
    db.commit()
    logger.info(
        "manual_risk created project=%s report=%s actor=%s", project_id, report_id, actor.id
    )
    return manual_view(row, db)


def handle_manual(project_id, report_id, risk_id, payload: schema.ManualHandlingInput, actor, db):
    own(project_id, report_id, actor, db, lock=True)
    row = db.scalar(
        select(RequirementManualRisk)
        .where(RequirementManualRisk.id == risk_id, RequirementManualRisk.report_id == report_id)
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "risk_item_not_found")
    if row.revision != payload.revision:
        raise AppError(409, "risk_report_changed")
    if row.status != payload.status or row.note != payload.note:
        now = datetime.now(UTC)
        row.history = [
            *row.history,
            {
                "from": row.status,
                "to": payload.status,
                "note": payload.note,
                "actor": actor.display_name,
                "actor_id": actor.id,
                "time": now.isoformat(),
            },
        ]
        row.status, row.note, row.updated_at = payload.status, payload.note, now
        row.revision += 1
        db.commit()
    return manual_view(row, db)


def catalog(
    project_id, actor, db, page=1, source=0, function="", severity="", state="", page_size=10
):
    documents.access(project_id, actor, db)
    # Catalog rows use report results/bindings, never the potentially large input body.
    entries = db.execute(
        select(RequirementRiskReport, UserAccount.display_name)
        .options(defer(RequirementRiskReport.input))
        .outerjoin(UserAccount, UserAccount.id == RequirementRiskReport.created_by)
        .where(
            RequirementRiskReport.project_id == project_id,
            RequirementRiskReport.deleted_at.is_(None),
        )
        .order_by(RequirementRiskReport.id.desc())
    ).all()
    reports = [row for row, _ in entries]
    creators = {row.id: name or "已删除账号" for row, name in entries}
    delete_permissions = requirement_permissions(project_id, reports, actor, db)
    review_by_report = review_warnings_by_report(project_id, db)
    manuals = list(
        db.scalars(
            select(RequirementManualRisk)
            .join(
                RequirementRiskReport, RequirementRiskReport.id == RequirementManualRisk.report_id
            )
            .where(
                RequirementRiskReport.project_id == project_id,
                RequirementRiskReport.deleted_at.is_(None),
            )
            .order_by(RequirementManualRisk.id)
        )
    )
    manual_by_report = {}
    for item in manuals:
        manual_by_report.setdefault(item.report_id, []).append(item)
    rows, functions = [], []
    for report in reports:
        function_map = {item["key"]: item for item in report.report["functions"]}
        functions.extend(
            {
                "id": f"{report.id}:{item['key']}",
                "report_id": report.id,
                "key": item["key"],
                "module": item["module"],
                "name": item["name"],
                "risk_count": len(item["risk_keys"])
                + sum(m.function_key == item["key"] for m in manual_by_report.get(report.id, [])),
            }
            for item in report.report["functions"]
        )
        handling = report.handling
        for risk in report.report["risks"]:
            current = handling.get(risk["key"], {"status": "PENDING", "note": "", "history": []})
            rows.append(
                {
                    "id": f"{report.id}:{risk['key']}",
                    "source_kind": "ANALYSIS",
                    "report_id": report.id,
                    "report_title": report.title,
                    "risk_key": risk["key"],
                    "risk": risk,
                    "review_warnings": [
                        warning
                        for warning in review_by_report.get(report.id, [])
                        if warning["risk_key"] == risk["key"]
                    ],
                    "functions": [function_map[key] for key in risk["function_keys"]],
                    "status": current["status"],
                    "note": current["note"],
                    "history": current["history"],
                    "revision": report.revision,
                    "created_at": report.created_at.isoformat(),
                }
            )
        for item in manual_by_report.get(report.id, []):
            risk = {
                "key": f"M{item.id}",
                "function_keys": [item.function_key],
                "title": item.title,
                "type": item.risk_type,
                "severity": item.severity,
                "description": item.description,
                "evidence": item.evidence,
                "impact": item.impact,
                "questions": item.questions,
                "improvement": item.improvement,
            }
            rows.append(
                {
                    "id": f"M{item.id}",
                    "source_kind": "MANUAL",
                    "manual_id": item.id,
                    "message_turn_id": item.message_turn_id,
                    "report_id": report.id,
                    "report_title": report.title,
                    "risk_key": risk["key"],
                    "risk": risk,
                    "review_warnings": [],
                    "functions": [function_map[item.function_key]],
                    "status": item.status,
                    "note": item.note,
                    "history": item.history,
                    "revision": item.revision,
                    "created_at": item.created_at.isoformat(),
                }
            )
    scoped = [item for item in rows if not source or item["report_id"] == source]
    overview = {
        "reports": len({item["report_id"] for item in scoped}),
        "functions": sum(not source or item["report_id"] == source for item in functions),
        "risks": len(scoped),
        "high": sum(item["risk"]["severity"] == "HIGH" for item in scoped),
        "medium": sum(item["risk"]["severity"] == "MEDIUM" for item in scoped),
        "low": sum(item["risk"]["severity"] == "LOW" for item in scoped),
        "pending": sum(item["status"] in ("PENDING", "NEEDS_INFO") for item in scoped),
    }
    filtered = [
        item
        for item in scoped
        if (
            not function
            or any(f"{item['report_id']}:{f['key']}" == function for f in item["functions"])
        )
        and (not severity or item["risk"]["severity"] == severity)
        and (not state or item["status"] == state)
    ]
    start = (page - 1) * page_size if page_size else 0
    pages = max(1, (len(filtered) + page_size - 1) // page_size) if page_size else 1
    return {
        "overview": overview,
        "reports": [
            {
                "id": item.id,
                "title": item.title,
                "created_at": item.created_at.isoformat(),
                "created_by": creators[item.id],
                "outcome": item.report["outcome"],
                "functions": len(item.report["functions"]),
                "risks": len(item.report["risks"]),
                "review_warning_count": len(review_by_report.get(item.id, [])),
                "can_delete": delete_permissions[item.id],
                "materials": [
                    {
                        "name": binding["name"],
                        "version": (
                            f"v{binding['version']['number']}"
                            if binding.get("version")
                            else binding.get("commit") or "固定快照"
                        ),
                    }
                    for binding in item.bindings
                ],
            }
            for item in reports
        ],
        "functions": functions,
        "total": len(filtered),
        "page": page,
        "pages": pages,
        "items": filtered[start : start + page_size] if page_size else filtered,
    }


def export_markdown(project_id, actor, db, source=0, function="", severity="", state=""):
    rows = catalog(project_id, actor, db, 1, source, function, severity, state, 0)["items"]
    if not rows:
        raise AppError(422, "risk_export_empty")
    lines = ["# 需求风险清单", ""]
    for item in rows:
        risk = item["risk"]
        lines.extend(
            [
                f"## {item['report_title']} / {risk['key']} {risk['title']}",
                "",
                f"来源：{'人工新增' if item['source_kind'] == 'MANUAL' else 'AI分析'}",
                f"功能：{'、'.join(value['name'] for value in item['functions'])}",
                f"等级：{risk['severity']}  状态：{item['status']}",
                "",
                risk["description"],
                "",
                f"影响：{risk['impact']}",
                f"建议：{risk['improvement']['proposal']}",
                f"人工结论：{item['note'] or '尚未填写'}",
                "",
            ]
        )
        if item["review_warnings"]:
            warnings = "、".join(
                f"{warning['path']}（{warning['code']}）" for warning in item["review_warnings"]
            )
            lines.extend((f"待人工核对：{warnings}", ""))
        for evidence in risk["evidence"]:
            proof = evidence["excerpt"] or evidence["observation"]
            lines.append(f"- 依据 {evidence['source_id']} / {evidence['location']}：{proof}")
        lines.append("")
    return "\n".join(lines)
