from fastapi import APIRouter, Depends

from app.api.dependencies import DB, Actor, Admin, check_origin
from app.modules.acceptance import schemas, service

router = APIRouter(prefix="/api", tags=["analysis-acceptance"])


@router.get("/analysis-acceptance")
def all_projects(actor: Admin, db: DB):
    return {"project_id": None, "modules": service.project_summary(None, actor, db)}


@router.get("/projects/{project_id}/analysis-acceptance")
def summary(project_id: int, actor: Admin, db: DB):
    return {"project_id": project_id, "modules": service.project_summary(project_id, actor, db)}


@router.get("/projects/{project_id}/analysis-acceptance/{module}/{record_id}")
def detail(project_id: int, module: schemas.Module, record_id: int, actor: Actor, db: DB):
    return service.detail(module, project_id, record_id, actor, db)


@router.post(
    "/projects/{project_id}/analysis-acceptance/{module}/{record_id}",
    dependencies=[Depends(check_origin)],
)
def save(
    project_id: int,
    module: schemas.Module,
    record_id: int,
    payload: schemas.Save,
    actor: Actor,
    db: DB,
):
    return service.save(module, project_id, record_id, payload, actor, db)
