"""Immutable uploaded directory versions; archive paths are never extracted to disk."""

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import DocumentVersion, SourceDocument, UserAccount
from app.modules.documents import files
from app.modules.documents import service as documents
from app.modules.prototypes import html_preview as preview_html
from app.modules.prototypes.schemas import ImageUpload
from app.modules.requirements import analysis_materials
from app.security.source_content import contains_private_key

TEXT = {"html", "htm", "css", "js", "ts", "jsx", "tsx", "vue", "json", "md", "txt", "svg"}
IMAGES = {"png", "jpg", "jpeg", "webp"}
EXCLUDED = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "target",
    "build",
    "dist",
    ".next",
    ".nuxt",
    ".idea",
    ".vscode",
    ".ssh",
    ".aws",
    ".azure",
    "coverage",
    ".codex",
    ".npmrc",
    ".pypirc",
    ".netrc",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
}


def safe_path(value):
    try:
        value.encode("utf-8")
    except (AttributeError, UnicodeError):
        return False
    return (
        isinstance(value, str)
        and 0 < len(value) <= 512
        and not any(ord(c) < 32 or ord(c) == 127 or c in "\\:" for c in value)
        and all(
            p
            and p not in {".", ".."}
            and p.lower() not in EXCLUDED
            and not p.lower().startswith(".env")
            and not re.match(r"id_(rsa|dsa|ecdsa|ed25519)(\.|$)", p, re.I)
            for p in value.split("/")
        )
        and value.rsplit(".", 1)[-1].lower() in TEXT | IMAGES
    )


def unique_paths(paths):
    ordered = sorted(paths)
    return len(set(paths)) == len(paths) and not any(
        b.startswith(a + "/") for a, b in zip(ordered, ordered[1:])
    )


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str
    size: int = Field(ge=0)

    @field_validator("path")
    @classmethod
    def valid_path(cls, value):
        if not safe_path(value):
            raise ValueError("invalid directory path")
        return value


def public_files(version):
    return [
        {k: f[k] for k in ("path", "size", "sha256", "extension")} for f in version.directory_files
    ]


def checked(project_id, source_id, version_id, paths, actor, db, *, allow_absent=False):
    _, version = documents.stored_version(project_id, version_id, actor, db)
    source = db.get(SourceDocument, source_id)
    if (
        source is None
        or source.project_id != project_id
        or source.purpose != "PROTOTYPE"
        or source.kind != "DIRECTORY"
        or version.document_id != source_id
    ):
        raise AppError(422, "prototype_directory_version_invalid")
    index = {f["path"]: f for f in version.directory_files}
    if paths is not None and (
        not paths
        or len(set(paths)) != len(paths)
        or any(not safe_path(p) or not allow_absent and p not in index for p in paths)
    ):
        raise AppError(422, "prototype_directory_selection_invalid")
    return version, index


def file_path(entry):
    key = entry["storage_key"]
    if not re.fullmatch(r"[a-f0-9]{32}", key):
        raise AppError(503, "document_storage_unavailable")
    path = Settings().document_storage_path.resolve() / key
    try:
        with path.open("rb") as stream:
            if (
                path.stat().st_size != entry["size"]
                or hashlib.file_digest(stream, "sha256").hexdigest() != entry["sha256"]
            ):
                raise AppError(409, "prototype_directory_file_changed")
    except OSError:
        raise AppError(503, "document_storage_unavailable") from None
    return path


def catalog(project_id, source_id, version_id, actor, db):
    version, _ = checked(project_id, source_id, version_id, None, actor, db)
    return {
        "document_id": source_id,
        "version_id": version.id,
        "sha256": version.sha256,
        "files": public_files(version),
    }


def get_file(project_id, source_id, version_id, path, actor, db):
    _, index = checked(project_id, source_id, version_id, [path], actor, db)
    entry = index[path]
    return file_path(entry), entry


def preview(project_id, source_id, version_id, path, actor, db):
    stored, entry = get_file(project_id, source_id, version_id, path, actor, db)
    if entry["extension"] in IMAGES:
        return {"kind": "image", "text": ""}
    text, truncated = files.text_prefix(stored)
    return {"kind": "text", "text": text[:100000], "truncated": truncated or len(text) > 100000}


def html_preview(project_id, source_id, version_id, path, actor, db):
    stored, entry = get_file(project_id, source_id, version_id, path, actor, db)
    if entry["extension"] not in {"html", "htm"}:
        raise AppError(422, "document_format")
    _, index = checked(project_id, source_id, version_id, None, actor, db)
    html = preview_html.render(
        files.decode_text(stored.read_bytes()),
        path,
        index,
        lambda item: file_path(item).read_bytes(),
    )
    documents.access(project_id, actor, db)
    return html


def download(project_id, source_id, version_id, actor, db):
    version, _ = checked(project_id, source_id, version_id, None, actor, db)
    target = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    try:
        with tarfile.open(fileobj=target, mode="w", format=tarfile.PAX_FORMAT) as archive:
            for entry in version.directory_files:
                info = tarfile.TarInfo(entry["path"])
                info.size = entry["size"]
                with file_path(entry).open("rb") as content:
                    archive.addfile(info, content)
        documents.access(project_id, actor, db)
        db.rollback()
        target.seek(0)
    except OSError:
        target.close()
        raise AppError(503, "document_storage_unavailable") from None
    except BaseException:
        target.close()
        raise

    def chunks():
        try:
            while chunk := target.read(1024 * 1024):
                yield chunk
        finally:
            target.close()

    return chunks()


async def upload(project_id, source_id, payload: ImageUpload, chunks, actor, db):
    documents.access(project_id, actor, db)
    actor_id = actor.id
    db.rollback()
    root = Settings().document_storage_path.resolve()
    key = uuid4().hex
    staging, destination = root / (key + ".part"), root / key
    created, published = [], False
    try:
        root.mkdir(parents=True, exist_ok=True)
        size, digest = 0, hashlib.sha256()
        with staging.open("xb") as stream:
            async for chunk in chunks:
                stream.write(chunk)
                size += len(chunk)
                digest.update(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        # Uncompressed internal TAR framing uses numeric member names. User paths live in JSON.
        manifest = []
        with tarfile.open(staging, "r:") as archive:
            iterator = iter(archive)
            header = next(iterator, None)
            if (
                not header
                or header.name != "manifest.json"
                or not header.isfile()
                or header.sparse is not None
            ):
                raise AppError(422, "prototype_directory_invalid")
            try:
                package = json.load(archive.extractfile(header))
                expected = {
                    "name": payload.name.strip() or payload.filename,
                    "description": payload.description,
                    "group_id": payload.group_id,
                    "source_id": source_id,
                    "directory_name": payload.filename,
                }
                if (
                    not isinstance(package, dict)
                    or set(package) != {"metadata", "files"}
                    or package["metadata"] != expected
                ):
                    raise ValueError("metadata mismatch")
                raw = package["files"]
                if not isinstance(raw, list) or not raw:
                    raise ValueError("empty manifest")
                entries = [Entry.model_validate(f) for f in raw]
                if not unique_paths([f.path for f in entries]):
                    raise ValueError("duplicate path")
            except (ValueError, UnicodeError, ValidationError):
                raise AppError(422, "prototype_directory_invalid") from None
            for n, entry in enumerate(entries):
                member = next(iterator, None)
                if (
                    not member
                    or not member.isfile()
                    or member.sparse is not None
                    or member.name != f"f{n}"
                    or member.size != entry.size
                ):
                    raise AppError(422, "prototype_directory_invalid")
                storage_key = uuid4().hex
                target = root / storage_key
                created.append(target)
                with archive.extractfile(member) as incoming, target.open("xb") as output:
                    shutil.copyfileobj(incoming, output, 1024 * 1024)
                    output.flush()
                    os.fsync(output.fileno())
                extension = entry.path.rsplit(".", 1)[-1].lower()
                if extension in IMAGES:
                    files.validate_file(target, extension)
                elif contains_private_key(files.decode_text(target.read_bytes())):
                    raise AppError(422, "code_private_key_content")
                with target.open("rb") as content:
                    sha = hashlib.file_digest(content, "sha256").hexdigest()
                if target.stat().st_size != entry.size:
                    raise AppError(422, "prototype_directory_invalid")
                manifest.append(
                    {
                        **entry.model_dump(),
                        "sha256": sha,
                        "extension": extension,
                        "storage_key": storage_key,
                    }
                )
            if next(iterator, None) is not None:
                raise AppError(422, "prototype_directory_invalid")
            with staging.open("rb") as trailer:
                trailer.seek(archive.offset)
                while chunk := trailer.read(1024 * 1024):
                    if any(chunk):
                        raise AppError(422, "prototype_directory_invalid")
        actor = db.get(UserAccount, actor_id, populate_existing=True)
        if actor is None:
            raise AppError(401, "not_authenticated")
        documents.access(project_id, actor, db, lock=True)
        prior = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.project_id == project_id,
                DocumentVersion.upload_id == str(payload.upload_id),
            )
        )
        if prior:
            row = db.get(SourceDocument, prior.document_id)
            if (
                row.kind != "DIRECTORY"
                or row.deleted_at is not None
                or prior.sha256 != digest.hexdigest()
                or source_id is not None
                and row.id != source_id
                or prior.created_by != actor_id
            ):
                raise AppError(409, "document_upload_conflict")
            return prior.document_id
        library = documents.library_lock(project_id, payload.revision, actor, db)
        if source_id:
            row = db.get(SourceDocument, source_id, populate_existing=True)
            if (
                not row
                or row.project_id != project_id
                or row.kind != "DIRECTORY"
                or row.deleted_at is not None
            ):
                raise AppError(404, "prototype_not_found")
            row.current_version += 1
            documents.group_exists(project_id, payload.group_id, db, "PROTOTYPE")
            if row.group_id != payload.group_id:
                row.position = documents.last_position(
                    project_id, payload.group_id, db, "PROTOTYPE"
                )
                row.group_id = payload.group_id
        else:
            documents.group_exists(project_id, payload.group_id, db, "PROTOTYPE")
            row = SourceDocument(
                project_id=project_id,
                kind="DIRECTORY",
                purpose="PROTOTYPE",
                current_version=1,
                group_id=payload.group_id,
                position=documents.last_position(project_id, payload.group_id, db, "PROTOTYPE"),
            )
            db.add(row)
            db.flush()
        row.name, row.description = payload.name.strip() or payload.filename, payload.description
        db.add(
            DocumentVersion(
                project_id=project_id,
                document_id=row.id,
                number=row.current_version,
                filename=payload.filename + ".tar",
                extension="directory",
                media_type="application/x-tar",
                size=size,
                sha256=digest.hexdigest(),
                storage_key=key,
                upload_id=str(payload.upload_id),
                created_by=actor_id,
                directory_files=manifest,
            )
        )
        os.replace(staging, destination)
        # Keep renamed bytes after an ambiguous commit; a later query resolves the UUID.
        published = True
        library.revision += 1
        db.commit()
        return row.id
    except (tarfile.TarError, EOFError, OverflowError):
        raise AppError(422, "prototype_directory_invalid") from None
    except OSError:
        raise AppError(503, "document_storage_unavailable") from None
    finally:
        db.rollback()
        staging.unlink(missing_ok=True)
        if not published:
            for path in created:
                path.unlink(missing_ok=True)


def material(project_id, source_id, version_id, paths, ref, actor, db):
    version, index = checked(project_id, source_id, version_id, paths, actor, db)
    segments, binaries = [], []
    for n, name in enumerate(paths, 1):
        entry, segment_id = index[name], f"f{n}"
        path = file_path(entry)
        if entry["extension"] in IMAGES:
            segments.append(
                {
                    "segment_id": segment_id,
                    "location": name,
                    "text": "",
                    "image_ref": f"{ref}#{segment_id}",
                }
            )
            binaries.append((path, entry["extension"], f"{ref}#{segment_id}", name))
        else:
            text = files.decode_text(path.read_bytes())
            for segment in analysis_materials.text_segments(text, name):
                segments.append({**segment, "segment_id": f"{segment_id}-{segment['segment_id']}"})
    return {
        "source_id": ref,
        "kind": "PROTOTYPE_CODE",
        "snapshot_ref": version.sha256,
        "read_state": "PARTIAL",
        "read_note": (
            f"固定目录版本v{version.number}的{len(paths)}个所选文件；未执行脚本或读取未选择的依赖。"
        ),
        "segments": segments,
    }, binaries


def bind_material(project_id, source_id, version_id, segments, ref, actor, db):
    """Infer only explicit file locations, then compare the full supplied fixed segments."""
    version, index = checked(project_id, source_id, version_id, None, actor, db)
    paths = []
    for segment in segments:
        matches = [
            p
            for p in index
            if segment["location"] == p or segment["location"].startswith(p + " · ")
        ]
        if len(matches) != 1:
            raise AppError(422, "prototype_directory_selection_invalid")
        if matches[0] not in paths:
            paths.append(matches[0])
    actual, _ = material(project_id, source_id, version_id, paths, ref, actor, db)
    fields = ("segment_id", "location", "text", "image_ref")
    supplied = [{k: s[k] for k in fields} for s in segments]
    normalized = [
        {**s, "text": s["text"].replace("\r\n", "\n").replace("\r", "\n")}
        for s in actual["segments"]
    ]
    if supplied not in (actual["segments"], normalized):
        raise AppError(422, "prototype_directory_file_changed")
    return version, paths
