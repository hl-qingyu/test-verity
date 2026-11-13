from fastapi import APIRouter, Depends

from app.api.dependencies import DB, Actor, check_origin
from app.modules.local_code import service
from app.modules.local_code.schemas import SourceInput, SourceView

router = APIRouter(prefix="/api/projects/{project_id}/local-code", tags=["local-code"])


@router.get("", response_model=list[SourceView])
def list_sources(project_id: int, actor: Actor, db: DB) -> list[SourceView]:
    return service.list_sources(project_id, actor, db)


@router.post("", response_model=SourceView, dependencies=[Depends(check_origin)])
def save_source(project_id: int, payload: SourceInput, actor: Actor, db: DB) -> SourceView:
    return service.save_source(project_id, payload, actor, db)
