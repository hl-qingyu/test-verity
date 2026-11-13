import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import GitHubConnection, GitHubRepository, UserAccount
from app.integrations import github as client
from app.modules.github.schemas import ConnectionInput, ProbeInput, SaveInput
from app.security.secrets import credential_cipher


def token_cipher() -> Fernet:
    return credential_cipher("github_key_storage_unavailable")


def own_connection(
    db: Session, actor: UserAccount, connection_id: int, lock: bool = False
) -> GitHubConnection:
    query = select(GitHubConnection).where(
        GitHubConnection.id == connection_id, GitHubConnection.owner_id == actor.id
    )
    connection = db.scalar(query.with_for_update() if lock else query)
    if connection is None:
        raise AppError(404, "github_connection_not_found")
    return connection


def saved_token(connection: GitHubConnection) -> str:
    try:
        return token_cipher().decrypt(connection.encrypted_token.encode()).decode("ascii")
    except (InvalidToken, ValueError, UnicodeError):
        raise AppError(503, "github_key_storage_unavailable") from None


def resolve_input(payload: ConnectionInput, actor: UserAccount, db: Session) -> str:
    connection = own_connection(db, actor, payload.connection_id) if payload.connection_id else None
    if payload.version != (connection.version if connection else 0):
        raise AppError(409, "github_connection_changed")
    if payload.token.get_secret_value():
        return payload.token.get_secret_value()
    if connection is None:
        raise AppError(422, "github_token_required")
    if payload.kind is not None and (
        connection.kind != payload.kind
        or connection.resource_owner.lower() != payload.resource_owner.lower()
    ):
        raise AppError(422, "github_new_owner_requires_token")
    return saved_token(connection)


def fingerprint(payload: ConnectionInput, token: str, actor_id: int, binding: str) -> str:
    value = [
        actor_id,
        binding,
        payload.connection_id,
        payload.version,
        payload.kind,
        payload.resource_owner.lower() if payload.resource_owner else None,
        payload.token_type,
        token,
    ]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()


def connection_view(connection: GitHubConnection, db: Session) -> dict:
    return {
        "id": connection.id,
        "name": connection.name,
        "kind": connection.kind,
        "resource_owner": connection.resource_owner,
        "github_login": connection.github_login,
        "token_type": "fine_grained"
        if saved_token(connection).startswith("github_pat_")
        else "classic",
        "version": connection.version,
        "has_token": True,
        "api_url": "https://api.github.com",
        "repositories": [
            client.RepositoryView.model_validate(r).model_dump()
            for r in db.scalars(
                select(GitHubRepository)
                .where(GitHubRepository.connection_id == connection.id)
                .order_by(GitHubRepository.full_name)
            )
        ],
    }


def list_connections(actor: UserAccount, db: Session) -> list[dict]:
    return [
        connection_view(row, db)
        for row in db.scalars(
            select(GitHubConnection)
            .where(GitHubConnection.owner_id == actor.id)
            .order_by(GitHubConnection.id)
        )
    ]


def delete_connection(connection_id: int, version: int, actor: UserAccount, db: Session) -> dict:
    connection = own_connection(db, actor, connection_id, lock=True)
    if connection.version != version:
        raise AppError(409, "github_connection_changed")
    db.execute(delete(GitHubRepository).where(GitHubRepository.connection_id == connection.id))
    db.delete(connection)
    db.commit()
    return {"deleted": True}


def probe_connection(payload: ProbeInput, actor: UserAccount, db: Session, binding: str) -> dict:
    token = resolve_input(payload, actor, db)
    actual_type = "fine_grained" if token.startswith("github_pat_") else "classic"
    if payload.token_type and payload.token_type != actual_type:
        raise AppError(422, "github_token_type_mismatch")
    signature = fingerprint(payload, token, actor.id, binding)
    db.rollback()
    identity = client.github_get(token, "identity")
    if not isinstance(identity, dict) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", str(identity.get("login", ""))
    ):
        raise AppError(502, "github_invalid_response")
    login = identity["login"]
    if payload.kind == "personal" and login.lower() != payload.resource_owner.lower():
        raise AppError(422, "github_owner_mismatch")
    raw = client.github_get(token, "repositories", page=payload.page)
    if not isinstance(raw, list) or len(raw) > 100:
        raise AppError(502, "github_invalid_response")
    repos = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("owner"), dict):
            raise AppError(502, "github_invalid_response")
        if (
            payload.resource_owner is None
            or str(item["owner"].get("login", "")).lower() == payload.resource_owner.lower()
        ):
            repos.append(client.repository_view(item, payload.resource_owner, payload.kind))
    receipt = (
        token_cipher()
        .encrypt(
            json.dumps(
                {
                    "purpose": "github_discovery",
                    "signature": signature,
                    "login": login,
                    "ids": [repo.github_id for repo in repos],
                }
            ).encode()
        )
        .decode()
    )
    return {
        "github_login": login,
        "repositories": [repo.model_dump() for repo in repos],
        "receipt": receipt,
        "has_more": len(raw) == 100,
        "page": payload.page,
    }


def save_connection(payload: SaveInput, actor: UserAccount, db: Session, binding: str) -> dict:
    token = resolve_input(payload, actor, db)
    actual_type = "fine_grained" if token.startswith("github_pat_") else "classic"
    if payload.token_type and payload.token_type != actual_type:
        raise AppError(422, "github_token_type_mismatch")
    actor_id = actor.id
    signature = fingerprint(payload, token, actor_id, binding)
    permitted: set[int] = set()
    login = ""
    try:
        for receipt in payload.receipts:
            data = json.loads(token_cipher().decrypt(receipt.encode(), ttl=600))
            if data["purpose"] != "github_discovery" or data["signature"] != signature:
                raise ValueError("stale_receipt")
            login = data["login"]
            permitted.update(data["ids"])
    except (InvalidToken, ValueError, KeyError, TypeError):
        raise AppError(409, "github_retest_required") from None
    ids = set(payload.repository_ids)
    if not ids.issubset(permitted):
        raise AppError(403, "github_repository_not_allowed")
    db.rollback()
    # Bound remote I/O; no DB transaction is held while GitHub replies.
    with ThreadPoolExecutor(max_workers=4) as pool:
        repos = list(
            pool.map(
                lambda rid: client.check_repository(
                    token, rid, payload.resource_owner, payload.kind
                ),
                sorted(ids),
            )
        )
    db.refresh(actor, with_for_update=True)
    if actor.status != "ACTIVE":
        raise AppError(401, "not_authenticated")
    connection = (
        own_connection(db, actor, payload.connection_id, lock=True)
        if payload.connection_id
        else None
    )
    if payload.version != (connection.version if connection else 0):
        raise AppError(409, "github_connection_changed")
    if connection is None:
        connection = GitHubConnection(owner_id=actor_id)
        db.add(connection)
    connection.name = payload.name
    connection.kind = payload.kind or "automatic"
    connection.resource_owner = (
        payload.resource_owner.lower() if payload.resource_owner else login.lower()
    )
    connection.github_login = login
    connection.encrypted_token = token_cipher().encrypt(token.encode()).decode()
    connection.version = payload.version + 1
    db.flush()
    db.execute(delete(GitHubRepository).where(GitHubRepository.connection_id == connection.id))
    for repo in repos:
        db.add(GitHubRepository(connection_id=connection.id, **repo.model_dump()))
    db.commit()
    return connection_view(connection, db)
