from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AICallPreference, AICLIConnection, AIConnection, UserAccount
from app.integrations import ai_client, codex_exec, responses
from app.modules.ai import reservations
from app.modules.ai.schemas import (
    ActivationInput,
    ConfigurationInput,
    ConnectionInput,
    ModelDiscoveryInput,
    TestInput,
)
from app.security.secrets import credential_cipher


def cipher() -> Fernet:
    return credential_cipher("ai_key_storage_unavailable")


def metadata(connection: AIConnection | AICLIConnection | None) -> dict | None:
    if connection is None:
        return None
    return {
        "name": connection.name,
        "base_url": connection.base_url,
        "model": connection.model,
        "reasoning_effort": connection.reasoning_effort,
        "has_key": bool(connection.encrypted_key),
        "version": connection.version,
    }


def lock_changes(db: Session, actor: UserAccount) -> None:
    # ponytail: serialize rare configuration writes; per-owner locks if usage grows.
    db.execute(text("SELECT pg_advisory_xact_lock(2026091102)"))
    db.refresh(actor, with_for_update=True)
    if actor.status != "ACTIVE":
        raise AppError(401, "not_authenticated")


def check_version(connection: AIConnection | AICLIConnection | None, version: int) -> None:
    if version != (connection.version if connection else 0):
        raise AppError(409, "ai_configuration_changed")


def resolve_key(
    payload: ConnectionInput | ModelDiscoveryInput,
    connection: AIConnection | AICLIConnection | None,
) -> str:
    if payload.api_key.get_secret_value():
        return payload.api_key.get_secret_value()
    if connection is None:
        raise AppError(422, "ai_key_required")
    if payload.base_url != connection.base_url:
        raise AppError(422, "ai_new_address_requires_key")
    try:
        return cipher().decrypt(connection.encrypted_key.encode("ascii")).decode("ascii")
    except (InvalidToken, ValueError, UnicodeError):
        raise AppError(503, "ai_key_storage_unavailable") from None


def preference(actor, db):
    row = db.get(AICallPreference, actor.id, populate_existing=True)
    return (row.call_mode, row.version) if row else ("RESPONSES_API", 0)


def connection_for(actor, db, mode):
    if mode not in ("RESPONSES_API", "CODEX_EXEC"):
        raise AppError(422, "ai_call_mode_invalid")
    return db.get(
        AICLIConnection if mode == "CODEX_EXEC" else AIConnection, actor.id, populate_existing=True
    )


def current_metadata(actor, db, mode=None):
    selected, pref_version = preference(actor, db)
    selected = mode or selected
    value = metadata(connection_for(actor, db, selected))
    return (
        {
            **value,
            "call_mode": selected,
            "preference_version": pref_version,
            "client_version": codex_exec.VERSION if selected == "CODEX_EXEC" else "responses-v1",
            **({"execution_policy": codex_exec.NATIVE_POLICY} if selected == "CODEX_EXEC" else {}),
        }
        if value
        else None
    )


def configuration_revision(actor, db):
    """One scalar projection for list refresh keys; never load credentials or task input."""
    row = db.execute(
        select(
            AICallPreference.call_mode,
            AICallPreference.version,
            AIConnection.version,
            AICLIConnection.version,
        )
        .select_from(UserAccount)
        .outerjoin(
            AICallPreference,
            AICallPreference.owner_id == UserAccount.id,
        )
        .outerjoin(AIConnection, AIConnection.owner_id == UserAccount.id)
        .outerjoin(
            AICLIConnection,
            AICLIConnection.owner_id == UserAccount.id,
        )
        .where(UserAccount.id == actor.id)
    ).one()
    return [row[0] or "RESPONSES_API", row[1] or 0, row[3] if row[0] == "CODEX_EXEC" else row[2]]


def read_configuration(actor: UserAccount, db: Session) -> dict:
    mode, version = preference(actor, db)
    return {
        "personal": metadata(db.get(AIConnection, actor.id)),
        "cli": metadata(db.get(AICLIConnection, actor.id)),
        "call_mode": mode,
        "preference_version": version,
        "cli_runtime": codex_exec.runtime_status(),
        "allowed_base_urls": Settings().ai_allowed_base_urls,
    }


def analysis_configuration(actor, db, version=None, *, mode=None, preference_version=None):
    """A persisted snapshot selects its own mode; missing historical mode means API."""
    current = db.get(UserAccount, actor.id, populate_existing=True)
    if current is None or current.status != "ACTIVE":
        raise AppError(401, "not_authenticated")
    snapshot = version if isinstance(version, dict) else None
    if snapshot is not None:
        mode = snapshot.get("call_mode", "RESPONSES_API")
        version = snapshot.get("version")
        if type(version) is not int or version < 1:
            raise AppError(409, "ai_configuration_changed")
    selected, pref_version = preference(actor, db)
    if preference_version is not None and (preference_version != pref_version or mode != selected):
        raise AppError(409, "ai_preference_changed")
    mode = mode or selected
    connection = connection_for(actor, db, mode)
    if connection is None or connection.owner_id != actor.id or actor.id == 0:
        raise AppError(422, "ai_personal_required")
    if version is not None:
        check_version(connection, version)
    if mode == "CODEX_EXEC":
        codex_exec.require_available()
    try:
        payload = ConnectionInput(
            name=connection.name,
            base_url=connection.base_url,
            model=connection.model,
            reasoning_effort=connection.reasoning_effort,
            version=connection.version,
        )
    except ValidationError:
        raise AppError(422, "ai_parameters_rejected") from None
    return current_metadata(actor, db, mode), resolve_key(payload, connection)


def configuration_snapshot(config):
    return {
        k: config[k]
        for k in (
            "name",
            "model",
            "version",
            "call_mode",
            "reasoning_effort",
            "client_version",
            "execution_policy",
        )
        if k in config
    }


def _activate(payload, actor, db):
    mode, version = preference(actor, db)
    if payload.preference_version != version:
        raise AppError(409, "ai_preference_changed")
    connection = connection_for(actor, db, payload.call_mode)
    check_version(connection, payload.version)
    if connection is None:
        raise AppError(422, "ai_personal_required")
    if payload.call_mode == "CODEX_EXEC":
        codex_exec.require_available()
    row = db.get(AICallPreference, actor.id)
    if row is None:
        row = AICallPreference(owner_id=actor.id)
        db.add(row)
    row.call_mode, row.version = payload.call_mode, version + 1


def activate_configuration(payload: ActivationInput, actor, db):
    lock_changes(db, actor)
    _activate(payload, actor, db)
    db.commit()
    return read_configuration(actor, db)


def save_and_select(payload: ConfigurationInput, actor, db):
    lock_changes(db, actor)
    _, pref_version = preference(actor, db)
    if payload.preference_version != pref_version:
        raise AppError(409, "ai_preference_changed")
    if payload.activate and payload.call_mode == "CODEX_EXEC":
        codex_exec.require_available()
    connection = connection_for(actor, db, payload.call_mode)
    check_version(connection, payload.version)
    secret = resolve_key(payload, connection)
    changed = (
        connection is None
        or bool(payload.api_key.get_secret_value())
        or any(
            getattr(connection, key) != getattr(payload, key)
            for key in ("name", "base_url", "model", "reasoning_effort")
        )
    )
    if changed:
        if connection is None:
            connection = (
                AICLIConnection(owner_id=actor.id)
                if payload.call_mode == "CODEX_EXEC"
                else AIConnection(id=actor.id, owner_id=actor.id)
            )
            db.add(connection)
        for key in ("name", "base_url", "model", "reasoning_effort"):
            setattr(connection, key, getattr(payload, key))
        connection.encrypted_key = cipher().encrypt(secret.encode("ascii")).decode("ascii")
        connection.version = payload.version + 1
        if payload.call_mode == "RESPONSES_API":
            connection.updated_by = actor.id
        db.flush()
    if payload.activate:
        _activate(
            ActivationInput(
                call_mode=payload.call_mode,
                version=connection.version,
                preference_version=payload.preference_version,
            ),
            actor,
            db,
        )
    db.commit()
    result = read_configuration(actor, db)
    result["activated"] = payload.activate
    result["not_activated_reason"] = (
        codex_exec.runtime_status()["reason"]
        if payload.call_mode == "CODEX_EXEC" and not payload.activate
        else None
    )
    return result


def save_configuration(payload: ConnectionInput, actor: UserAccount, db: Session) -> dict:
    lock_changes(db, actor)
    connection_id = actor.id
    connection = db.get(AIConnection, connection_id)
    check_version(connection, payload.version)
    encrypted_key = (
        cipher().encrypt(resolve_key(payload, connection).encode("ascii")).decode("ascii")
    )
    if connection is None:
        connection = AIConnection(id=connection_id, owner_id=actor.id)
        db.add(connection)
    connection.name = payload.name
    connection.base_url = payload.base_url
    connection.model = payload.model
    connection.reasoning_effort = payload.reasoning_effort
    connection.encrypted_key = encrypted_key
    connection.version = payload.version + 1
    connection.updated_by = actor.id
    db.commit()
    return metadata(connection)


def test_configuration(
    payload: ConnectionInput | TestInput, actor: UserAccount, db: Session
) -> dict:
    mode = getattr(payload, "call_mode", "RESPONSES_API")
    connection = connection_for(actor, db, mode)
    check_version(connection, payload.version)
    key = resolve_key(payload, connection)
    if mode == "CODEX_EXEC":
        codex_exec.require_probe_available()
    # The reservation is committed before the external call; release only after it returns.
    reservation = reservations.reserve_test(db, actor, payload.base_url, key)
    try:
        ai_client.probe_model(
            payload.base_url, payload.model, key, payload.reasoning_effort, call_mode=mode
        )
    finally:
        reservations.release(db, reservation)
    return {"status": "success", "capability": "text", "call_mode": mode}


def discover_models(payload: ModelDiscoveryInput, actor: UserAccount, db: Session) -> dict:
    connection = db.get(AIConnection, actor.id)
    check_version(connection, payload.version)
    key = resolve_key(payload, connection)
    db.rollback()
    return {"models": responses.list_models(payload.base_url, key)}
