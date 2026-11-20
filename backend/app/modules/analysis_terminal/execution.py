"""Resume a private native history through the existing AI worker and budget."""

from datetime import UTC, datetime
from time import monotonic

from sqlalchemy import update

from app.core.errors import AppError
from app.db.models import AnalysisTerminalResume, UserAccount
from app.integrations import ai_client
from app.modules.ai import native_terminal
from app.modules.ai.recovery import propagate_database_outage
from app.modules.ai.service import analysis_configuration
from app.modules.analysis_terminal import service
from app.modules.case_generation import sources as case_sources
from app.modules.change_analysis import sources as change_sources
from app.modules.code_analysis import sources as code_sources
from app.modules.requirements import risk_analysis_service


def recheck_sources(kind, row, project_id, actor, db):
    if kind == "requirements":
        risk_analysis_service.frozen_materials(project_id, row, actor, db)
    elif kind == "coverage":
        case_sources.recheck(project_id, row.metadata_snapshot, actor, db)
    else:
        sources = code_sources if kind == "code" else change_sources
        metadata = row.metadata_snapshot
        sources.recheck(
            project_id, metadata, actor, db, shared_snapshot=metadata.get("shared_snapshot", False)
        )


def recover(db):
    db.execute(
        update(AnalysisTerminalResume)
        .where(AnalysisTerminalResume.status == "RUNNING")
        .values(
            status="FAILED",
            error_code="analysis_terminal_interrupted",
            updated_at=datetime.now(UTC),
        )
    )
    db.commit()


def execute(resume_id, factory):
    try:
        with factory() as db:
            resume = db.get(AnalysisTerminalResume, resume_id)
            if not resume or resume.status != "RUNNING":
                return
            project_id, kind, record_id = resume.project_id, resume.record_kind, resume.record_id
            owner_id, rows, cols = resume.actor_id, resume.rows, resume.cols
            actor = db.get(UserAccount, owner_id)
            row = service.own(project_id, kind, record_id, actor, db, full=True)
            recheck_sources(kind, row, project_id, actor, db)
            config, key = analysis_configuration(actor, db, resume.ai_config)
            identity = service.terminal_spec(row)["identity"]
            resume_thread = service.history_thread(row)
            if not resume_thread:
                raise AppError(409, "analysis_terminal_history_unavailable")

        last_check = 0.0

        def check(force=False):
            nonlocal last_check
            if not force and monotonic() - last_check < 1:
                return
            last_check = monotonic()
            with factory() as db:
                actor = db.get(UserAccount, owner_id)
                service.own(project_id, kind, record_id, actor, db)
                current = db.get(AnalysisTerminalResume, resume_id)
                if not current or current.status != "RUNNING":
                    raise AppError(409, "analysis_terminal_cancelled")
                if not native_terminal.enabled_for(owner_id):
                    raise AppError(403, "generation_terminal_permission_required")
                analysis_configuration(actor, db, config)

        check()
        ai_client.terminal(
            config["base_url"],
            config["model"],
            key,
            config["reasoning_effort"],
            identity=identity,
            execution=resume_id,
            instructions="",
            fixed_input={},
            resume=True,
            resume_thread=resume_thread,
            rows=rows,
            cols=cols,
            on_progress=check,
        )
        check(force=True)
        status, error_code = "COMPLETED", ""
    except Exception as exc:
        propagate_database_outage(exc)
        status = "FAILED"
        error_code = exc.detail if isinstance(exc, AppError) else "generation_terminal_failed"
    with factory() as db:
        db.execute(
            update(AnalysisTerminalResume)
            .where(
                AnalysisTerminalResume.id == resume_id, AnalysisTerminalResume.status == "RUNNING"
            )
            .values(status=status, error_code=error_code, updated_at=datetime.now(UTC))
        )
        db.commit()
