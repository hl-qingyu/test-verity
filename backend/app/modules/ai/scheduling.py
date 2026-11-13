"""Budget-aware claiming, parameterized by the existing worker's fixed task registry."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import UserAccount
from app.modules.ai import reservations
from app.modules.ai.service import analysis_configuration


def claim(db, model, scheduler_id, *, parent=None, parent_key=None, on_claim=None):
    query = select(model.id).where(model.status == "QUEUED")
    if hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    if parent is not None:
        query = query.join(parent, parent.id == getattr(model, parent_key)).where(
            parent.deleted_at.is_(None), parent.status != "CANCELLED"
        )
    # Inspect other users when one user's head is budget-blocked. No rows become RUNNING early.
    candidates = list(db.scalars(query.order_by(model.id)))
    db.rollback()
    for key in candidates:
        reservations.lock_budget(db)
        if parent is not None:
            parent_id = db.scalar(select(getattr(model, parent_key)).where(model.id == key))
            root = db.get(
                parent, parent_id, with_for_update={"skip_locked": True}, populate_existing=True
            )
            if root is None or root.deleted_at is not None or root.status == "CANCELLED":
                db.rollback()
                continue
        row = db.scalar(
            select(model)
            .where(model.id == key, model.status == "QUEUED")
            .with_for_update(skip_locked=True)
        )
        if row is None:
            db.rollback()
            continue
        actor = db.get(UserAccount, row.actor_id)
        try:
            if actor is None:
                raise AppError(401, "not_authenticated")
            config, secret = analysis_configuration(actor, db, row.ai_config)
        except AppError as exc:
            row.status, row.error_code, row.updated_at = "FAILED", exc.detail, datetime.now(UTC)
            if on_claim:
                on_claim(db, row, False)
            db.commit()
            continue
        try:
            reservation = reservations.reserve(
                db,
                actor.id,
                config["base_url"],
                secret,
                kind=model.__tablename__,
                task_id=key,
                request_id=row.request_id,
                scheduler_id=scheduler_id,
            )
        except AppError as exc:
            row.status, row.error_code, row.updated_at = "FAILED", exc.detail, datetime.now(UTC)
            if on_claim:
                on_claim(db, row, False)
            db.commit()
            continue
        if reservation is None:
            db.rollback()
            continue
        row.status, row.updated_at = "RUNNING", datetime.now(UTC)
        if on_claim:
            on_claim(db, row, True)
        db.commit()
        return key, reservation
    return None
