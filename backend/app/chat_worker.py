"""Independent single-process analysis/conversation worker. python -m app.chat_worker"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Event
from uuid import uuid4

from sqlalchemy import Engine, select, text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import configure_logging
from app.db import models
from app.db.scheduler import SchedulerConnection
from app.db.session import get_engine, get_scheduler_engine
from app.integrations import cli_results
from app.integrations.call_control import execution_scope
from app.modules.ai import reservations, scheduling
from app.modules.ai.recovery import DATABASE_ERRORS
from app.modules.case_analysis import apply as case_analysis_apply
from app.modules.case_analysis import execution as case_analysis_execution
from app.modules.case_generation import apply as generation_apply
from app.modules.case_generation import execution as generation_execution
from app.modules.case_generation import native_results as generation_native_results
from app.modules.change_analysis import execution as change_analysis_execution
from app.modules.code_analysis import execution as code_analysis_execution
from app.modules.requirements import chat_execution, risk_analysis_execution
from app.modules.skills import execution as skills_execution

SCHEDULER_LOCK_ID = 2026091725


def main():
    configure_logging("chat-worker")
    logger = logging.getLogger("app.chat_worker")
    engine = get_engine()
    try:
        while True:
            try:
                _run(engine, logger)
                logger.warning("analysis_chat_worker_waiting_for_lock")
            except (OperationalError, InterfaceError) as exc:
                logger.warning(
                    "analysis_chat_worker_database_unavailable type=%s", type(exc).__name__
                )
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("requirement_chat_worker_stopped")


def _run(engine: Engine, logger: logging.Logger) -> None:
    with SchedulerConnection(get_scheduler_engine()) as lock:
        try:
            if not lock.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULER_LOCK_ID}
            ):
                return
            lock.commit()

            def factory():
                return Session(engine, expire_on_commit=False)

            with factory() as db:
                reservations.recover_exited(db)
                unknown = db.scalar(
                    select(models.AICallReservation.id)
                    .where(
                        models.AICallReservation.state == "HELD",
                        models.AICallReservation.kind != "CONNECTION_TEST",
                    )
                    .limit(1)
                )
                db.commit()
                if unknown is not None:
                    logger.warning("analysis_chat_worker_waiting_for_live_calls")
                    return

            _restore_cli_results(factory, logger)
            with factory() as db:
                chat_execution.recover(db)
            with factory() as db:
                risk_analysis_execution.recover(db)
            with factory() as db:
                code_analysis_execution.recover(db)
            with factory() as db:
                change_analysis_execution.recover(db)
            with factory() as db:
                generation_execution.recover(db)
            with factory() as db:
                case_analysis_execution.recover(db)
            with factory() as db:
                skills_execution.recover(db)
            logger.info("analysis_chat_worker_ready")
            _schedule(lock, factory, logger)

        finally:
            # Close the owning DB session; never reconnect just to unlock a lost session.
            lock.invalidate()


def _generation_claim(db, row, running):
    run = db.get(models.CaseGenerationRun, row.run_id)
    if running:
        run.status, run.updated_at = "RUNNING", datetime.now(UTC)
        generation_execution.update_attempt(
            row, {"phase": "preparing"}, started_at=datetime.now(UTC).isoformat()
        )
    else:
        generation_execution.refresh_run(db, run)


def _registry():
    return (
        (models.SkillChatTurn, skills_execution.execute, {}),
        (models.CaseAnalysisRun, case_analysis_execution.execute, {}),
        (models.CaseAnalysisChatTurn, case_analysis_execution.execute_chat, {}),
        (models.RequirementRiskAnalysis, risk_analysis_execution.execute, {}),
        (models.CodeAnalysisTask, code_analysis_execution.execute, {}),
        (models.ChangeAnalysisTask, change_analysis_execution.execute, {}),
        (
            models.CaseGenerationBatch,
            generation_execution.execute,
            {
                "parent": models.CaseGenerationRun,
                "parent_key": "run_id",
                "on_claim": _generation_claim,
            },
        ),
        (models.CaseGenerationChatTurn, generation_native_results.execute_chat, {}),
        (models.RequirementChatTurn, chat_execution.execute, {}),
        (models.ChangeAnalysisChatTurn, change_analysis_execution.execute_chat, {}),
        (models.CodeAnalysisChatTurn, code_analysis_execution.execute_chat, {}),
    )


def _run_task(model, execute, key, reservation, factory, stop, logger, *, saved_only=False):
    def configuration():
        with factory() as db:
            row = db.get(model, key)
            return bool(row and row.ai_config.get("call_mode") == "CODEX_EXEC")

    cli = saved_only
    while True:
        try:
            cli = configuration() if not saved_only else True
            break
        except DATABASE_ERRORS:
            logger.warning(
                "analysis_task_waiting_for_database kind=%s id=%s", model.__tablename__, key
            )
            if stop.wait(5):
                return
    if saved_only and not cli_results.pending(reservation):
        return
    try:
        with execution_scope(
            stop,
            receipt=reservation if cli else None,
            transient_error=lambda error: isinstance(error, DATABASE_ERRORS),
        ):
            while True:
                try:
                    execute(key, factory)
                    if cli:
                        cli_results.acknowledge(reservation)
                    break
                except DATABASE_ERRORS:
                    if not cli:
                        raise
                    logger.warning(
                        "cli_result_waiting_for_database kind=%s id=%s", model.__tablename__, key
                    )
                    if stop.wait(5):
                        return
    finally:
        # A reservation is retained until execution and result delivery have ended.
        while True:
            try:
                with factory() as db:
                    reservations.release(db, reservation, interrupted=stop.is_set())
                break
            except DATABASE_ERRORS:
                if stop.wait(5):
                    break


def _restore_cli_results(factory, logger):
    registry = {model.__tablename__: (model, execute) for model, execute, _ in _registry()}
    with factory() as db:
        saved = [
            (row.id, row.kind, row.task_id, row.request_id, row.owner_id)
            for row in db.scalars(
                select(models.AICallReservation).where(
                    models.AICallReservation.state.in_(("INTERRUPTED", "RELEASED"))
                )
            )
            if row.kind in registry and cli_results.pending(row.id)
        ]
    for identity, kind, key, request_id, owner_id in saved:
        model, execute = registry[kind]
        with factory() as db:
            row = db.get(model, key)
            eligible = bool(
                row
                and row.status == "RUNNING"
                and row.request_id == request_id
                and row.actor_id == owner_id
            )
        if eligible:
            logger.info("cli_saved_result_delivery kind=%s id=%s", kind, key)
            _run_task(model, execute, key, identity, factory, Event(), logger, saved_only=True)
        else:
            cli_results.acknowledge(identity)


def _schedule(lock, factory, logger):
    stop = Event()
    scheduler_id = str(uuid4())
    slots = max(1, Settings().ai_max_concurrent)
    registry = _registry()
    engine, current = lock.engine, lock

    active = set()
    with ThreadPoolExecutor(max_workers=slots, thread_name_prefix="analysis") as pool:
        try:
            while True:
                try:
                    if current is None:
                        current = SchedulerConnection(engine)
                        if not current.scalar(
                            text("SELECT pg_try_advisory_lock(:key)"), {"key": SCHEDULER_LOCK_ID}
                        ):
                            current.invalidate()
                            current.close()
                            current = None
                            stop.wait(5)
                            continue
                        current.commit()
                        logger.info("analysis_scheduler_database_reconnected")
                    # Reacquire the singleton before claiming, without touching active tasks.
                    owned = current.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                            "AND pid=pg_backend_pid() AND classid=0 "
                            "AND objid=CAST(:key AS oid) AND granted)"
                        ),
                        {"key": SCHEDULER_LOCK_ID},
                    )
                    current.commit()
                    if not owned:
                        raise OperationalError(None, None, RuntimeError("scheduler_lock_lost"))
                    for future in tuple(active):
                        if future.done():
                            active.remove(future)
                            try:
                                future.result()
                            except Exception as error:
                                logger.warning("analysis_task_ended type=%s", type(error).__name__)
                    if len(active) < slots:
                        for model, execute, options in registry:
                            if len(active) >= slots:
                                break
                            with factory() as db:
                                item = scheduling.claim(db, model, scheduler_id, **options)
                            if item:
                                key, reservation = item
                                active.add(
                                    pool.submit(
                                        _run_task,
                                        model,
                                        execute,
                                        key,
                                        reservation,
                                        factory,
                                        stop,
                                        logger,
                                    )
                                )
                    if len(active) < slots:
                        for claim, execute in (
                            (
                                case_analysis_execution.claim_application,
                                case_analysis_apply.execute,
                            ),
                            (generation_execution.claim_application, generation_apply.execute),
                        ):
                            with factory() as db:
                                key = claim(db)
                            if key is not None:
                                execute(key, factory)
                    time.sleep(1)
                except DATABASE_ERRORS:
                    logger.warning("analysis_scheduler_database_unavailable active=%s", len(active))
                    if current is not None:
                        current.invalidate()
                        if current is not lock:
                            current.close()
                        current = None
                    stop.wait(5)
        finally:
            stop.set()
            if current is not None and current is not lock:
                current.invalidate()
                current.close()
            logger.info("analysis_worker_stopping_active_calls count=%s", len(active))
            # The executor joins all calls before the owning DB lock is discarded/recovery runs.
            # A blocked connection keeps its reservation; there is no timeout-based replay.


if __name__ == "__main__":
    main()
