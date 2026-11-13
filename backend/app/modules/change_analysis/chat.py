"""Project-scoped conversations over one completed, immutable code report."""

import copy
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import ChangeAnalysisChatTurn
from app.modules.ai.service import analysis_configuration, configuration_snapshot
from app.modules.change_analysis import service, sources


def view(turn, actor):
    return {
        "id": turn.id,
        "task_id": turn.task_id,
        "actor_id": turn.actor_id,
        "finding_key": turn.finding_key,
        "question": turn.question,
        "answer": turn.answer,
        "status": turn.status,
        "error_code": turn.error_code,
        "ai": turn.ai_config,
        "created_at": turn.created_at.isoformat(),
        "can_cancel": turn.actor_id == actor.id and turn.status in service.ACTIVE,
    }


def listing(project_id, task_id, actor, db, before=None):
    service.own(project_id, task_id, actor, db)
    query = select(ChangeAnalysisChatTurn).where(ChangeAnalysisChatTurn.task_id == task_id)
    if before:
        query = query.where(ChangeAnalysisChatTurn.id < before)
    rows = list(db.scalars(query.order_by(ChangeAnalysisChatTurn.id.desc()).limit(51)))
    return {"items": [view(r, actor) for r in reversed(rows[:50])], "has_more": len(rows) > 50}


def enqueue(project_id, task_id, payload, actor, db):
    task = service.own(project_id, task_id, actor, db, lock=True)
    prior = db.scalar(
        select(ChangeAnalysisChatTurn).where(
            ChangeAnalysisChatTurn.task_id == task_id,
            ChangeAnalysisChatTurn.request_id == str(payload.request_id),
        )
    )
    if prior:
        if (
            prior.actor_id != actor.id
            or prior.question != payload.question
            or prior.finding_key != payload.finding_key
        ):
            raise AppError(409, "change_chat_request_conflict")
        return view(prior, actor)
    if task.status != "COMPLETED" or task.report.get("contract_version") != 2:
        raise AppError(422, "change_report_not_ready")
    if not payload.question.strip():
        raise AppError(422, "change_question_required")
    if payload.finding_key and payload.finding_key not in service.items(task.report):
        raise AppError(422, "change_finding_unavailable")
    if db.scalar(
        select(ChangeAnalysisChatTurn.id).where(
            ChangeAnalysisChatTurn.task_id == task_id,
            ChangeAnalysisChatTurn.status.in_(service.ACTIVE),
        )
    ):
        raise AppError(409, "change_chat_busy")
    sources.recheck(project_id, task.metadata_snapshot, actor, db, shared_snapshot=True)
    config, _ = analysis_configuration(actor, db)
    messages = []
    for previous in db.scalars(
        select(ChangeAnalysisChatTurn)
        .where(
            ChangeAnalysisChatTurn.task_id == task_id, ChangeAnalysisChatTurn.status == "COMPLETED"
        )
        .order_by(ChangeAnalysisChatTurn.id)
    ):
        messages.extend(
            [
                {"role": "user", "content": previous.question},
                {"role": "assistant", "content": previous.answer},
            ]
        )
    context = {
        "task_id": task_id,
        "revision": task.revision,
        "finding_key": payload.finding_key,
        "input": copy.deepcopy(task.input_snapshot),
        "report": copy.deepcopy(task.report),
        "handling": copy.deepcopy(task.handling),
        "messages": messages,
    }
    row = ChangeAnalysisChatTurn(
        task_id=task_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        question=payload.question,
        finding_key=payload.finding_key,
        context=context,
        ai_config=configuration_snapshot(config),
    )
    db.add(row)
    db.commit()
    return view(row, actor)


def cancel(project_id, task_id, turn_id, actor, db):
    service.own(project_id, task_id, actor, db, lock=True)
    row = db.get(ChangeAnalysisChatTurn, turn_id, with_for_update=True)
    if row is None or row.task_id != task_id:
        raise AppError(404, "change_chat_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "change_analysis_cancel_owner_only")
    if row.status in service.ACTIVE:
        row.status, row.updated_at = "CANCELLED", datetime.now(UTC)
        db.commit()
    return view(row, actor)
