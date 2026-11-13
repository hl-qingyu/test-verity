from fastapi import APIRouter, Depends, Query

from app.api.dependencies import DB, Actor, check_origin
from app.modules.projects import service
from app.modules.projects.schemas import (
    DeleteProjectInput,
    DeleteRepositoryInput,
    GitVersionsQuery,
    MemberInput,
    ProjectInput,
    RepositoryInput,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.delete("/{project_id}", dependencies=[Depends(check_origin)])
def delete_project(project_id: int, payload: DeleteProjectInput, actor: Actor, db: DB) -> dict:
    return service.delete_project(project_id, payload, actor, db)


@router.get("")
def list_projects(actor: Actor, db: DB) -> list[dict]:
    return service.list_projects(actor, db)


@router.get("/people")
def account_choices(
    actor: Actor, db: DB, search: str = Query(default="", max_length=80)
) -> list[dict]:
    return service.account_choices(actor, db, search)


@router.post("", dependencies=[Depends(check_origin)], status_code=201)
def create_project(payload: ProjectInput, actor: Actor, db: DB) -> dict:
    return service.create_project(payload, actor, db)


@router.patch("/{project_id}", dependencies=[Depends(check_origin)])
def update_project(project_id: int, payload: ProjectInput, actor: Actor, db: DB) -> dict:
    return service.update_project(project_id, payload, actor, db)


@router.get("/{project_id}/members")
def list_members(project_id: int, actor: Actor, db: DB) -> dict:
    return service.list_members(project_id, actor, db)


@router.post("/{project_id}/members", dependencies=[Depends(check_origin)])
def add_member(project_id: int, payload: MemberInput, actor: Actor, db: DB) -> dict:
    return service.add_member(project_id, payload, actor, db)


@router.delete("/{project_id}/members/{user_id}", dependencies=[Depends(check_origin)])
def remove_member(
    project_id: int, user_id: int, actor: Actor, db: DB, version: int = Query(gt=0)
) -> dict:
    return service.remove_member(project_id, user_id, actor, db, version)


@router.get("/{project_id}/repositories")
def list_repositories(project_id: int, actor: Actor, db: DB) -> list[dict]:
    return service.list_repositories(project_id, actor, db)


@router.get("/{project_id}/repositories/{repository_id}/versions")
def repository_versions(
    project_id: int, repository_id: int, actor: Actor, db: DB, payload: GitVersionsQuery = Query()
) -> dict:
    return service.repository_versions(project_id, repository_id, payload, actor, db)


@router.delete("/{project_id}/repositories/{repository_id}", dependencies=[Depends(check_origin)])
def delete_repository(
    project_id: int, repository_id: int, payload: DeleteRepositoryInput, actor: Actor, db: DB
) -> dict:
    return service.delete_repository(project_id, repository_id, payload.version, actor, db)


@router.post("/{project_id}/repositories", dependencies=[Depends(check_origin)])
def bind_repository(project_id: int, payload: RepositoryInput, actor: Actor, db: DB) -> dict:
    return service.bind_repository(project_id, payload, actor, db)
