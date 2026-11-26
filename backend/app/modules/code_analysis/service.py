"""Code analysis records, paired import and independent human handling."""

import copy
import hashlib
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.json_data import json_object as read_json
from app.db.models import (
    CodeAnalysisTask,
    DocumentVersion,
    LocalCodeSource,
    SourceDocument,
    UserAccount,
)
from app.modules.ai import native_terminal
from app.modules.ai.service import (
    analysis_configuration,
    configuration_snapshot,
)
from app.modules.code_analysis import artifacts, contract, report_v3, schemas, sources
from app.modules.documents import service as documents
from app.modules.github import service as github_service
from app.modules.projects import service as projects
from app.modules.projects.record_deletion import require_visible
from app.modules.prototypes import directories

ACTIVE = ("QUEUED", "RUNNING")


def parse(model, data, *, context=None):
    try:
        return model.model_validate(data, context=context)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise AppError(422, "code_contract_invalid") from None


async def read_payload(chunks, model):
    body = bytearray()
    async for chunk in chunks:
        if len(body) + len(chunk) > 4 * sources.FILE_LIMIT:
            raise AppError(413, "code_input_too_large")
        body.extend(chunk)
    try:
        return parse(model, json_object(body.decode("utf-8-sig")))
    except (UnicodeError, RecursionError):
        raise AppError(422, "code_json_invalid") from None


def options(project_id, actor, db):
    documents.access(project_id, actor, db)
    repositories = [
        row
        for row in projects.list_repositories(project_id, actor, db)
        if row["has_personal_authorization"]
    ]
    materials = []
    for row in db.scalars(
        select(SourceDocument)
        .where(SourceDocument.project_id == project_id, SourceDocument.deleted_at.is_(None))
        .order_by(SourceDocument.id)
    ):
        versions = list(
            db.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.project_id == project_id, DocumentVersion.document_id == row.id
                )
                .order_by(DocumentVersion.number.desc())
            )
        )
        materials.append(
            {
                "id": row.id,
                "name": row.name or "未命名资料",
                "purpose": row.purpose,
                "kind": row.kind,
                "url": row.url or "",
                "commit": row.latest_commit or "",
                "files": row.file_manifest or [],
                "versions": [
                    {
                        "id": v.id,
                        "number": v.number,
                        "filename": v.filename,
                        "extension": v.extension,
                    }
                    for v in versions
                ],
            }
        )
    try:
        meta, _ = analysis_configuration(actor, db)
        ai = {
            **configuration_snapshot(meta),
            "preference_version": meta.get("preference_version", 0),
        }
    except AppError as exc:
        ai = {"error_code": exc.detail}
    return {
        "repositories": repositories,
        "connections": github_service.list_connections(actor, db),
        "materials": materials,
        "local_sources": [
            {
                "id": r.id,
                "client_id": r.client_id,
                "name": r.name,
                "directory_name": r.directory_name,
                "kind": r.kind,
                "version": r.version,
            }
            for r in db.scalars(
                select(LocalCodeSource)
                .where(
                    LocalCodeSource.project_id == project_id, LocalCodeSource.owner_id == actor.id
                )
                .order_by(LocalCodeSource.id)
            )
        ],
        "ai": ai,
        "file_limit": sources.FILE_LIMIT,
    }


def github_scope(project_id, repository_id, connection_id, branch, actor, db):
    from app.db.models import ProjectRepository
    from app.integrations import github
    from app.modules.github.service import saved_token

    repo = db.get(ProjectRepository, repository_id)
    if repo is None or repo.project_id != project_id:
        raise AppError(404, "project_repository_not_found")
    selection = {
        "kind": "GITHUB",
        "source_id": repository_id,
        "source_version": repo.version,
        "connection_id": connection_id,
    }
    row, connection = sources.source_authorization(project_id, selection, actor, db)
    github_id, connection_version = row.github_id, connection.version
    token = saved_token(connection)
    db.rollback()
    result = github.code_scope(token, github_id, branch)
    row, connection = sources.source_authorization(project_id, selection, actor, db)
    if connection.version != connection_version:
        raise AppError(409, "github_connection_changed")
    result["files"] = [f for f in result["files"] if contract.safe_path(f["path"])]
    return {**result, "repository_kind": row.kind, "source_version": row.version}


def json_object(value: str):
    return read_json(value, "code_contract_invalid")


def validate_candidate(raw, input_data, *, version=None, normalize=True):
    contract.require(isinstance(raw, dict))
    version = raw.get("contract_version") if version is None else version
    if version == 3:
        output = parse(contract.CandidateV3, raw, context={"normalize_chain_text": normalize})
        return report_v3.validate(input_data, output, normalize=normalize)
    output = parse(contract.Report, raw)
    output, corrections = (
        contract.normalize_code_evidence(input_data, output) if normalize else (output, [])
    )
    return contract.validate_report(input_data, output), corrections


def own(project_id, task_id, actor, db, *, lock=False):
    if actor is None:
        raise AppError(403, "code_access_lost")
    documents.access(project_id, actor, db, lock=lock)
    row = db.scalar(
        select(CodeAnalysisTask)
        .where(CodeAnalysisTask.id == task_id, CodeAnalysisTask.project_id == project_id)
        .execution_options(populate_existing=True)
        .with_for_update()
        if lock
        else select(CodeAnalysisTask)
        .where(CodeAnalysisTask.id == task_id, CodeAnalysisTask.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise AppError(404, "code_analysis_not_found")
    require_visible(row)
    return row


def github_file(project_id, repository_id, connection_id, commit, path, actor, db):
    from app.db.models import ProjectRepository
    from app.integrations import github
    from app.modules.github.service import saved_token

    contract.require(contract.safe_path(path), "code_path_excluded")
    contract.require(
        len(commit) == 40 and all(c in "0123456789abcdef" for c in commit), "code_ref_invalid"
    )
    repo = db.get(ProjectRepository, repository_id)
    if repo is None or repo.project_id != project_id:
        raise AppError(404, "project_repository_not_found")
    selection = {
        "kind": "GITHUB",
        "source_id": repository_id,
        "source_version": repo.version,
        "connection_id": connection_id,
    }
    repo, connection = sources.source_authorization(project_id, selection, actor, db)
    github_id, version, token = repo.github_id, connection.version, saved_token(connection)
    db.rollback()
    scope = github.code_scope(token, github_id, commit)
    file = next((f for f in scope["files"] if f["path"] == path), None)
    if file is None or file["size"] > 2_000_000:
        raise AppError(422, "code_file_unavailable")
    raw = github.prototype_content(token, scope["full_name"], file["sha"])
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeError:
        raise AppError(422, "code_text_required") from None
    contract.require("\x00" not in content, "code_text_required")
    _, connection = sources.source_authorization(project_id, selection, actor, db)
    if connection.version != version:
        raise AppError(409, "github_connection_changed")
    return {"path": path, "content": content, "commit": scope["commit"]}


def view(row, actor, *, detail=False):
    require_visible(row)
    metadata = row.metadata_snapshot or {}
    report = row.report or {}
    findings = report.get("findings", [])
    result = {
        "id": row.id,
        "project_id": row.project_id,
        "actor_id": row.actor_id,
        "title": row.title,
        "focus": row.focus,
        "targets": row.targets,
        "status": row.status,
        "error_code": row.error_code,
        "retry_of": row.retry_of,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "revision": row.revision,
        "origin": metadata.get("origin", "LEGACY"),
        "ai": native_terminal.public_snapshot(row.ai_config),
        "terminal_available": native_terminal.available(row.ai_config, row.actor_id, actor.id),
        "can_cancel": row.actor_id == actor.id and row.status in ACTIVE,
        "can_retry": metadata.get("origin") == "AI" and row.status in ("FAILED", "CANCELLED"),
        "findings_count": len(findings),
        "outcome": report.get("outcome"),
        "contract_version": report.get("contract_version"),
        "skill": {k: v for k, v in metadata.get("skill", {}).items() if k != "instructions"},
    }
    if detail:
        candidate_available = (
            metadata.get("origin") == "AI"
            and row.status not in ACTIVE
            and artifacts.candidate_path(row.id).is_file()
        )
        result.update(
            input=row.input_snapshot,
            report=report,
            handling=row.handling,
            bindings=metadata.get("bindings", []),
            candidate_available=candidate_available,
            can_revalidate=(
                row.actor_id == actor.id
                and row.status == "FAILED"
                and row.error_code in {"code_evidence_invalid", "code_contract_invalid"}
                and candidate_available
            ),
            evidence_corrections=metadata.get("evidence_corrections", []),
        )
    return result


def listing(project_id, actor, db, page=1):
    documents.access(project_id, actor, db)
    # Polling the sidebar must not load every record's source text or complete report.
    rows = (
        db.execute(
            select(
                CodeAnalysisTask.id,
                CodeAnalysisTask.project_id,
                CodeAnalysisTask.actor_id,
                CodeAnalysisTask.title,
                CodeAnalysisTask.focus,
                CodeAnalysisTask.targets,
                CodeAnalysisTask.status,
                CodeAnalysisTask.error_code,
                CodeAnalysisTask.retry_of,
                CodeAnalysisTask.created_at,
                CodeAnalysisTask.updated_at,
                CodeAnalysisTask.revision,
                CodeAnalysisTask.ai_config.label("ai"),
                CodeAnalysisTask.metadata_snapshot["origin"].astext.label("origin"),
                CodeAnalysisTask.report["outcome"].astext.label("outcome"),
                CodeAnalysisTask.report["contract_version"].as_integer().label("contract_version"),
                func.coalesce(
                    func.jsonb_array_length(CodeAnalysisTask.report["findings"]), 0
                ).label("findings_count"),
            )
            .where(CodeAnalysisTask.project_id == project_id, CodeAnalysisTask.deleted_at.is_(None))
            .order_by(CodeAnalysisTask.id.desc())
            .limit(51)
            .offset((page - 1) * 50)
        )
        .mappings()
        .all()
    )
    items = []
    for row in rows[:50]:
        item = dict(row)
        item["terminal_available"] = native_terminal.available(
            item["ai"], item["actor_id"], actor.id
        )
        item["ai"] = native_terminal.public_snapshot(item["ai"])
        item["origin"] = item["origin"] or "LEGACY"
        item["can_cancel"] = item["actor_id"] == actor.id and item["status"] in ACTIVE
        item["can_retry"] = item["origin"] == "AI" and item["status"] in ("FAILED", "CANCELLED")
        for key in ("created_at", "updated_at"):
            item[key] = item[key].isoformat()
        items.append(item)
    return {"items": items, "has_more": len(rows) > 50}


def detail(project_id, task_id, actor, db):
    return view(own(project_id, task_id, actor, db), actor, detail=True)


def enqueue(project_id, payload, actor, db):
    documents.access(project_id, actor, db, lock=True)
    raw = payload.model_dump(mode="json")
    fingerprint = sources.digest(raw)
    previous = db.scalar(
        select(CodeAnalysisTask).where(
            CodeAnalysisTask.project_id == project_id,
            CodeAnalysisTask.actor_id == actor.id,
            CodeAnalysisTask.request_id == str(payload.request_id),
        )
    )
    if previous:
        if previous.metadata_snapshot.get("request_hash") != fingerprint:
            raise AppError(409, "code_analysis_request_conflict")
        return view(previous, actor, detail=True)
    if not payload.title.strip():
        raise AppError(422, "code_title_required")
    sources.validate_selections(project_id, raw, actor, db)
    meta, _ = analysis_configuration(
        actor,
        db,
        payload.ai_version,
        mode=payload.ai_call_mode or "RESPONSES_API",
        preference_version=payload.ai_preference_version,
    )
    row = CodeAnalysisTask(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        title=payload.title.strip(),
        focus=payload.focus,
        targets=payload.targets,
        input_snapshot={},
        ai_config=native_terminal.bind_snapshot(configuration_snapshot(meta)),
        metadata_snapshot={
            "origin": "AI",
            "selections": raw,
            "request_hash": fingerprint,
            "skill": sources.skill_snapshot(),
        },
        handling={},
    )
    db.add(row)
    db.commit()
    return view(row, actor, detail=True)


def cancel(project_id, task_id, actor, db):
    row = own(project_id, task_id, actor, db, lock=True)
    if row.actor_id != actor.id:
        raise AppError(403, "code_analysis_cancel_owner_only")
    if row.status in ACTIVE:
        row.status, row.updated_at = "CANCELLED", datetime.now(UTC)
        db.commit()
    return view(row, actor, detail=True)


def retry(project_id, task_id, payload, actor, db):
    previous = own(project_id, task_id, actor, db, lock=True)
    prior = db.scalar(
        select(CodeAnalysisTask).where(
            CodeAnalysisTask.project_id == project_id,
            CodeAnalysisTask.actor_id == actor.id,
            CodeAnalysisTask.request_id == str(payload.request_id),
        )
    )
    if prior:
        if prior.retry_of != task_id:
            raise AppError(409, "code_analysis_request_conflict")
        return view(prior, actor, detail=True)
    if (
        previous.status not in ("FAILED", "CANCELLED")
        or previous.metadata_snapshot.get("origin") != "AI"
    ):
        raise AppError(422, "code_analysis_retry_invalid")
    meta, _ = analysis_configuration(
        actor, db, mode=previous.ai_config.get("call_mode", "RESPONSES_API")
    )
    metadata = copy.deepcopy(previous.metadata_snapshot)
    sources.recheck(project_id, metadata, actor, db, shared_snapshot=True)
    snapshot = copy.deepcopy(previous.input_snapshot)
    if not snapshot:
        # A retry of preparation still uses the new caller's own authorized code connections.
        from app.db.models import GitHubConnection, GitHubRepository, ProjectRepository

        for selection in metadata["selections"]["sources"]:
            if selection["kind"] == "GITHUB":
                repo = db.get(ProjectRepository, selection["source_id"])
                connection = db.scalar(
                    select(GitHubConnection)
                    .join(GitHubRepository, GitHubRepository.connection_id == GitHubConnection.id)
                    .where(
                        GitHubConnection.owner_id == actor.id,
                        GitHubRepository.github_id == repo.github_id,
                    )
                    .order_by(GitHubConnection.id)
                )
                selection["connection_id"] = connection.id
    else:
        snapshot["request_id"] = str(payload.request_id)
    metadata["shared_snapshot"] = True
    metadata["request_hash"] = sources.digest(
        {"retry_of": task_id, "request_id": str(payload.request_id)}
    )
    row = CodeAnalysisTask(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        retry_of=task_id,
        title=previous.title,
        focus=previous.focus,
        targets=previous.targets,
        input_snapshot=snapshot,
        ai_config=native_terminal.bind_snapshot(configuration_snapshot(meta)),
        metadata_snapshot=metadata,
        handling={},
    )
    db.add(row)
    db.commit()
    return view(row, actor, detail=True)


def revalidate_candidate(project_id, task_id, actor, db):
    row = own(project_id, task_id, actor, db, lock=True)
    if row.actor_id != actor.id:
        raise AppError(403, "code_analysis_revalidate_owner_only")
    metadata = row.metadata_snapshot or {}
    if row.status == "COMPLETED" and metadata.get("revalidation"):
        return view(row, actor, detail=True)
    if (
        row.status != "FAILED"
        or row.error_code not in {"code_evidence_invalid", "code_contract_invalid"}
        or metadata.get("origin") != "AI"
    ):
        raise AppError(422, "code_revalidation_invalid")
    try:
        raw = artifacts.candidate_path(row.id).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AppError(404, "code_candidate_not_found") from None
    except (OSError, UnicodeError):
        raise AppError(503, "code_candidate_storage_unavailable") from None
    input_data = parse(contract.AnalysisInput, row.input_snapshot)
    output, corrections = validate_candidate(
        json_object(raw), input_data, version=metadata.get("skill", {}).get("contract_version", 2)
    )
    sources.recheck(
        project_id, metadata, actor, db, shared_snapshot=metadata.get("shared_snapshot", False)
    )
    analysis_configuration(actor, db, row.ai_config)
    now = datetime.now(UTC)
    previous_error = row.error_code
    row.report = output
    row.status, row.error_code, row.updated_at = "COMPLETED", "", now
    row.revision += 1
    row.metadata_snapshot = {
        **metadata,
        "evidence_corrections": corrections,
        "revalidation": {
            "at": now.isoformat(),
            "actor_id": actor.id,
            "previous_error": previous_error,
        },
    }
    db.commit()
    return view(row, actor, detail=True)


async def import_report(project_id, chunks, actor, db):
    documents.access(project_id, actor, db)
    actor_id = actor.id
    db.rollback()
    payload = await read_payload(chunks, schemas.ImportRequest)
    for name, content in (
        (payload.input_filename, payload.input_json),
        (payload.report_filename, payload.report_json),
    ):
        if (
            not name.lower().endswith(".json")
            or any(c in name for c in "/\\\x00")
            or len(content.encode()) > sources.FILE_LIMIT
        ):
            raise AppError(422, "code_import_file_invalid")
    input_data = parse(contract.AnalysisInput, json_object(payload.input_json.lstrip("\ufeff")))
    raw = json_object(payload.report_json.lstrip("\ufeff"))
    if isinstance(raw, dict) and raw.get("contract_version") == 3:
        raw = {
            key: value for key, value in raw.items() if key not in ("outcome", "platform_coverage")
        }
    output, _ = validate_candidate(raw, input_data, normalize=False)
    actor = db.get(UserAccount, actor_id, populate_existing=True)
    documents.access(project_id, actor, db, lock=True)
    mapping = contract.index([b.model_dump() for b in payload.bindings], "source_id")
    contract.require(
        set(mapping) == {m.source_id for m in input_data.materials},
        "code_material_bindings_required",
    )
    bindings = []
    for material in input_data.materials:
        binding = mapping[material.source_id]
        document = db.get(SourceDocument, binding["document_id"])
        if document is None or document.project_id != project_id or document.deleted_at is not None:
            raise AppError(422, "code_material_unavailable")
        if material.origin in ("REQUIREMENT", "PROTOTYPE") and material.origin != document.purpose:
            raise AppError(422, "code_material_binding_mismatch")
        if document.kind == "FILE":
            path, version = documents.stored_version(project_id, binding["version_id"], actor, db)
            if version.document_id != document.id:
                raise AppError(422, "code_material_binding_mismatch")
            for segment in material.segments:
                if segment.image_ref and (
                    segment.image_ref != material.source_id
                    or hashlib.sha256(path.read_bytes()).hexdigest() != material.snapshot_ref
                    or version.extension not in {"png", "jpg", "jpeg", "webp", "pdf"}
                ):
                    raise AppError(422, "code_attachment_mismatch")
        elif document.kind == "DIRECTORY":
            version, paths = directories.bind_material(
                project_id,
                document.id,
                binding["version_id"],
                [s.model_dump() for s in material.segments],
                material.source_id,
                actor,
                db,
            )
            contract.require(
                version.sha256 == material.snapshot_ref, "code_material_binding_mismatch"
            )
            binding["paths"] = paths
        elif any(s.image_ref for s in material.segments):
            raise AppError(422, "code_attachment_mismatch")
        bindings.append({**binding, "name": document.name, "kind": document.kind})
    input_dict, report_dict = input_data.model_dump(), output
    fingerprint = sources.digest({"input": input_dict, "report": report_dict})
    prior = db.scalar(
        select(CodeAnalysisTask).where(
            CodeAnalysisTask.project_id == project_id,
            CodeAnalysisTask.metadata_snapshot["import_hash"].astext == fingerprint,
        )
    )
    if prior:
        return {**view(prior, actor, detail=True), "duplicate": True}
    row = CodeAnalysisTask(
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(uuid5(NAMESPACE_URL, fingerprint)),
        title=payload.title.strip(),
        focus=input_data.focus,
        targets=input_data.targets,
        input_snapshot=input_dict,
        report=report_dict,
        status="COMPLETED",
        ai_config={},
        metadata_snapshot={
            "origin": "IMPORT",
            "import_hash": fingerprint,
            "bindings": bindings,
            "input_filename": payload.input_filename,
            "report_filename": payload.report_filename,
            "provenance": "用户导入的固定快照；引用校验不代表已与真实仓库自动比对",
        },
        handling={},
    )
    if not row.title:
        raise AppError(422, "code_title_required")
    db.add(row)
    db.commit()
    return {**view(row, actor, detail=True), "duplicate": False}


def handle_finding(project_id, task_id, payload, actor, db):
    row = own(project_id, task_id, actor, db, lock=True)
    if row.revision != payload.revision:
        raise AppError(409, "code_handling_changed")
    if (
        row.status != "COMPLETED"
        or row.report.get("contract_version") not in (2, 3)
        or payload.finding_key not in {f["key"] for f in row.report.get("findings", [])}
    ):
        raise AppError(422, "code_finding_unavailable")
    if payload.status != "PENDING" and not payload.note.strip():
        raise AppError(422, "code_handling_note_required")
    handling = copy.deepcopy(row.handling)
    previous = handling.get(payload.finding_key, {})
    entry = {
        "status": payload.status,
        "note": payload.note.strip(),
        "actor_id": actor.id,
        "actor_name": actor.display_name,
        "at": datetime.now(UTC).isoformat(),
    }
    handling[payload.finding_key] = {
        **entry,
        "history": [
            *previous.get("history", []),
            {**entry, "previous_status": previous.get("status", "PENDING")},
        ],
    }
    row.handling, row.revision, row.updated_at = handling, row.revision + 1, datetime.now(UTC)
    db.commit()
    return view(row, actor, detail=True)
