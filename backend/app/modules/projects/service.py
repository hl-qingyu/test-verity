from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    CaseAnalysisApplication,
    CaseAnalysisChatTurn,
    CaseAnalysisRun,
    CaseGenerationApplication,
    CaseGenerationBatch,
    CaseGenerationChatTurn,
    CaseGenerationRun,
    ChangeAnalysisChatTurn,
    ChangeAnalysisTask,
    CodeAnalysisChatTurn,
    CodeAnalysisTask,
    GitHubConnection,
    GitHubRepository,
    Project,
    ProjectMember,
    ProjectRepository,
    RequirementChatTurn,
    RequirementRiskAnalysis,
    RequirementRiskReport,
    SourceDocument,
    UserAccount,
)
from app.integrations import github as github_client
from app.modules.github.service import own_connection, saved_token
from app.modules.projects.schemas import (
    GitVersionsQuery,
    MemberInput,
    ProjectInput,
    RepositoryInput,
)


def access_project(
    project_id: int, actor: UserAccount, db: Session, *, write: bool = False, lock: bool = False
) -> Project:
    project = db.get(Project, project_id, with_for_update=lock, populate_existing=True)
    if project is None or project.deleted_at is not None:
        raise AppError(404, "project_not_found")
    manager = actor.platform_role == "ADMIN" or project.owner_id == actor.id
    if not manager and db.get(ProjectMember, (project_id, actor.id)) is None:
        raise AppError(404, "project_not_found")
    if write and not manager:
        raise AppError(403, "project_manager_required")
    return project


def repository_versions(
    project_id: int, repository_id: int, payload: GitVersionsQuery, actor: UserAccount, db: Session
) -> dict:
    def authorized(current_actor):
        access_project(project_id, current_actor, db)
        repo = db.get(ProjectRepository, repository_id, populate_existing=True)
        if repo is None or repo.project_id != project_id:
            raise AppError(404, "project_repository_not_found")
        connection = own_connection(db, current_actor, payload.connection_id)
        if (
            db.get(GitHubRepository, (connection.id, repo.github_id), populate_existing=True)
            is None
        ):
            raise AppError(403, "github_repository_not_allowed")
        return repo, connection

    repo, connection = authorized(actor)
    actor_id, github_id, repo_version, connection_version = (
        actor.id,
        repo.github_id,
        repo.version,
        connection.version,
    )
    token = saved_token(connection)
    db.rollback()
    result = github_client.repository_versions(
        token, github_id, payload.kind, payload.ref, payload.page
    )
    actor = db.get(UserAccount, actor_id, populate_existing=True)
    if actor is None or actor.status != "ACTIVE":
        raise AppError(401, "not_authenticated")
    repo, connection = authorized(actor)
    if (
        repo.github_id != github_id
        or repo.version != repo_version
        or connection.version != connection_version
    ):
        raise AppError(409, "github_connection_changed")
    return {**result, "project_id": project_id, "association_id": repository_id}


def active_account(user_id: int, db: Session) -> UserAccount:
    account = db.get(UserAccount, user_id)
    if account is None or account.status != "ACTIVE":
        raise AppError(422, "project_account_unavailable")
    return account


def project_view(project: Project, actor: UserAccount, db: Session) -> dict:
    owner = db.get(UserAccount, project.owner_id)
    return {
        "id": project.id,
        "name": project.name,
        "identifier": project.identifier,
        "description": project.description,
        "owner_id": project.owner_id,
        "owner_name": owner.display_name,
        "version": project.version,
        "can_manage": actor.platform_role == "ADMIN" or project.owner_id == actor.id,
    }


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "project_duplicate") from None


def list_projects(actor: UserAccount, db: Session) -> list[dict]:
    query = select(Project).where(Project.deleted_at.is_(None)).order_by(Project.id)
    if actor.platform_role != "ADMIN":
        query = query.where(
            or_(
                Project.owner_id == actor.id,
                Project.id.in_(
                    select(ProjectMember.project_id).where(ProjectMember.user_id == actor.id)
                ),
            )
        )
    return [project_view(p, actor, db) for p in db.scalars(query)]


def account_choices(actor: UserAccount, db: Session, search: str = "") -> list[dict]:
    if (
        actor.platform_role != "ADMIN"
        and db.scalar(
            select(Project.id)
            .where(Project.owner_id == actor.id, Project.deleted_at.is_(None))
            .limit(1)
        )
        is None
    ):
        raise AppError(403, "project_manager_required")
    query = select(UserAccount).where(UserAccount.status == "ACTIVE")
    if search.strip():
        query = query.where(
            or_(
                UserAccount.display_name.icontains(search.strip(), autoescape=True),
                UserAccount.login_name.icontains(search.strip(), autoescape=True),
            )
        )
    return [
        {"id": a.id, "name": a.display_name, "login_name": a.login_name}
        for a in db.scalars(query.order_by(UserAccount.id).limit(50))
    ]


def create_project(payload: ProjectInput, actor: UserAccount, db: Session) -> dict:
    if actor.platform_role != "ADMIN" and payload.owner_id != actor.id:
        raise AppError(403, "admin_required")
    active_account(payload.owner_id, db)
    project = Project(**payload.model_dump(exclude={"version"}), created_by=actor.id, version=1)
    project.identifier = "proj-" + uuid4().hex
    db.add(project)
    commit(db)
    return project_view(project, actor, db)


def update_project(project_id: int, payload: ProjectInput, actor: UserAccount, db: Session) -> dict:
    project = access_project(project_id, actor, db, write=True, lock=True)
    if payload.version != project.version:
        raise AppError(409, "project_changed")
    if payload.owner_id != project.owner_id and actor.platform_role != "ADMIN":
        raise AppError(403, "admin_required")
    active_account(payload.owner_id, db)
    project.name, project.description = payload.name, payload.description
    project.owner_id = payload.owner_id
    project.version += 1
    commit(db)
    return project_view(project, actor, db)


def delete_project(project_id, payload, actor, db):
    project = access_project(project_id, actor, db, write=True, lock=True)
    if project.version != payload.version:
        raise AppError(409, "project_changed")
    roots = (
        RequirementRiskAnalysis,
        CodeAnalysisTask,
        ChangeAnalysisTask,
        CaseGenerationRun,
        CaseAnalysisRun,
        CaseGenerationApplication,
        CaseAnalysisApplication,
    )
    queries = [
        select(model.id).where(
            model.project_id == project_id, model.status.in_(("QUEUED", "RUNNING"))
        )
        for model in roots
    ]
    for child, parent, key in (
        (RequirementChatTurn, RequirementRiskReport, "report_id"),
        (CodeAnalysisChatTurn, CodeAnalysisTask, "task_id"),
        (ChangeAnalysisChatTurn, ChangeAnalysisTask, "task_id"),
        (CaseGenerationBatch, CaseGenerationRun, "run_id"),
        (CaseGenerationChatTurn, CaseGenerationRun, "run_id"),
        (CaseAnalysisChatTurn, CaseAnalysisRun, "run_id"),
    ):
        queries.append(
            select(child.id)
            .join(parent, parent.id == getattr(child, key))
            .where(parent.project_id == project_id, child.status.in_(("QUEUED", "RUNNING")))
        )
    if any(db.scalar(query.limit(1)) is not None for query in queries):
        raise AppError(409, "project_delete_active")
    project.deleted_at, project.deleted_by = datetime.now(UTC), actor.id
    project.version += 1
    commit(db)
    return {"id": project.id, "deleted": True}


def list_members(project_id: int, actor: UserAccount, db: Session) -> dict:
    project = access_project(project_id, actor, db)
    ids = select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
    rows = db.scalars(
        select(UserAccount)
        .where(or_(UserAccount.id.in_(ids), UserAccount.id == project.owner_id))
        .order_by(UserAccount.id)
    )
    return {
        "version": project.version,
        "items": [
            {
                "id": a.id,
                "name": a.display_name,
                "role": "负责人" if a.id == project.owner_id else "成员",
                "status": a.status,
            }
            for a in rows
        ],
    }


def add_member(project_id: int, payload: MemberInput, actor: UserAccount, db: Session) -> dict:
    project = access_project(project_id, actor, db, write=True, lock=True)
    if project.version != payload.version:
        raise AppError(409, "project_changed")
    active_account(payload.user_id, db)
    if (
        payload.user_id != project.owner_id
        and db.get(ProjectMember, (project_id, payload.user_id)) is None
    ):
        db.add(ProjectMember(project_id=project_id, user_id=payload.user_id))
        project.version += 1
    commit(db)
    return {"version": project.version}


def remove_member(
    project_id: int, user_id: int, actor: UserAccount, db: Session, version: int
) -> dict:
    project = access_project(project_id, actor, db, write=True, lock=True)
    if project.version != version:
        raise AppError(409, "project_changed")
    if user_id == project.owner_id:
        raise AppError(422, "project_owner_required")
    member = db.get(ProjectMember, (project_id, user_id))
    if member:
        db.delete(member)
        project.version += 1
    commit(db)
    return {"version": project.version}


def list_repositories(project_id: int, actor: UserAccount, db: Session) -> list[dict]:
    access_project(project_id, actor, db)
    authorized = set(
        db.scalars(
            select(GitHubRepository.github_id)
            .join(GitHubConnection)
            .where(GitHubConnection.owner_id == actor.id)
        )
    )
    return [
        {
            "id": r.id,
            "github_id": r.github_id,
            "full_name": r.full_name,
            "url": "https://github.com/" + r.full_name,
            "kind": r.kind,
            "default_branch": r.default_branch,
            "version": r.version,
            "has_personal_authorization": r.github_id in authorized,
        }
        for r in db.scalars(
            select(ProjectRepository)
            .where(ProjectRepository.project_id == project_id)
            .order_by(ProjectRepository.id)
        )
    ]


def delete_repository(
    project_id: int, repository_id: int, version: int, actor: UserAccount, db: Session
) -> dict:
    access_project(project_id, actor, db, write=True, lock=True)
    row = db.scalar(
        select(ProjectRepository)
        .where(ProjectRepository.id == repository_id, ProjectRepository.project_id == project_id)
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "project_repository_not_found")
    if row.version != version:
        raise AppError(409, "project_changed")
    if (
        db.scalar(select(SourceDocument.id).where(SourceDocument.repository_id == row.id).limit(1))
        is not None
    ):
        raise AppError(409, "project_repository_in_use")
    db.delete(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise AppError(409, "project_repository_in_use") from None
    return {"deleted": True}


def bind_repository(
    project_id: int, payload: RepositoryInput, actor: UserAccount, db: Session
) -> dict:
    access_project(project_id, actor, db, write=True)
    connection = own_connection(db, actor, payload.connection_id)
    selected_repo = db.get(GitHubRepository, (connection.id, payload.github_id))
    if selected_repo is None:
        raise AppError(403, "github_repository_not_allowed")
    token, owner, kind, connection_version = (
        saved_token(connection),
        selected_repo.full_name.split("/")[0],
        "organization" if selected_repo.owner_type == "Organization" else "personal",
        connection.version,
    )
    db.rollback()
    remote = github_client.check_repository(
        token, payload.github_id, owner, kind, payload.default_branch
    )
    db.refresh(actor)
    if actor.status != "ACTIVE":
        raise AppError(401, "not_authenticated")
    access_project(project_id, actor, db, write=True, lock=True)
    connection = own_connection(db, actor, payload.connection_id, lock=True)
    if (
        connection.version != connection_version
        or db.get(GitHubRepository, (connection.id, payload.github_id)) is None
    ):
        raise AppError(409, "github_connection_changed")
    row = (
        db.scalar(
            select(ProjectRepository).where(
                ProjectRepository.id == payload.association_id,
                ProjectRepository.project_id == project_id,
            )
        )
        if payload.association_id
        else None
    )
    if payload.association_id and row is None:
        raise AppError(404, "project_repository_not_found")
    if payload.version != (row.version if row else 0):
        raise AppError(409, "project_changed")
    if row is None:
        row = ProjectRepository(project_id=project_id)
        db.add(row)
    row.github_id, row.full_name, row.kind = remote.github_id, remote.full_name, payload.kind
    row.default_branch, row.version, row.updated_by = (
        payload.default_branch,
        payload.version + 1,
        actor.id,
    )
    commit(db)
    return {"id": row.id, "version": row.version}
