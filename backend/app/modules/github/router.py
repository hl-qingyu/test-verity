from fastapi import APIRouter, Depends, Request

from app.api.dependencies import DB, Actor, check_origin, limit_login
from app.api.encryption import EncryptedRequest, decrypt_payload, session_binding
from app.modules.github import service
from app.modules.github.schemas import DeleteConnectionInput, ProbeInput, SaveInput

router = APIRouter(prefix="/api/github", tags=["github"])


@router.delete("/connections/{connection_id}", dependencies=[Depends(check_origin)])
def delete_connection(
    connection_id: int, payload: DeleteConnectionInput, actor: Actor, db: DB
) -> dict:
    return service.delete_connection(connection_id, payload.version, actor, db)


@router.get("/connections")
def list_connections(actor: Actor, db: DB) -> list[dict]:
    return service.list_connections(actor, db)


@router.post("/connections/probe", dependencies=[Depends(check_origin)])
def probe_connection(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    limit_login(request, f"github_probe_{actor.id}")
    payload = decrypt_payload(envelope, request, ProbeInput)
    return service.probe_connection(payload, actor, db, session_binding(request))


@router.post("/connections", dependencies=[Depends(check_origin)])
def save_connection(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    limit_login(request, f"github_save_{actor.id}")
    payload = decrypt_payload(envelope, request, SaveInput)
    return service.save_connection(payload, actor, db, session_binding(request))
