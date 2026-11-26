"""Shared worker transitions and model conversation assembly."""

import json
from datetime import UTC, datetime
from functools import wraps
from time import monotonic

from sqlalchemy import update

from app.core.errors import AppError
from app.integrations import ai_client
from app.modules.ai.recovery import propagate_database_outage


def mark_interrupted(db, models, code, requeue=()):
    now = datetime.now(UTC)
    for model in models:
        db.execute(
            update(model)
            .where(model.status == "RUNNING")
            .values(status="FAILED", error_code=code, updated_at=now)
        )
    for model in requeue:
        db.execute(
            update(model).where(model.status == "RUNNING").values(status="QUEUED", updated_at=now)
        )


def mark_failed(factory, model, key, exc, fallback, extra=None):
    propagate_database_outage(exc)
    code = exc.detail if isinstance(exc, AppError) and isinstance(exc.detail, str) else fallback
    with factory() as db:
        db.execute(
            update(model)
            .where(model.id == key, model.status == "RUNNING")
            .values(status="FAILED", error_code=code, updated_at=datetime.now(UTC), **(extra or {}))
        )
        db.commit()


def throttled(fn=None, *, seconds):
    if fn is None:
        return lambda callback: throttled(callback, seconds=seconds)
    last_check = float("-inf")

    @wraps(fn)
    def check(*, force=False):
        nonlocal last_check
        now = monotonic()
        if force or now - last_check >= seconds:
            last_check = now
            return fn()

    return check


def conversation_messages(context, question, prefix):
    references = {key: value for key, value in context.items() if key != "messages"}
    return [
        {"role": "user", "content": prefix + json.dumps(references, ensure_ascii=False)},
        *context["messages"],
        {"role": "user", "content": question},
    ]


def run_conversation(config, secret, instructions, messages, check):
    return ai_client.converse(
        config["base_url"],
        config["model"],
        secret,
        config["reasoning_effort"],
        instructions,
        messages,
        on_progress=check,
        call_mode=config.get("call_mode", "RESPONSES_API"),
    )
