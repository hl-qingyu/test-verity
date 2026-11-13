from typing import Annotated

from fastapi import APIRouter, Query

from app.api.dependencies import DB, Actor
from app.modules.overview import schemas, service

router = APIRouter(prefix="/api/projects/{project_id}/overview", tags=["overview"])


@router.get("")
def summary(project_id: int, actor: Actor, db: DB, query: Annotated[schemas.Query, Query()]):
    return service.summary(project_id, actor, db, query)


@router.get("/attention")
def attention(
    project_id: int, actor: Actor, db: DB, query: Annotated[schemas.AttentionQuery, Query()]
):
    return service.attention(project_id, actor, db, query)
