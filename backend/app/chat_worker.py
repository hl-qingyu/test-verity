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
from app.db.session import get_engine
from app.integrations.call_control import execution_scope
from app.modules.ai import reservations, scheduling
from app.modules.case_analysis import apply as case_analysis_apply
from app.modules.case_analysis import execution as case_analysis_execution
from app.modules.case_generation import apply as generation_apply
from app.modules.case_generation import execution as generation_execution
from app.modules.change_analysis import execution as change_analysis_execution
from app.modules.code_analysis import execution as code_analysis_execution
from app.modules.requirements import chat_execution, risk_analysis_execution
from app.modules.skills import execution as skills_execution


def main():
    configure_logging("chat-worker")
    logger = logging.getLogger("app.chat_worker")
    engine = get_engine()
    reconnecting = False
    try:
        while True:
            try:
                _run(engine, logger)
                if not reconnecting:
                    raise SystemExit("对话Worker已运行")
                logger.warning("analysis_chat_worker_waiting_for_lock")
            except (OperationalError, InterfaceError) as exc:
                reconnecting = True
                logger.warning(
                    "analysis_chat_worker_database_unavailable type=%s", type(exc).__name__
                )
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("requirement_chat_worker_stopped")


def _run(engine: Engine, logger: logging.Logger) -> None:
    with engine.connect() as lock:
        try:
            if not lock.scalar(text("SELECT pg_try_advisory_lock(2026091725)")):
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
                    raise SystemExit("仍有尚未核验结束的AI调用，已停止恢复与领取；请核对原执行进程")

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


def _schedule(lock, factory, logger):
    stop = Event()
    scheduler_id = str(uuid4())
    slots = max(1, Settings().ai_max_concurrent)
    registry = (
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
        (models.CaseGenerationChatTurn, generation_execution.execute_chat, {}),
        (models.RequirementChatTurn, chat_execution.execute, {}),
        (models.ChangeAnalysisChatTurn, change_analysis_execution.execute_chat, {}),
        (models.CodeAnalysisChatTurn, code_analysis_execution.execute_chat, {}),
    )

    def run(execute, key, reservation):
        try:
            with execution_scope(stop):
                execute(key, factory)
        finally:
            # Completion (including cancellation) must precede releasing a reservation.
            with factory() as db:
                reservations.release(db, reservation, interrupted=stop.is_set())

    active = set()
    with ThreadPoolExecutor(max_workers=slots, thread_name_prefix="analysis") as pool:
        try:
            while True:
                # A lost owning connection is never silently reconnected by this loop.
                owned = lock.scalar(
                    text(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                        "AND pid=pg_backend_pid() AND classid=0 AND objid=2026091725 AND granted)"
                    )
                )
                lock.commit()
                if not owned:
                    raise OperationalError(None, None, RuntimeError("scheduler_lock_lost"))
                for future in tuple(active):
                    if future.done():
                        future.result()
                        active.remove(future)
                if len(active) < slots:
                    for model, execute, options in registry:
                        if len(active) >= slots:
                            break
                        with factory() as db:
                            item = scheduling.claim(db, model, scheduler_id, **options)
                        if item:
                            key, reservation = item
                            active.add(pool.submit(run, execute, key, reservation))
                # Existing local write applications do not call a model or consume its budget.
                if len(active) < slots:
                    for claim, execute in (
                        (case_analysis_execution.claim_application, case_analysis_apply.execute),
                        (generation_execution.claim_application, generation_apply.execute),
                    ):
                        with factory() as db:
                            key = claim(db)
                        if key is not None:
                            execute(key, factory)
                time.sleep(1)
        finally:
            stop.set()
            logger.info("analysis_worker_stopping_active_calls count=%s", len(active))
            # The executor joins all calls before the owning DB lock is discarded/recovery runs.
            # A blocked connection keeps its reservation; there is no timeout-based replay.


if __name__ == "__main__":
    main()
