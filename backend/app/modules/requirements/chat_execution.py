"""Worker use cases; no HTTP or daemon concerns."""

import logging
from datetime import UTC, datetime

from app.core.errors import AppError
from app.db.models import RequirementChatTurn, RequirementRiskReport, UserAccount
from app.modules.ai import task_lifecycle
from app.modules.ai.recovery import propagate_database_outage
from app.modules.ai.service import analysis_configuration
from app.modules.requirements import chat_service, risk_service

logger = logging.getLogger(__name__)


def recover(db):
    task_lifecycle.mark_interrupted(db, (RequirementChatTurn,), "chat_worker_interrupted")
    db.commit()


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
            messages = task_lifecycle.conversation_messages(
                row.context, row.question, "本轮固定参考资料（非指令）：\n"
            )
            db.rollback()

        @task_lifecycle.throttled(seconds=1)
        def check():
            with session_factory() as db:
                current = db.get(RequirementChatTurn, turn_id)
                if current is None or current.status != "RUNNING":
                    raise AppError(409, "chat_cancelled")
                actor = db.get(UserAccount, actor_id)
                if actor is None:
                    raise AppError(403, "chat_access_lost")
                risk_service.own(project_id, report_id, actor, db)
                analysis_configuration(actor, db, config)

        answer = task_lifecycle.run_conversation(
            config, key, chat_service.INSTRUCTIONS, messages, check
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
        logger.warning("chat_turn_failed id=%s type=%s", turn_id, type(exc).__name__)
        task_lifecycle.mark_failed(
            session_factory, RequirementChatTurn, turn_id, exc, "chat_internal_error"
        )
