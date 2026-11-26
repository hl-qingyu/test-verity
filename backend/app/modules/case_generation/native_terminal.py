"""Record-owned native CLI sessions scheduled by the existing worker."""

import copy
import logging
from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import select

from app.core.config import Settings
from app.core.errors import AppError
from app.db.models import (
    CaseGenerationBatch,
    CaseGenerationChatTurn,
    CaseGenerationRun,
    UserAccount,
)
from app.integrations import codex_terminal
from app.modules.ai import native_terminal as shared_terminal
from app.modules.ai.recovery import propagate_database_outage
from app.modules.ai.service import analysis_configuration, configuration_snapshot
from app.modules.case_generation import service, sources
from app.modules.documents import service as documents

logger = logging.getLogger(__name__)


def run_access(project_id, run_id, actor, db):
    documents.access(project_id, actor, db)
    run = db.execute(
        select(CaseGenerationRun.id, CaseGenerationRun.actor_id).where(
            CaseGenerationRun.id == run_id,
            CaseGenerationRun.project_id == project_id,
            CaseGenerationRun.deleted_at.is_(None),
        )
    ).first()
    if not run:
        raise AppError(404, "generation_not_found")
    return run


def authorized(project_id, run_id, actor, db, turn_id=None):
    run_access(project_id, run_id, actor, db)
    query = select(
        CaseGenerationChatTurn.id,
        CaseGenerationChatTurn.status,
        CaseGenerationChatTurn.error_code,
        CaseGenerationChatTurn.context["native_terminal"].label("terminal"),
    ).where(
        CaseGenerationChatTurn.run_id == run_id,
        CaseGenerationChatTurn.actor_id == actor.id,
        CaseGenerationChatTurn.context.has_key("native_terminal"),
    )
    if turn_id is not None:
        query = query.where(CaseGenerationChatTurn.id == turn_id)
    row = db.execute(query.order_by(CaseGenerationChatTurn.id.desc()).limit(1)).mappings().first()
    if turn_id is not None and not row:
        raise AppError(404, "generation_not_found")
    return row


def generation(project_id, run_id, actor, db, batch_id=None):
    run_access(project_id, run_id, actor, db)
    query = select(
        CaseGenerationBatch.id,
        CaseGenerationBatch.status,
        CaseGenerationBatch.error_code,
        CaseGenerationBatch.actor_id,
        CaseGenerationBatch.request_id,
        CaseGenerationBatch.ai_config["generation_terminal"].label("terminal"),
    ).where(
        CaseGenerationBatch.run_id == run_id,
        CaseGenerationBatch.ai_config.has_key("generation_terminal"),
    )
    if batch_id is not None:
        query = query.where(CaseGenerationBatch.id == batch_id)
    row = db.execute(query.order_by(CaseGenerationBatch.id.desc()).limit(1)).mappings().first()
    if row and row["actor_id"] != actor.id:
        raise AppError(403, "generation_owner_only")
    if batch_id is not None and row is None:
        raise AppError(404, "generation_not_found")
    return row


def view(row):
    if row is None:
        return None
    return shared_terminal.session_view(row, kind="generation" if "request_id" in row else "chat")


def current(project_id, run_id, actor, db):
    main = generation(project_id, run_id, actor, db)
    chat = authorized(project_id, run_id, actor, db)
    selected = main
    if (
        chat
        and main
        and chat["terminal"]["identity"] == main["terminal"]["identity"]
        and main["status"] not in service.ACTIVE
    ):
        selected = chat
    elif main is None:
        selected = chat
    return {
        "session": view(selected),
        "enabled": enabled_for(actor.id) and main is not None,
        "generation_bound": main is not None,
    }


def enabled_for(owner_id):
    users = Settings().ai_cli_terminal_user_ids
    return users is None or owner_id in users


def require_enabled(owner_id):
    if not enabled_for(owner_id):
        raise AppError(403, "generation_terminal_permission_required")


def binding(project_id, run_id, turn_id, actor, db):
    row = authorized(project_id, run_id, actor, db, turn_id)
    return {
        "identity": row["terminal"]["identity"],
        "execution": turn_id,
        "owner_id": actor.id,
        "session": view(row),
        "readonly": not row["terminal"].get("generation_bound", False),
    }


def generation_binding(project_id, run_id, batch_id, actor, db):
    row = generation(project_id, run_id, actor, db, batch_id)
    return {
        "identity": row["terminal"]["identity"],
        # Batch and follow-up chat identifiers use separate database sequences.
        "execution": row["terminal"]["execution"],
        "owner_id": actor.id,
        "session": view(row),
        "readonly": False,
    }


bound_output = shared_terminal.bound_output


def bound_input(bound, payload):
    shared_terminal.write_command(bound, payload, enabled=enabled_for(bound["owner_id"]))


def start(project_id, run_id, payload, actor, db):
    require_enabled(actor.id)
    run = service.own(project_id, run_id, actor, db, True)
    main = generation(project_id, run_id, actor, db)
    if main is None:
        raise AppError(409, "generation_terminal_not_started")
    if not payload.resume:
        raise AppError(409, "generation_terminal_bound_to_batch")
    if main["status"] in service.ACTIVE:
        return {"session": view(main)}
    previous = authorized(project_id, run_id, actor, db)
    if (
        previous
        and previous["terminal"]["identity"] == main["terminal"]["identity"]
        and previous["status"] in service.ACTIVE
    ):
        return {"session": view(previous)}
    replay = db.scalar(
        select(CaseGenerationChatTurn).where(
            CaseGenerationChatTurn.run_id == run_id,
            CaseGenerationChatTurn.request_id == str(payload.request_id),
        )
    )
    if replay:
        if replay.actor_id != actor.id or "native_terminal" not in replay.context:
            raise AppError(409, "generation_request_conflict")
        return {
            "session": {"id": replay.id, "status": replay.status, "error_code": replay.error_code}
        }
    batch = db.get(CaseGenerationBatch, main["id"])
    config, _ = analysis_configuration(actor, db, batch.ai_config)
    if config.get("call_mode") != "CODEX_EXEC":
        raise AppError(422, "generation_cli_mode_required")
    if db.scalar(
        select(CaseGenerationChatTurn.id).where(
            CaseGenerationChatTurn.run_id == run_id,
            CaseGenerationChatTurn.function_key == "",
            CaseGenerationChatTurn.status.in_(service.ACTIVE),
        )
    ):
        raise AppError(409, "generation_chat_busy")
    sources.recheck(project_id, run.metadata_snapshot, actor, db)
    identity = main["terminal"]["identity"]
    thread_id = codex_terminal.history_thread(identity, main["terminal"]["execution"])
    prior = (
        db.get(CaseGenerationChatTurn, previous["id"])
        if previous and previous["terminal"]["identity"] == main["terminal"]["identity"]
        else None
    )
    if thread_id:
        context = {"native_terminal": {"identity": identity, "thread_id": thread_id}}
        config_snapshot = configuration_snapshot(config)
    elif prior:
        analysis_configuration(actor, db, prior.ai_config)
        context = copy.deepcopy(prior.context)
        config_snapshot = copy.deepcopy(prior.ai_config)
    else:
        history = []
        for turn in db.scalars(
            select(CaseGenerationChatTurn)
            .where(
                CaseGenerationChatTurn.run_id == run_id,
                CaseGenerationChatTurn.actor_id == actor.id,
                CaseGenerationChatTurn.status == "COMPLETED",
            )
            .order_by(CaseGenerationChatTurn.id)
        ):
            if "native_terminal" not in turn.context:
                history += [
                    {"role": "user", "content": turn.question},
                    {"role": "assistant", "content": turn.answer},
                ]
        context = {
            "native_terminal": {"identity": main["terminal"]["identity"]},
            "inputs": [copy.deepcopy(b.input_snapshot) for b in service.batches(run, db)],
            "reports": [copy.deepcopy(r) for _, r in service.reports(run, db)],
            "skill": copy.deepcopy(run.metadata_snapshot.get("skill", {})),
            "messages": history,
        }
        config_snapshot = configuration_snapshot(config)
    context["native_terminal"].update(
        resume=True, generation_bound=True, rows=payload.rows, cols=payload.cols
    )
    row = CaseGenerationChatTurn(
        run_id=run_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        function_key="",
        finding_key="",
        question="原生 CLI 终端会话",
        context=context,
        ai_config=config_snapshot,
    )
    db.add(row)
    db.commit()
    return {"session": {"id": row.id, "status": row.status, "error_code": row.error_code}}


def read(project_id, run_id, turn_id, cursor, actor, db):
    row = authorized(project_id, run_id, actor, db, turn_id)
    result = codex_terminal.output(row["terminal"]["identity"], turn_id, cursor)
    return {**result, "session": view(row)}


def write(project_id, run_id, turn_id, payload, actor, db):
    require_enabled(actor.id)
    row = authorized(project_id, run_id, actor, db, turn_id)
    if not row["terminal"].get("generation_bound"):
        raise AppError(409, "generation_terminal_not_started")
    if row["status"] not in service.ACTIVE:
        raise AppError(409, "generation_terminal_closed")
    command = payload.model_dump(exclude_none=True)
    codex_terminal.put_command(row["terminal"]["identity"], turn_id, command)
    return {"accepted": True}


def execute(turn_id, factory, *, save_completed_turns):
    try:
        with factory() as db:
            turn = db.get(CaseGenerationChatTurn, turn_id)
            if turn is None or turn.status != "RUNNING":
                return
            context = copy.deepcopy(turn.context)
            if not context["native_terminal"].get("generation_bound"):
                raise AppError(409, "generation_terminal_not_started")
            actor_id, run_id = turn.actor_id, turn.run_id
            require_enabled(actor_id)
            actor = db.get(UserAccount, actor_id)
            run = db.get(CaseGenerationRun, run_id)
            project_id = run.project_id
            service.own(project_id, run_id, actor, db)
            sources.recheck(project_id, run.metadata_snapshot, actor, db)
            config, key = analysis_configuration(actor, db, turn.ai_config)
        spec = context["native_terminal"]
        last = 0.0
        cursor = 0
        finished = set()

        def check(force=False):
            nonlocal last, cursor
            if not force and monotonic() - last < 1:
                return
            last = monotonic()
            with factory() as db:
                actor = db.get(UserAccount, actor_id)
                row = authorized(project_id, run_id, actor, db, turn_id)
                if row["status"] != "RUNNING":
                    raise AppError(409, "generation_chat_cancelled")
                analysis_configuration(actor, db, config)
                try:
                    events, cursor = codex_terminal.turn_events(spec["identity"], turn_id, cursor)
                    finished.update(
                        (event["thread_id"], event["turn_id"])
                        for event in events
                        if event["method"] == "turn/completed"
                        and event.get("status") == "completed"
                        and event.get("thread_id")
                        and event.get("turn_id")
                    )
                    if finished:
                        finished.difference_update(
                            save_completed_turns(
                                project_id,
                                run_id,
                                spec["identity"],
                                finished,
                                actor,
                                db,
                                execution_id=turn_id,
                            )
                        )
                except (AppError, OSError, ValueError):
                    logger.warning("Could not save native generation results for chat %s", turn_id)
                    finished.clear()

        if not spec["resume"]:
            raise AppError(409, "generation_terminal_not_started")
        shared_terminal.resume_session(
            config,
            key,
            {**spec, "execution": turn_id},
            check,
            legacy_context={k: v for k, v in context.items() if k != "native_terminal"}
            if not spec.get("thread_id")
            else None,
            legacy_instructions=context.get("skill", {}).get("instructions", ""),
        )
        with factory() as db:
            turn = db.get(CaseGenerationChatTurn, turn_id, with_for_update=True)
            if turn.status == "RUNNING":
                turn.status, turn.updated_at = "COMPLETED", datetime.now(UTC)
                db.commit()
    except Exception as exc:
        propagate_database_outage(exc)
        code = exc.detail if isinstance(exc, AppError) else "generation_terminal_failed"
        with factory() as db:
            turn = db.get(CaseGenerationChatTurn, turn_id, with_for_update=True)
            if turn and turn.status == "RUNNING":
                turn.status, turn.error_code, turn.updated_at = "FAILED", code, datetime.now(UTC)
                db.commit()
