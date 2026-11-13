import hashlib
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    DocumentGroup,
    DocumentLibrary,
    DocumentLinkBinding,
    DocumentVersion,
    RequirementAnalysis,
    RequirementRiskReport,
    RequirementRule,
    RequirementSource,
    SourceDocument,
    UserAccount,
)
from app.modules.documents import files
from app.modules.documents.markdown_links import file_links, link_hash, link_key
from app.modules.documents.schemas import (
    DeleteInput,
    GroupInput,
    LinkBindingInput,
    MoveInput,
    ReorderInput,
    UploadInput,
)
from app.modules.projects.service import access_project


def access(project_id: int, actor: UserAccount, db: Session, lock: bool = False) -> None:
    current = db.get(UserAccount, actor.id, populate_existing=True)
    if current is None or current.status != "ACTIVE":
        raise AppError(401, "not_authenticated")
    access_project(project_id, current, db, lock=lock)


def library_lock(
    project_id: int, revision: int, actor: UserAccount, db: Session
) -> DocumentLibrary:
    access(project_id, actor, db, lock=True)
    db.execute(insert(DocumentLibrary).values(project_id=project_id).on_conflict_do_nothing())
    library = db.get(DocumentLibrary, project_id, with_for_update=True, populate_existing=True)
    if library.revision != revision:
        raise AppError(409, "documents_changed")
    return library


def group_exists(
    project_id: int, group_id: int | None, db: Session, purpose: str = "REQUIREMENT"
) -> None:
    if (
        group_id is not None
        and db.scalar(
            select(DocumentGroup.id).where(
                DocumentGroup.project_id == project_id,
                True if purpose is None else DocumentGroup.purpose == purpose,
                DocumentGroup.id == group_id,
            )
        )
        is None
    ):
        raise AppError(404, "document_group_not_found")


def version_view(row: DocumentVersion, db: Session) -> dict:
    creator = db.get(UserAccount, row.created_by)
    return {
        "id": row.id,
        "document_id": row.document_id,
        "deleted": db.get(SourceDocument, row.document_id).deleted_at is not None,
        "number": row.number,
        "filename": row.filename,
        "extension": row.extension,
        "size": row.size,
        "sha256": row.sha256,
        "created_at": row.created_at.isoformat(),
        "created_by": creator.display_name if creator else "已删除账号",
    }


def list_documents(
    project_id: int, actor: UserAccount, db: Session, purpose: str | None = "REQUIREMENT"
) -> dict:
    access(project_id, actor, db)
    # One shared project lock keeps revision and list contents consistent with all writers.
    access_project(project_id, actor, db, lock=True)
    library = db.get(DocumentLibrary, project_id, populate_existing=True)
    groups = db.scalars(
        select(DocumentGroup)
        .where(
            DocumentGroup.project_id == project_id,
            True if purpose is None else DocumentGroup.purpose == purpose,
        )
        .order_by(DocumentGroup.id)
    )
    rows = db.execute(
        select(SourceDocument, DocumentVersion)
        .join(
            DocumentVersion,
            (DocumentVersion.document_id == SourceDocument.id)
            & (DocumentVersion.number == SourceDocument.current_version),
        )
        .where(
            SourceDocument.project_id == project_id,
            SourceDocument.deleted_at.is_(None),
            True if purpose is None else SourceDocument.purpose == purpose,
        )
        .order_by(SourceDocument.position, SourceDocument.id)
    )
    return {
        "revision": library.revision if library else 0,
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "documents": [
            {
                "id": d.id,
                "group_id": d.group_id,
                "position": d.position,
                "current": version_view(v, db),
            }
            for d, v in rows
        ],
    }


def create_group(
    project_id: int,
    payload: GroupInput,
    actor: UserAccount,
    db: Session,
    purpose: str = "REQUIREMENT",
) -> dict:
    library = library_lock(project_id, payload.revision, actor, db)
    if db.scalar(
        select(DocumentGroup.id).where(
            DocumentGroup.project_id == project_id,
            True if purpose is None else DocumentGroup.purpose == purpose,
            DocumentGroup.name == payload.name,
        )
    ):
        raise AppError(409, "document_group_duplicate")
    db.add(DocumentGroup(project_id=project_id, name=payload.name, purpose=purpose))
    library.revision += 1
    db.commit()
    return list_documents(project_id, actor, db, purpose)


def last_position(
    project_id: int, group_id: int | None, db: Session, purpose: str = "REQUIREMENT"
) -> int:
    value = db.scalar(
        select(func.max(SourceDocument.position)).where(
            SourceDocument.project_id == project_id,
            SourceDocument.deleted_at.is_(None),
            True if purpose is None else SourceDocument.purpose == purpose,
            SourceDocument.group_id == group_id,
        )
    )
    return (value if value is not None else -1) + 1


def rename_group(
    project_id: int,
    group_id: int,
    payload: GroupInput,
    actor: UserAccount,
    db: Session,
    purpose: str = "REQUIREMENT",
) -> dict:
    library = library_lock(project_id, payload.revision, actor, db)
    group = db.scalar(
        select(DocumentGroup).where(
            DocumentGroup.project_id == project_id,
            True if purpose is None else DocumentGroup.purpose == purpose,
            DocumentGroup.id == group_id,
        )
    )
    if group is None:
        raise AppError(404, "document_group_not_found")
    if db.scalar(
        select(DocumentGroup.id).where(
            DocumentGroup.project_id == project_id,
            True if purpose is None else DocumentGroup.purpose == purpose,
            DocumentGroup.id != group_id,
            DocumentGroup.name == payload.name,
        )
    ):
        raise AppError(409, "document_group_duplicate")
    group.name = payload.name
    library.revision += 1
    db.commit()
    return list_documents(project_id, actor, db, purpose)


def move(
    project_id: int,
    payload: MoveInput,
    actor: UserAccount,
    db: Session,
    purpose: str = "REQUIREMENT",
) -> dict:
    library = library_lock(project_id, payload.revision, actor, db)
    group_exists(project_id, payload.group_id, db, purpose)
    docs = list(
        db.scalars(
            select(SourceDocument)
            .where(
                SourceDocument.project_id == project_id,
                SourceDocument.deleted_at.is_(None),
                True if purpose is None else SourceDocument.purpose == purpose,
                SourceDocument.id.in_(payload.document_ids),
            )
            .order_by(SourceDocument.position, SourceDocument.id)
        )
    )
    if len(docs) != len(set(payload.document_ids)):
        raise AppError(404, "document_not_found")
    position = last_position(project_id, payload.group_id, db, purpose)
    for doc in docs:
        if doc.group_id != payload.group_id:
            doc.group_id, doc.position = payload.group_id, position
            position += 1
    library.revision += 1
    db.commit()
    return list_documents(project_id, actor, db, purpose)


def reorder(
    project_id: int,
    payload: ReorderInput,
    actor: UserAccount,
    db: Session,
    purpose: str = "REQUIREMENT",
) -> dict:
    library = library_lock(project_id, payload.revision, actor, db)
    doc = db.scalar(
        select(SourceDocument).where(
            SourceDocument.project_id == project_id,
            SourceDocument.deleted_at.is_(None),
            True if purpose is None else SourceDocument.purpose == purpose,
            SourceDocument.id == payload.document_id,
        )
    )
    if doc is None:
        raise AppError(404, "document_not_found")
    docs = list(
        db.scalars(
            select(SourceDocument)
            .where(
                SourceDocument.project_id == project_id,
                SourceDocument.deleted_at.is_(None),
                True if purpose is None else SourceDocument.purpose == purpose,
                SourceDocument.group_id == doc.group_id,
            )
            .order_by(SourceDocument.position, SourceDocument.id)
        )
    )
    index = docs.index(doc)
    target = index + payload.direction
    if payload.direction == 0 or not 0 <= target < len(docs):
        raise AppError(422, "document_order_boundary")
    docs[index], docs[target] = docs[target], docs[index]
    for position, row in enumerate(docs):
        row.position = position
    library.revision += 1
    db.commit()
    return list_documents(project_id, actor, db, purpose)


async def upload(
    project_id: int,
    payload: UploadInput,
    chunks: AsyncIterator[bytes],
    actor: UserAccount,
    db: Session,
    purpose: str = "REQUIREMENT",
    name: str = "",
    description: str = "",
) -> dict:
    access(project_id, actor, db)
    actor_id = actor.id
    db.rollback()  # Do not keep an idle transaction during a browser upload.
    extension = payload.filename.rsplit(".", 1)[-1].lower()
    if (
        extension not in files.MEDIA
        or (
            purpose == "PROTOTYPE"
            and extension not in {"png", "jpg", "jpeg", "webp", "html", "htm"}
        )
        or (purpose != "PROTOTYPE" and extension in {"html", "htm"})
    ):
        raise AppError(422, "document_format")
    root = Settings().document_storage_path.resolve()
    key = uuid4().hex
    staging, destination = root / (key + ".part"), root / key
    committed = False
    try:
        root.mkdir(parents=True, exist_ok=True)
        size, digest = 0, hashlib.sha256()
        with staging.open("xb") as stream:
            async for chunk in chunks:
                size += len(chunk)
                stream.write(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        if size == 0:
            raise AppError(422, "document_empty")
        files.validate_file(staging, extension)
        new_links, links_truncated = file_links(staging) if extension == "md" else ([], False)
        actor = db.get(UserAccount, actor_id, populate_existing=True)
        if actor is None:
            raise AppError(401, "not_authenticated")
        access(project_id, actor, db, lock=True)
        previous = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.project_id == project_id,
                DocumentVersion.upload_id == str(payload.upload_id),
            )
        )
        if previous:
            prior_doc = db.get(SourceDocument, previous.document_id)
            if (
                prior_doc is None
                or prior_doc.purpose != purpose
                or prior_doc.deleted_at is not None
            ):
                raise AppError(409, "document_upload_conflict")
            if (
                previous.sha256 != digest.hexdigest()
                or previous.filename != payload.filename
                or (payload.document_id is not None and previous.document_id != payload.document_id)
            ):
                raise AppError(409, "document_upload_conflict")
            return list_documents(project_id, actor, db, purpose)
        library = library_lock(project_id, payload.revision, actor, db)
        old_version = None
        if payload.document_id:
            doc = db.scalar(
                select(SourceDocument).where(
                    SourceDocument.project_id == project_id,
                    SourceDocument.deleted_at.is_(None),
                    True if purpose is None else SourceDocument.purpose == purpose,
                    SourceDocument.id == payload.document_id,
                )
            )
            if doc is None or doc.kind != "FILE":
                raise AppError(404, "document_not_found")
            old_version = db.scalar(
                select(DocumentVersion.id).where(
                    DocumentVersion.document_id == doc.id,
                    DocumentVersion.number == doc.current_version,
                )
            )
            doc.current_version += 1
            if purpose == "PROTOTYPE":
                doc.name = name or payload.filename
                doc.description = description
        else:
            group_exists(project_id, payload.group_id, db, purpose)
            doc = SourceDocument(
                project_id=project_id,
                purpose=purpose,
                kind="FILE",
                name=name or payload.filename if purpose == "PROTOTYPE" else "",
                description=description,
                group_id=payload.group_id,
                position=last_position(project_id, payload.group_id, db, purpose),
                current_version=1,
            )
            db.add(doc)
            db.flush()
        version = DocumentVersion(
            project_id=project_id,
            document_id=doc.id,
            number=doc.current_version,
            filename=payload.filename,
            extension=extension,
            media_type=files.MEDIA[extension],
            size=size,
            sha256=digest.hexdigest(),
            storage_key=key,
            upload_id=str(payload.upload_id),
            created_by=actor_id,
        )
        db.add(version)
        db.flush()
        if old_version:
            old_bindings = current_bindings(old_version, db)
            present = {link_hash(link["href"]) for link in new_links}
            if links_truncated and any(h not in present for h in old_bindings):
                # Do not silently drop an existing relation whose presence cannot be checked.
                raise AppError(422, "document_links_inheritance_unverified")
            for link in new_links:
                prior = old_bindings.get(link_hash(link["href"]))
                if prior:
                    db.add(
                        DocumentLinkBinding(
                            project_id=project_id,
                            source_version_id=version.id,
                            href=link["href"],
                            href_hash=prior.href_hash,
                            target_version_id=prior.target_version_id,
                            revision=1,
                            inherited_from_id=prior.id,
                            created_by=actor_id,
                        )
                    )
        os.replace(staging, destination)
        library.revision += 1
        db.commit()
        committed = True
        return list_documents(project_id, actor, db, purpose)
    except OSError:
        db.rollback()
        raise AppError(503, "document_storage_unavailable") from None
    finally:
        staging.unlink(missing_ok=True)
        if not committed:
            # A lost COMMIT response can be ambiguous. Preserve an already-renamed file for
            # recovery rather than deleting bytes that may have a committed database reference.
            db.rollback()


def versions(project_id: int, document_id: int, actor: UserAccount, db: Session) -> list[dict]:
    access(project_id, actor, db)
    rows = list(
        db.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.project_id == project_id, DocumentVersion.document_id == document_id
            )
            .order_by(DocumentVersion.number.desc())
        )
    )
    if not rows:
        raise AppError(404, "document_not_found")
    return [version_view(row, db) for row in rows]


def stored_version(
    project_id: int, version_id: int, actor: UserAccount, db: Session
) -> tuple[Path, DocumentVersion]:
    access(project_id, actor, db)
    row = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.project_id == project_id, DocumentVersion.id == version_id
        )
    )
    if row is None:
        raise AppError(404, "document_not_found")
    root = Settings().document_storage_path.resolve()
    path = (root / row.storage_key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise AppError(503, "document_storage_unavailable")
    return path, row


def html_preview(project_id: int, version_id: int, actor: UserAccount, db: Session) -> str:
    path, row = stored_version(project_id, version_id, actor, db)
    if row.extension not in {"html", "htm"}:
        raise AppError(422, "document_format")
    try:
        return files.decode_text(path.read_bytes())
    except OSError:
        raise AppError(503, "document_storage_unavailable") from None


def preview(project_id: int, version_id: int, actor: UserAccount, db: Session) -> dict:
    path, row = stored_version(project_id, version_id, actor, db)
    try:
        return {
            **files.preview(path, row.extension),
            "deleted": db.get(SourceDocument, row.document_id).deleted_at is not None,
        }
    except OSError:
        raise AppError(503, "document_storage_unavailable") from None


def current_bindings(source_version_id: int, db: Session) -> dict[str, DocumentLinkBinding]:
    rows = db.scalars(
        select(DocumentLinkBinding)
        .where(DocumentLinkBinding.source_version_id == source_version_id)
        .order_by(DocumentLinkBinding.revision.desc())
    )
    result = {}
    for row in rows:
        result.setdefault(row.href_hash, row)
    return result


def list_links(project_id: int, version_id: int, actor: UserAccount, db: Session) -> dict:
    access(project_id, actor, db, lock=True)
    path, source = stored_version(project_id, version_id, actor, db)
    if source.extension != "md":
        raise AppError(422, "document_links_require_markdown")
    try:
        links, truncated = file_links(path)
    except OSError:
        raise AppError(503, "document_storage_unavailable") from None
    bindings = current_bindings(version_id, db)
    library = db.get(DocumentLibrary, project_id, populate_existing=True)
    source_doc = db.get(SourceDocument, source.document_id)
    for link in links:
        row = bindings.get(link_hash(link["href"]))
        link["binding"] = None
        if row:
            target = db.get(DocumentVersion, row.target_version_id)
            target_doc = db.get(SourceDocument, target.document_id)
            link["binding"] = {
                "id": row.id,
                "revision": row.revision,
                "target": version_view(target, db),
                "latest_number": target_doc.current_version,
                "inherited": row.inherited_from_id is not None,
            }
    return {
        "revision": library.revision if library else 0,
        "source_version_id": version_id,
        "editable": source.number == source_doc.current_version and source_doc.deleted_at is None,
        "truncated": truncated,
        "links": links,
    }


def bind_link(
    project_id: int, version_id: int, payload: LinkBindingInput, actor: UserAccount, db: Session
) -> dict:
    library = library_lock(project_id, payload.revision, actor, db)
    source = list_links(project_id, version_id, actor, db)
    if not source["editable"]:
        raise AppError(409, "document_link_history_readonly")
    match = next(
        (link for link in source["links"] if link_key(link["href"]) == link_key(payload.href)), None
    )
    if match is None:
        raise AppError(422, "document_link_not_found")
    _, target = stored_version(project_id, payload.target_version_id, actor, db)
    if target.id == version_id:
        raise AppError(422, "document_link_self")
    previous = match["binding"]
    if db.get(SourceDocument, target.document_id).deleted_at is not None and (
        not previous or previous["target"]["id"] != target.id
    ):
        raise AppError(409, "document_deleted")
    if not previous or previous["target"]["id"] != target.id:
        db.add(
            DocumentLinkBinding(
                project_id=project_id,
                source_version_id=version_id,
                href=match["href"],
                href_hash=link_hash(match["href"]),
                target_version_id=target.id,
                revision=previous["revision"] + 1 if previous else 1,
                created_by=actor.id,
            )
        )
        library.revision += 1
        db.commit()
    return list_links(project_id, version_id, actor, db)


def deletion_info(
    project_id: int, document_id: int, actor: UserAccount, db: Session, purpose: str = "REQUIREMENT"
) -> dict:
    access(project_id, actor, db, lock=True)
    doc = db.scalar(
        select(SourceDocument).where(
            SourceDocument.project_id == project_id,
            SourceDocument.id == document_id,
            SourceDocument.purpose == purpose,
            SourceDocument.deleted_at.is_(None),
        )
    )
    if doc is None:
        raise AppError(404, "document_not_found")
    lib = db.get(DocumentLibrary, project_id, populate_existing=True)
    version_ids = select(DocumentVersion.id).where(DocumentVersion.document_id == doc.id)
    latest = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == doc.id, DocumentVersion.number == doc.current_version
        )
    )
    references = set(
        db.scalars(
            select(RequirementSource.rule_id).where(
                RequirementSource.document_version_id.in_(version_ids)
            )
        )
    )
    for rule, task in db.execute(
        select(RequirementRule, RequirementAnalysis)
        .join(RequirementAnalysis, RequirementRule.analysis_id == RequirementAnalysis.id)
        .where(
            RequirementRule.project_id == project_id,
            RequirementAnalysis.context.contains({"source_metadata": [{"id": doc.id}]}),
        )
    ):
        candidate = next(
            (
                c
                for c in (task.result or {}).get("candidates", [])
                if c["key"] == rule.analysis_candidate_key
            ),
            None,
        )
        if candidate and any(e["source_id"] == str(doc.id) for e in candidate["evidence"]):
            references.add(rule.id)
    return {
        "id": doc.id,
        "revision": lib.revision if lib else 0,
        "name": doc.name or (latest.filename if latest else "未命名资料"),
        "kind": doc.kind,
        "versions": db.scalar(
            select(func.count())
            .select_from(DocumentVersion)
            .where(DocumentVersion.document_id == doc.id)
        ),
        "requirement_references": len(references),
        "risk_report_references": db.scalar(
            select(func.count())
            .select_from(RequirementRiskReport)
            .where(
                RequirementRiskReport.project_id == project_id,
                RequirementRiskReport.bindings.contains([{"document_id": doc.id}]),
            )
        ),
        "link_references": db.scalar(
            select(func.count())
            .select_from(DocumentLinkBinding)
            .where(DocumentLinkBinding.target_version_id.in_(version_ids))
        ),
    }


def delete_document(
    project_id: int,
    document_id: int,
    payload: DeleteInput,
    actor: UserAccount,
    db: Session,
    purpose: str = "REQUIREMENT",
) -> dict:
    library = library_lock(project_id, payload.revision, actor, db)
    deletion_info(project_id, document_id, actor, db, purpose)
    doc = db.get(SourceDocument, document_id)
    doc.deleted_at = datetime.now(UTC)
    doc.deleted_by = actor.id
    library.revision += 1
    db.commit()
    return {"id": doc.id, "revision": library.revision}
