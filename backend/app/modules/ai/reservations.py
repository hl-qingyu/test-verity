"""Short PostgreSQL transactions coordinate API tests and the singleton scheduler."""

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import func, select, text, update

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import AICallReservation
from app.integrations.process_identity import current_identity, proven_exited

BUDGET_LOCK = 2026111143


def credential_group(base_url, key):
    secret = Settings().ai_encryption_key.get_secret_value()
    if not secret:
        raise AppError(503, "ai_key_storage_unavailable")
    return hmac.new(
        secret.encode(),
        ((urlsplit(base_url).hostname or "").lower() + "\0" + key).encode(),
        hashlib.sha256,
    ).hexdigest()


def lock_budget(db):
    db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": BUDGET_LOCK})


def recover_exited(db):
    lock_budget(db)
    for row in db.scalars(select(AICallReservation).where(AICallReservation.state == "HELD")):
        if proven_exited(row.process_identity):
            row.state, row.released_at = "INTERRUPTED", datetime.now(UTC)
    db.flush()


def reserve(db, owner_id, base_url, key, *, kind, task_id, request_id, scheduler_id):
    lock_budget(db)
    if (
        task_id is not None
        and db.scalar(
            select(AICallReservation.id).where(
                AICallReservation.kind == kind,
                AICallReservation.task_id == task_id,
                AICallReservation.request_id == request_id,
            )
        )
        is not None
    ):
        raise AppError(409, "ai_call_already_attempted")
    group = credential_group(base_url, key)
    settings = Settings()
    held = AICallReservation.state == "HELD"
    for condition, limit in (
        (True, settings.ai_max_concurrent),
        (AICallReservation.owner_id == owner_id, settings.ai_max_per_user),
        (AICallReservation.credential_group == group, settings.ai_max_per_credential),
    ):
        if (
            db.scalar(select(func.count()).select_from(AICallReservation).where(held, condition))
            >= limit
        ):
            return None
    row = AICallReservation(
        id=str(uuid4()),
        owner_id=owner_id,
        kind=kind,
        task_id=task_id,
        request_id=request_id,
        credential_group=group,
        scheduler_id=scheduler_id,
        process_identity=current_identity(),
        state="HELD",
    )
    db.add(row)
    db.flush()
    return row.id


def reserve_test(db, actor, base_url, key):
    recover_exited(db)
    reservation = reserve(
        db,
        actor.id,
        base_url,
        key,
        kind="CONNECTION_TEST",
        task_id=None,
        request_id=str(uuid4()),
        scheduler_id=str(uuid4()),
    )
    if reservation is None:
        db.rollback()
        raise AppError(409, "ai_call_busy")
    db.commit()
    return reservation


def release(db, reservation, *, interrupted=False):
    db.rollback()
    db.execute(
        update(AICallReservation)
        .where(
            AICallReservation.id == reservation,
            AICallReservation.state == "HELD",
            AICallReservation.process_identity == current_identity(),
        )
        .values(state="INTERRUPTED" if interrupted else "RELEASED", released_at=datetime.now(UTC))
    )
    db.commit()
