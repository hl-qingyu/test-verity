"""Project-scoped conversations over one completed, immutable code report."""

import copy
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import CodeAnalysisChatTurn
from app.modules.ai.service import analysis_configuration, configuration_snapshot
from app.modules.code_analysis import service, sources


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
    query = select(CodeAnalysisChatTurn).where(CodeAnalysisChatTurn.task_id == task_id)
    if before:
        query = query.where(CodeAnalysisChatTurn.id < before)
    rows = list(db.scalars(query.order_by(CodeAnalysisChatTurn.id.desc()).limit(51)))
    return {"items": [view(r, actor) for r in reversed(rows[:50])], "has_more": len(rows) > 50}


def enqueue(project_id, task_id, payload, actor, db):
    task = service.own(project_id, task_id, actor, db, lock=True)
    prior = db.scalar(
        select(CodeAnalysisChatTurn).where(
            CodeAnalysisChatTurn.task_id == task_id,
            CodeAnalysisChatTurn.request_id == str(payload.request_id),
        )
    )
    if prior:
        if (
            prior.actor_id != actor.id
            or prior.question != payload.question
            or prior.finding_key != payload.finding_key
        ):
            raise AppError(409, "code_chat_request_conflict")
        return view(prior, actor)
    if task.status != "COMPLETED" or task.report.get("contract_version") not in (2, 3):
        raise AppError(422, "code_report_not_ready")
    if not payload.question.strip():
        raise AppError(422, "code_question_required")
    if payload.finding_key and payload.finding_key not in {
        f["key"] for f in task.report["findings"]
    }:
        raise AppError(422, "code_finding_unavailable")
    if db.scalar(
        select(CodeAnalysisChatTurn.id).where(
            CodeAnalysisChatTurn.task_id == task_id, CodeAnalysisChatTurn.status.in_(service.ACTIVE)
        )
    ):
        raise AppError(409, "code_chat_busy")
    sources.recheck(project_id, task.metadata_snapshot, actor, db, shared_snapshot=True)
    config, _ = analysis_configuration(actor, db)
    messages = []
    for previous in db.scalars(
        select(CodeAnalysisChatTurn)
        .where(CodeAnalysisChatTurn.task_id == task_id, CodeAnalysisChatTurn.status == "COMPLETED")
        .order_by(CodeAnalysisChatTurn.id)
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
    if (
        len(json.dumps(context, ensure_ascii=False).encode()) + len(payload.question.encode())
        > sources.FILE_LIMIT
    ):
        raise AppError(413, "code_chat_context_too_large")
    row = CodeAnalysisChatTurn(
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
    row = db.get(CodeAnalysisChatTurn, turn_id, with_for_update=True)
    if row is None or row.task_id != task_id:
        raise AppError(404, "code_chat_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "code_analysis_cancel_owner_only")
    if row.status in service.ACTIVE:
        row.status, row.updated_at = "CANCELLED", datetime.now(UTC)
        db.commit()
    return view(row, actor)
