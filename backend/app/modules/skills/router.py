from fastapi import APIRouter, Depends, Query

from app.api.dependencies import DB, Actor, Admin, check_origin
from app.modules.skills import schemas, service

router = APIRouter(prefix="/api/skills", tags=["skills"])


@router.get("")
def listing(actor: Actor):
    return service.listing()


@router.get("/{key}")
def detail(
    key: str,
    actor: Actor,
    include_contents: bool = False,
    known_token: str = "",
    refresh: bool = False,
):
    return service.detail(key, include_contents, known_token, refresh)


@router.get("/{key}/files/{file_id}")
def read_file(key: str, file_id: str, actor: Actor):
    return service.read_file(key, file_id)


@router.put("/{key}/content", dependencies=[Depends(check_origin)])
def save(key: str, payload: schemas.Save, actor: Admin, db: DB):
    return service.save(key, payload, actor, db)


@router.get("/{key}/chat")
def conversations(key: str, actor: Admin, db: DB, before: int | None = Query(None, ge=1)):
    return service.conversations(key, actor, db, before)


@router.post("/{key}/chat", dependencies=[Depends(check_origin)], status_code=202)
def enqueue(key: str, payload: schemas.Chat, actor: Admin, db: DB):
    return service.enqueue(key, payload, actor, db)


@router.post("/{key}/chat/{turn_id}/cancel", dependencies=[Depends(check_origin)])
def cancel(key: str, turn_id: int, actor: Admin, db: DB):
    return service.cancel(key, turn_id, actor, db)
