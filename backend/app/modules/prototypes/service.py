from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    DocumentGroup,
    DocumentLibrary,
    DocumentVersion,
    GitHubConnection,
    GitHubRepository,
    ProjectRepository,
    SourceDocument,
    UserAccount,
)
from app.integrations import github as client
from app.integrations import prototype_link
from app.modules.documents import service as documents
from app.modules.github.service import own_connection, saved_token
from app.modules.prototypes.schemas import GitScope, LiveInput


def options(project_id: int, actor: UserAccount, db: Session) -> list[dict]:
    documents.access(project_id, actor, db)
    connections = db.scalars(
        select(GitHubConnection)
        .where(GitHubConnection.owner_id == actor.id)
        .order_by(GitHubConnection.id)
    )
    result = []
    for connection in connections:
        repos = db.scalars(
            select(ProjectRepository)
            .join(GitHubRepository, GitHubRepository.github_id == ProjectRepository.github_id)
            .where(
                ProjectRepository.project_id == project_id,
                GitHubRepository.connection_id == connection.id,
            )
            .order_by(ProjectRepository.id)
        )
        result.append(
            {
                "id": connection.id,
                "name": connection.name,
                "repositories": [
                    {"id": r.id, "name": r.full_name, "branch": r.default_branch} for r in repos
                ],
            }
        )
    return result


def own(project_id: int, source_id: int, db: Session) -> SourceDocument:
    row = db.scalar(
        select(SourceDocument).where(
            SourceDocument.id == source_id,
            SourceDocument.project_id == project_id,
            SourceDocument.deleted_at.is_(None),
            SourceDocument.purpose == "PROTOTYPE",
        )
    )
    if row is None:
        raise AppError(404, "prototype_not_found")
    return row


def row_view(row: SourceDocument, db: Session) -> dict:
    repo = db.get(ProjectRepository, row.repository_id) if row.repository_id else None
    version = (
        db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == row.id,
                DocumentVersion.number == row.current_version,
            )
        )
        if row.kind in {"FILE", "DIRECTORY"}
        else None
    )
    return {
        "id": row.id,
        "kind": row.kind,
        "name": row.name,
        "description": row.description,
        "group_id": row.group_id,
        "position": row.position,
        "url": row.url,
        "repository_id": row.repository_id,
        "repository_name": repo.full_name if repo else None,
        "github_id": repo.github_id if repo else None,
        "branch": row.branch,
        "path": row.path,
        "selected_paths": row.selected_paths,
        "latest_commit": row.latest_commit,
        "files": row.file_manifest,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        "current": documents.version_view(version, db) if version else None,
    }


def state(project_id: int, actor: UserAccount, db: Session) -> dict:
    documents.access(project_id, actor, db, lock=True)
    library = db.get(DocumentLibrary, project_id, populate_existing=True)
    rows = db.scalars(
        select(SourceDocument)
        .where(
            SourceDocument.project_id == project_id,
            SourceDocument.deleted_at.is_(None),
            SourceDocument.purpose == "PROTOTYPE",
        )
        .order_by(SourceDocument.position, SourceDocument.id)
    ).all()
    groups = db.scalars(
        select(DocumentGroup)
        .where(
            DocumentGroup.project_id == project_id,
            DocumentGroup.purpose == "PROTOTYPE",
        )
        .order_by(DocumentGroup.id)
    )
    return {
        "revision": library.revision if library else 0,
        "groups": [{"id": g.id, "name": g.name} for g in groups],
        "sources": [row_view(row, db) for row in rows],
    }


def authorization(project_id: int, payload: GitScope, actor: UserAccount, db: Session, lock=False):
    documents.access(project_id, actor, db, lock=lock)
    repo = db.get(ProjectRepository, payload.repository_id, populate_existing=True)
    if repo is None or repo.project_id != project_id:
        raise AppError(404, "project_repository_not_found")
    connection = own_connection(db, actor, payload.connection_id, lock=lock)
    grant = db.get(GitHubRepository, (connection.id, repo.github_id), populate_existing=True)
    if grant is None:
        raise AppError(403, "github_repository_not_allowed")
    return repo, connection


def read_scope(project_id: int, payload: GitScope, actor: UserAccount, db: Session) -> dict:
    repo, connection = authorization(project_id, payload, actor, db)
    actor_id, repo_id, connection_version = actor.id, repo.github_id, connection.version
    token = saved_token(connection)
    db.rollback()
    result = (
        client.prototype_scope(token, repo_id, payload.branch, payload.path, allow_empty=True)
        if payload.comparison
        else client.prototype_scope(token, repo_id, payload.branch, payload.path)
    )
    actor = db.get(UserAccount, actor_id, populate_existing=True)
    if actor is None:
        raise AppError(401, "not_authenticated")
    repo, connection = authorization(project_id, payload, actor, db, lock=True)
    if repo.github_id != repo_id or connection.version != connection_version:
        raise AppError(409, "github_connection_changed")
    return result


def selected_manifest(result: dict, paths: list[str]) -> list[dict]:
    entries = {entry["path"]: entry for entry in result["files"]}
    if not paths or any(path not in entries for path in paths):
        raise AppError(409, "prototype_files_changed")
    return [entries[path] for path in paths]


def save_live(
    project_id: int, source_id: int | None, payload: LiveInput, actor: UserAccount, db: Session
) -> dict:
    # Check existing type and revision before the remote wait, then repeat under the project lock.
    documents.library_lock(project_id, payload.revision, actor, db)
    if source_id and own(project_id, source_id, db).kind != payload.kind:
        raise AppError(422, "prototype_kind_changed")
    result = read_scope(project_id, payload.git, actor, db) if payload.git else None
    if result and result["commit"] != payload.commit:
        raise AppError(409, "prototype_commit_changed")
    manifest = selected_manifest(result, payload.selected_paths) if result else []
    library = documents.library_lock(project_id, payload.revision, actor, db)
    documents.group_exists(project_id, payload.group_id, db, "PROTOTYPE")
    row = (
        own(project_id, source_id, db)
        if source_id
        else SourceDocument(
            project_id=project_id,
            purpose="PROTOTYPE",
            kind=payload.kind,
            current_version=1,
            position=documents.last_position(project_id, payload.group_id, db, "PROTOTYPE"),
        )
    )
    if row.kind != payload.kind:
        raise AppError(422, "prototype_kind_changed")
    if source_id and row.group_id != payload.group_id:
        row.position = documents.last_position(project_id, payload.group_id, db, "PROTOTYPE")
    row.group_id, row.name, row.description = payload.group_id, payload.name, payload.description
    row.url = payload.url
    if payload.git:
        row.repository_id, row.branch, row.path = (
            payload.git.repository_id,
            payload.git.branch,
            payload.git.path,
        )
        row.selected_paths, row.file_manifest = payload.selected_paths, manifest
        row.latest_commit, row.checked_at = result["commit"], datetime.now(UTC)
    db.add(row)
    library.revision += 1
    db.commit()
    return state(project_id, actor, db)


def link_catalog(project_id: int, source_id: int, actor: UserAccount, db: Session) -> dict:
    documents.access(project_id, actor, db)
    row = own(project_id, source_id, db)
    if row.kind != "LINK" or not row.url:
        raise AppError(422, "prototype_link_unsupported")
    url = row.url
    db.rollback()
    result = prototype_link.catalog(url)
    documents.access(project_id, actor, db)
    if own(project_id, source_id, db).url != url:
        raise AppError(409, "prototype_link_changed")
    return {"snapshot": result["snapshot"], "pages": result["pages"]}


def link_pages(
    project_id: int,
    source_id: int,
    files: list[str],
    snapshot: str,
    actor: UserAccount,
    db: Session,
) -> dict:
    documents.access(project_id, actor, db)
    row = own(project_id, source_id, db)
    if row.kind != "LINK" or not row.url:
        raise AppError(422, "prototype_link_unsupported")
    url = row.url
    db.rollback()
    result = prototype_link.read_pages(url, files, snapshot)
    documents.access(project_id, actor, db)
    if own(project_id, source_id, db).url != url:
        raise AppError(409, "prototype_link_changed")
    return result


def check(
    project_id: int, source_id: int, connection_id: int, actor: UserAccount, db: Session
) -> dict:
    documents.access(project_id, actor, db)
    row = own(project_id, source_id, db)
    if row.kind != "GITHUB":
        raise AppError(422, "prototype_kind_changed")
    config = (row.repository_id, row.branch, row.path, tuple(row.selected_paths), row.checked_at)
    payload = GitScope(
        connection_id=connection_id,
        repository_id=row.repository_id,
        branch=row.branch,
        path=row.path,
    )
    result = read_scope(project_id, payload, actor, db)
    db.expire_all()
    row = own(project_id, source_id, db)
    if config != (
        row.repository_id,
        row.branch,
        row.path,
        tuple(row.selected_paths),
        row.checked_at,
    ):
        raise AppError(409, "documents_changed")
    manifest = selected_manifest(result, row.selected_paths)
    previous = row.latest_commit
    row.latest_commit, row.file_manifest, row.checked_at = (
        result["commit"],
        manifest,
        datetime.now(UTC),
    )
    db.commit()
    return {
        "changed": previous is not None and previous != result["commit"],
        "previous_commit": previous,
        "source": row_view(row, db),
    }
