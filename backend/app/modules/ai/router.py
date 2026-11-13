from fastapi import APIRouter, Depends, Request

from app.api.dependencies import DB, Actor, check_origin, limit_login
from app.api.encryption import EncryptedRequest, decrypt_payload
from app.modules.ai import service
from app.modules.ai.schemas import (
    ActivationInput,
    ConfigurationInput,
    ConnectionInput,
    ModelDiscoveryInput,
    TestInput,
)

router = APIRouter(prefix="/api/ai-service", tags=["ai-service"])


@router.get("")
def read_configuration(actor: Actor, db: DB) -> dict:
    return service.read_configuration(actor, db)


@router.post("/personal", dependencies=[Depends(check_origin)])
def save_configuration(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    payload = decrypt_payload(envelope, request, ConnectionInput)
    return service.save_configuration(payload, actor, db)


@router.post("/personal/test", dependencies=[Depends(check_origin)])
def test_configuration(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    limit_login(request, f"ai_test_{actor.id}")
    payload = decrypt_payload(envelope, request, ConnectionInput)
    return service.test_configuration(payload, actor, db)


@router.post("/personal/models", dependencies=[Depends(check_origin)])
def discover_models(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    limit_login(request, f"ai_models_{actor.id}")
    payload = decrypt_payload(envelope, request, ModelDiscoveryInput)
    return service.discover_models(payload, actor, db)


@router.post("/configuration", dependencies=[Depends(check_origin)])
def save_and_select(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    return service.save_and_select(
        decrypt_payload(envelope, request, ConfigurationInput), actor, db
    )


@router.post("/activate", dependencies=[Depends(check_origin)])
def activate(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    return service.activate_configuration(
        decrypt_payload(envelope, request, ActivationInput), actor, db
    )


@router.post("/test", dependencies=[Depends(check_origin)])
def test_current(envelope: EncryptedRequest, request: Request, actor: Actor, db: DB) -> dict:
    limit_login(request, f"ai_test_{actor.id}")
    return service.test_configuration(decrypt_payload(envelope, request, TestInput), actor, db)
