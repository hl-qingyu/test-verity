"""Authorized fixed inputs for code analysis. Network waits never retain a DB transaction."""

import hashlib
import json
import re

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import (
    DocumentVersion,
    GitHubConnection,
    GitHubRepository,
    LocalCodeSource,
    ProjectRepository,
    SourceDocument,
)
from app.integrations import github
from app.modules.code_analysis import contract
from app.modules.documents import service as documents
from app.modules.github.service import own_connection, saved_token
from app.modules.prototypes import directories
from app.modules.prototypes import service as prototypes
from app.modules.requirements import analysis_materials
from app.modules.skills import files as skill_files
from app.security.source_content import contains_private_key

FILE_LIMIT = 16 * 1024 * 1024


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def skill_snapshot():
    return skill_files.snapshot("code-review")


def source_authorization(project_id, selection, actor, db, *, shared_snapshot=False):
    documents.access(project_id, actor, db)
    if selection["kind"] == "LOCAL":
        row = db.get(LocalCodeSource, selection["source_id"], populate_existing=True)
        if (
            row is None
            or row.project_id != project_id
            or not shared_snapshot
            and row.owner_id != actor.id
        ):
            raise AppError(403, "code_source_unavailable")
        if row.version != selection["source_version"]:
            raise AppError(409, "code_source_changed")
        if row.kind == "PROTOTYPE":
            raise AppError(422, "code_source_type_invalid")
        return row, None
    row = db.get(ProjectRepository, selection["source_id"], populate_existing=True)
    if row is None or row.project_id != project_id:
        raise AppError(404, "project_repository_not_found")
    if row.version != selection["source_version"]:
        raise AppError(409, "code_source_changed")
    connection_id = selection.get("connection_id")
    if shared_snapshot:
        connection = db.scalar(
            select(GitHubConnection)
            .join(GitHubRepository, GitHubRepository.connection_id == GitHubConnection.id)
            .where(
                GitHubConnection.owner_id == actor.id, GitHubRepository.github_id == row.github_id
            )
            .order_by(GitHubConnection.id)
        )
        if connection is None:
            raise AppError(403, "github_repository_not_allowed")
    else:
        if not connection_id:
            raise AppError(422, "github_connection_required")
        connection = own_connection(db, actor, connection_id)
    if db.get(GitHubRepository, (connection.id, row.github_id), populate_existing=True) is None:
        raise AppError(403, "github_repository_not_allowed")
    if row.kind == "PROTOTYPE":
        raise AppError(422, "code_source_type_invalid")
    return row, connection


def material_authorization(project_id, selection, actor, db):
    documents.access(project_id, actor, db)
    row = db.get(SourceDocument, selection["document_id"], populate_existing=True)
    if row is None or row.project_id != project_id or row.deleted_at is not None:
        raise AppError(422, "code_material_unavailable")
    if row.kind == "FILE":
        version = db.get(DocumentVersion, selection.get("version_id"))
        if version is None or version.project_id != project_id or version.document_id != row.id:
            raise AppError(422, "code_material_version_required")
        if selection.get("paths") or selection.get("snapshot") or selection.get("url"):
            raise AppError(422, "code_material_unavailable")
    elif row.kind == "DIRECTORY":
        directories.checked(
            project_id, row.id, selection.get("version_id"), selection.get("paths") or [], actor, db
        )
        if selection.get("snapshot") or selection.get("url") or selection.get("commit"):
            raise AppError(422, "code_material_unavailable")
    elif row.kind == "GITHUB":
        if selection.get("snapshot") or selection.get("url"):
            raise AppError(422, "code_material_unavailable")
        if not selection.get("commit") or row.latest_commit != selection["commit"]:
            raise AppError(409, "code_material_changed")
        manifest = {f["path"]: f for f in row.file_manifest or []}
        if not selection.get("paths") or any(p not in manifest for p in selection["paths"]):
            raise AppError(422, "code_material_files_required")
        contract.unique(selection["paths"])
        repo = db.get(ProjectRepository, row.repository_id)
        grant = (
            db.scalar(
                select(GitHubRepository.connection_id)
                .join(GitHubConnection, GitHubConnection.id == GitHubRepository.connection_id)
                .where(
                    GitHubConnection.owner_id == actor.id,
                    GitHubRepository.github_id == repo.github_id,
                )
            )
            if repo and repo.project_id == project_id
            else None
        )
        if grant is None:
            raise AppError(403, "github_repository_not_allowed")
    elif row.kind == "LINK" and row.purpose == "PROTOTYPE":
        paths = selection.get("paths", [])
        if (
            selection.get("version_id") is not None
            or selection.get("commit")
            or not paths
            or not selection.get("snapshot")
            or any(
                not isinstance(p, str)
                or not re.fullmatch(r"(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.html", p)
                for p in paths
            )
        ):
            raise AppError(422, "code_material_files_required")
        if selection.get("url") != row.url:
            raise AppError(409, "prototype_link_changed")
        contract.unique(paths)
    else:
        raise AppError(422, "code_material_unreadable")
    return row


def validate_selections(project_id, payload, actor, db, *, shared_snapshot=False):
    selections = payload["sources"]
    contract.unique(payload["targets"])
    contract.require(len({s["kind"] for s in selections}) == 1)
    contract.unique([(s["kind"], s["source_id"]) for s in selections])
    roles = set()
    for selection in selections:
        row, _ = source_authorization(
            project_id, selection, actor, db, shared_snapshot=shared_snapshot
        )
        roles.add(row.kind)
        contract.unique([f["path"] for f in selection["files"]])
        for file in selection["files"]:
            contract.require(contract.safe_path(file["path"]), "code_path_excluded")
            if selection["kind"] == "LOCAL":
                content = file.get("content")
                contract.require(
                    isinstance(content, str) and bool(content.strip()) and "\x00" not in content,
                    "code_text_required",
                )
                contract.require(
                    hashlib.sha256(content.encode()).hexdigest() == file.get("sha256"),
                    "code_content_changed",
                )
            else:
                contract.require(file.get("content") is None and file.get("sha256") is None)
                contract.require(
                    len(selection["commit"]) == 40
                    and all(c in "0123456789abcdef" for c in selection["commit"]),
                    "code_ref_invalid",
                )
    if "FRONTEND_BACKEND_MISMATCH" in payload["targets"]:
        contract.require(
            "BACKEND" in roles and bool(roles & {"WEB", "FLUTTER"}), "code_both_sides_required"
        )
    contract.unique([s["document_id"] for s in payload["materials"]])
    for selection in payload["materials"]:
        material_authorization(project_id, selection, actor, db)
    if payload["targets"] == ["REQUIREMENT_DEVIATION"] and not payload["materials"]:
        raise AppError(422, "code_material_required")


def prepare(project_id, request_id, payload, actor, db, *, shared_snapshot=False, input_limit=None):
    validate_selections(project_id, payload, actor, db, shared_snapshot=shared_snapshot)
    result = {
        "contract_version": 2,
        "analysis_type": "CODE_REVIEW",
        "request_id": request_id,
        "source_mode": payload["sources"][0]["kind"],
        "targets": payload["targets"],
        "focus": payload["focus"],
        "sources": [],
        "materials": [],
        "input_limitations": [],
    }
    binaries, bindings = [], []
    for number, selection in enumerate(payload["sources"], 1):
        row, connection = source_authorization(
            project_id, selection, actor, db, shared_snapshot=shared_snapshot
        )
        kind, name = row.kind, row.name if selection["kind"] == "LOCAL" else row.full_name
        texts = []
        if connection:
            connection_version, token, github_id = (
                connection.version,
                saved_token(connection),
                row.github_id,
            )
            db.rollback()
            scope = github.code_scope(token, github_id, selection["commit"])
            entries = {f["path"]: f for f in scope["files"]}
            for file in selection["files"]:
                entry = entries.get(file["path"])
                if entry is None or entry["size"] > 2_000_000:
                    raise AppError(422, "code_file_unavailable")
                raw = github.prototype_content(token, scope["full_name"], entry["sha"])
                try:
                    content = raw.decode("utf-8-sig")
                except UnicodeError:
                    raise AppError(422, "code_text_required") from None
                texts.append((file["path"], content))
            _, current = source_authorization(
                project_id, selection, actor, db, shared_snapshot=shared_snapshot
            )
            if current.version != connection_version:
                raise AppError(409, "github_connection_changed")
            snapshot = selection["commit"]
        else:
            texts = [(file["path"], file["content"]) for file in selection["files"]]
            snapshot = "local:sha256:" + digest(texts)
        files = []
        for i, (path, content) in enumerate(texts, 1):
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            if not content.strip() or "\x00" in content:
                raise AppError(422, "code_text_required")
            contract.require(not contains_private_key(content), "code_private_key_content")
            files.append(
                {
                    "file_id": f"F{i}",
                    "path": path,
                    "read_state": "READABLE",
                    "read_note": "",
                    "segments": [{"segment_id": "full", "start_line": 1, "text": content}],
                }
            )
        result["sources"].append(
            {
                "source_id": f"C{number}",
                "source_kind": selection["kind"],
                "repository_kind": kind,
                "name": name,
                "snapshot_ref": snapshot,
                "commit": selection["commit"] if selection["kind"] == "GITHUB" else "",
                "files": files,
            }
        )
        if (
            input_limit is not None
            and len(json.dumps(result, ensure_ascii=False).encode()) > input_limit
        ):
            raise AppError(413, "code_input_too_large")
    for number, selection in enumerate(payload["materials"], 1):
        row = material_authorization(project_id, selection, actor, db)
        sid, name, origin = f"M{number}", row.name, row.purpose
        if row.kind == "FILE":
            path, version = documents.stored_version(project_id, selection["version_id"], actor, db)
            name = version.filename
            material = analysis_materials.file_material(
                path, version.extension, sid, version.filename
            )
            material.pop("kind", None)
            material.pop("role", None)
            if version.extension in {"png", "jpg", "jpeg", "webp", "pdf"}:
                binaries.append((path, version.extension, sid, version.filename))
        elif row.kind == "DIRECTORY":
            material, attached = directories.material(
                project_id, row.id, selection["version_id"], selection["paths"], sid, actor, db
            )
            material.pop("kind", None)
            binaries.extend(attached)
        elif row.kind == "LINK":
            captured = prototypes.link_pages(
                project_id, row.id, selection["paths"], selection["snapshot"], actor, db
            )
            material = {
                "source_id": sid,
                "snapshot_ref": captured["snapshot_ref"],
                "read_state": "PARTIAL",
                "read_note": (
                    "已固定页面HTML、原型说明及批注引用Markdown全文；不执行脚本或读取其他资源"
                ),
                "segments": [
                    {
                        "segment_id": f"p{i}",
                        "location": item["location"],
                        "text": item["text"],
                        "image_ref": "",
                    }
                    for i, item in enumerate(captured["segments"], 1)
                ],
            }
            material_authorization(project_id, selection, actor, db)
        else:
            repo = db.get(ProjectRepository, row.repository_id)
            connection = (
                db.scalar(
                    select(GitHubConnection)
                    .join(GitHubRepository, GitHubRepository.connection_id == GitHubConnection.id)
                    .where(
                        GitHubConnection.owner_id == actor.id,
                        GitHubRepository.github_id == repo.github_id,
                    )
                    .order_by(GitHubConnection.id)
                )
                if repo and repo.project_id == project_id
                else None
            )
            if connection is None:
                raise AppError(403, "github_repository_not_allowed")
            token, full_name = saved_token(connection), repo.full_name
            manifest = {f["path"]: f for f in row.file_manifest}
            db.rollback()
            material = {
                "source_id": sid,
                "snapshot_ref": selection["commit"],
                "read_state": "READABLE",
                "read_note": "",
                "segments": [],
            }
            for i, name_path in enumerate(selection["paths"], 1):
                raw = github.prototype_content(token, full_name, manifest[name_path]["sha"])
                try:
                    content = raw.decode("utf-8-sig")
                except UnicodeError:
                    raise AppError(422, "code_material_unreadable") from None
                for segment in analysis_materials.text_segments(content, name_path):
                    segment["segment_id"] = f"f{i}-" + segment["segment_id"]
                    material["segments"].append(segment)
            material_authorization(project_id, selection, actor, db)
        material.update(name=name, origin=origin)
        if not material["segments"]:
            material.update(read_state="UNREADABLE", read_note="未取得可分析内容")
        result["materials"].append(material)
        bindings.append({"source_id": sid, **selection})
    if input_limit is not None:
        size = len(json.dumps(result, ensure_ascii=False).encode()) + sum(
            p.stat().st_size for p, _, _, _ in binaries
        )
        if size > input_limit:
            raise AppError(413, "code_input_too_large")
    parsed = contract.AnalysisInput.model_validate(result)
    contract.validate_input(parsed)
    db.rollback()
    return result, bindings, binaries


def recheck(project_id, metadata, actor, db, *, shared_snapshot=False):
    documents.access(project_id, actor, db)
    if metadata.get("origin") == "AI":
        validate_selections(
            project_id, metadata["selections"], actor, db, shared_snapshot=shared_snapshot
        )
    else:
        for binding in metadata.get("bindings", []):
            row = db.get(SourceDocument, binding["document_id"], populate_existing=True)
            if row is None or row.project_id != project_id or row.deleted_at is not None:
                raise AppError(422, "code_material_unavailable")


def frozen_binaries(project_id, metadata, actor, db):
    result = []
    for binding in metadata.get("bindings", []):
        if binding.get("version_id"):
            path, version = documents.stored_version(project_id, binding["version_id"], actor, db)
            if version.extension == "directory":
                _, attached = directories.material(
                    project_id,
                    binding["document_id"],
                    version.id,
                    binding["paths"],
                    binding["source_id"],
                    actor,
                    db,
                )
                result.extend(attached)
            if version.extension in {"png", "jpg", "jpeg", "webp", "pdf"}:
                result.append((path, version.extension, binding["source_id"], version.filename))
    return result
