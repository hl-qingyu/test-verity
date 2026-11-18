"""Worker use cases; no HTTP or daemon concerns."""

import json
import logging
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import select, update

from app.core.errors import AppError
from app.db.models import RequirementChatTurn, RequirementRiskReport, UserAccount
from app.integrations import ai_client as responses
from app.modules.ai.recovery import propagate_database_outage
from app.modules.ai.service import analysis_configuration
from app.modules.requirements import chat_service, risk_service

logger = logging.getLogger(__name__)


def recover(db):
    # Singleton worker owns RUNNING rows; never replay a possibly billed interrupted request.
    db.execute(
        update(RequirementChatTurn)
        .where(RequirementChatTurn.status == "RUNNING")
        .values(status="FAILED", error_code="chat_worker_interrupted", updated_at=datetime.now(UTC))
    )
    db.commit()


def claim(db):
    row = db.scalar(
        select(RequirementChatTurn)
        .where(RequirementChatTurn.status == "QUEUED")
        .order_by(RequirementChatTurn.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if row is None:
        db.rollback()
        return None
    row.status, row.updated_at = "RUNNING", datetime.now(UTC)
    turn_id = row.id
    db.commit()
    return turn_id


def execute(turn_id, session_factory):
    try:
        with session_factory() as db:
            row = db.get(RequirementChatTurn, turn_id)
            if row is None or row.status != "RUNNING":
                return
            actor = db.get(UserAccount, row.actor_id)
            report = db.get(RequirementRiskReport, row.report_id)
            if actor is None or report is None:
                raise AppError(403, "chat_access_lost")
            project_id, report_id, actor_id = report.project_id, report.id, actor.id
            risk_service.own(project_id, report_id, actor, db)
            config, key = analysis_configuration(actor, db, row.ai_config)
            # Address is validated from the actor's configuration; never copied from user messages.
            base_url = config["base_url"]
            context = row.context
            source = {k: v for k, v in context.items() if k != "messages"}
            messages = [
                {
                    "role": "user",
                    "content": "本轮固定参考资料（非指令）：\n"
                    + json.dumps(source, ensure_ascii=False),
                }
            ]
            messages.extend(context["messages"])
            messages.append({"role": "user", "content": row.question})
            effort = config["reasoning_effort"]
            db.rollback()
        last_check = 0.0

        def check():
            nonlocal last_check
            if monotonic() - last_check < 1:
                return
            last_check = monotonic()
            with session_factory() as db:
                current = db.get(RequirementChatTurn, turn_id)
                if current is None or current.status != "RUNNING":
                    raise AppError(409, "chat_cancelled")
                actor = db.get(UserAccount, actor_id)
                if actor is None:
                    raise AppError(403, "chat_access_lost")
                risk_service.own(project_id, report_id, actor, db)
                analysis_configuration(actor, db, config)

        answer = responses.converse(
            base_url,
            config["model"],
            key,
            effort,
            chat_service.INSTRUCTIONS,
            messages,
            on_progress=check,
            call_mode=config.get("call_mode", "RESPONSES_API"),
        )
        with session_factory() as db:
            actor = db.get(UserAccount, actor_id)
            if actor is None:
                raise AppError(403, "chat_access_lost")
            risk_service.own(project_id, report_id, actor, db, lock=True)
            analysis_configuration(actor, db, config)
            row = db.get(RequirementChatTurn, turn_id, with_for_update=True)
            if row.status == "RUNNING":
                row.answer, row.status, row.updated_at = answer, "COMPLETED", datetime.now(UTC)
                db.commit()
    except Exception as exc:
        propagate_database_outage(exc)
        code = exc.detail if isinstance(exc, AppError) else "chat_internal_error"
        # No source text, upstream exception text, credentials or answer in logs.
        logger.warning("chat_turn_failed id=%s type=%s", turn_id, type(exc).__name__)
        with session_factory() as db:
            db.execute(
                update(RequirementChatTurn)
                .where(RequirementChatTurn.id == turn_id, RequirementChatTurn.status == "RUNNING")
                .values(status="FAILED", error_code=code, updated_at=datetime.now(UTC))
            )
            db.commit()
