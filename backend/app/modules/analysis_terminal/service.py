"""Native history for analysis records whose first run uses the Codex terminal."""

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import load_only

from app.core.errors import AppError
from app.db.models import (
    AICallReservation,
    AnalysisTerminalResume,
    CaseAnalysisRun,
    ChangeAnalysisTask,
    CodeAnalysisTask,
    RequirementRiskAnalysis,
)
from app.integrations import codex_terminal
from app.modules.ai import native_terminal
from app.modules.ai.service import analysis_configuration, configuration_snapshot
from app.modules.documents.service import access

RecordKind = Literal["requirements", "code", "changes", "coverage"]
MODELS = {
    "requirements": RequirementRiskAnalysis,
    "code": CodeAnalysisTask,
    "changes": ChangeAnalysisTask,
    "coverage": CaseAnalysisRun,
}
ACTIVE = ("QUEUED", "RUNNING")


def own(project_id, kind: RecordKind, record_id, actor, db, *, lock=False, full=False):
    if actor is None:
        raise AppError(401, "not_authenticated")
    access(project_id, actor, db, lock=lock)
    model = MODELS[kind]
    query = select(model).where(
        model.id == record_id, model.project_id == project_id, model.deleted_at.is_(None)
    )
    if not full:
        query = query.options(
            load_only(
                model.id,
                model.actor_id,
                model.status,
                model.error_code,
                model.request_id,
                model.ai_config,
            )
        )
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None or not row.ai_config.get(native_terminal.TERMINAL_KEY):
        raise AppError(404, "analysis_terminal_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "analysis_terminal_owner_only")
    return row


def resumes(project_id, kind: RecordKind, row):
    return select(AnalysisTerminalResume).where(
        AnalysisTerminalResume.project_id == project_id,
        AnalysisTerminalResume.record_kind == kind,
        AnalysisTerminalResume.record_id == row.id,
        AnalysisTerminalResume.actor_id == row.actor_id,
    )


def terminal_spec(row):
    return row.ai_config[native_terminal.TERMINAL_KEY]


def history_thread(row):
    spec = terminal_spec(row)
    return codex_terminal.history_thread(spec["identity"], spec["execution"])


def project_session(row, resume=None):
    spec = terminal_spec(row)
    execution = row
    if resume:
        execution = resume
        spec = {**spec, "execution": resume.id, "rows": resume.rows, "cols": resume.cols}
    result = native_terminal.session_view(
        {
            "id": execution.id,
            "request_id": execution.request_id,
            "status": execution.status,
            "error_code": execution.error_code,
            "terminal": spec,
        },
        kind="chat" if resume else "generation",
    )
    result["resumable"] = execution.status not in ACTIVE and bool(history_thread(row))
    return result, spec


def current(project_id, kind: RecordKind, record_id, actor, db):
    row = own(project_id, kind, record_id, actor, db)
    latest = db.scalar(
        resumes(project_id, kind, row).order_by(AnalysisTerminalResume.id.desc()).limit(1)
    )
    session, _ = project_session(row, latest)
    return {
        "session": session,
        "enabled": native_terminal.enabled_for(actor.id),
        "generation_bound": True,
    }


def binding(project_id, kind: RecordKind, record_id, execution_id, actor, db, *, initial=False):
    row = own(project_id, kind, record_id, actor, db)
    if initial:
        if execution_id != row.id:
            raise AppError(404, "analysis_terminal_not_found")
        resume = None
    else:
        resume = db.scalar(
            resumes(project_id, kind, row).where(AnalysisTerminalResume.id == execution_id)
        )
        if resume is None:
            raise AppError(404, "analysis_terminal_not_found")
    session, spec = project_session(row, resume)
    return {
        "identity": spec["identity"],
        "execution": spec["execution"],
        "owner_id": actor.id,
        "session": session,
    }


def start(project_id, kind: RecordKind, record_id, payload, actor, db):
    row = own(project_id, kind, record_id, actor, db, lock=True)
    if not native_terminal.enabled_for(actor.id):
        raise AppError(403, "generation_terminal_permission_required")
    if not payload.resume:
        raise AppError(409, "analysis_terminal_resume_required")
    query = resumes(project_id, kind, row)
    replay = db.scalar(query.where(AnalysisTerminalResume.request_id == str(payload.request_id)))
    if replay:
        return {"session": project_session(row, replay)[0]}
    if row.status in ACTIVE:
        return {"session": project_session(row)[0]}
    active = db.scalar(query.where(AnalysisTerminalResume.status.in_(ACTIVE)))
    if active:
        return {"session": project_session(row, active)[0]}
    if not history_thread(row):
        raise AppError(409, "analysis_terminal_history_unavailable")
    if db.scalar(
        select(AICallReservation.id)
        .where(
            AICallReservation.state == "HELD",
            or_(
                and_(
                    AICallReservation.kind == MODELS[kind].__tablename__,
                    AICallReservation.task_id == row.id,
                ),
                and_(
                    AICallReservation.kind == AnalysisTerminalResume.__tablename__,
                    AICallReservation.task_id.in_(
                        query.with_only_columns(AnalysisTerminalResume.id)
                    ),
                ),
            ),
        )
        .limit(1)
    ):
        raise AppError(409, "analysis_terminal_stopping")
    config, _ = analysis_configuration(actor, db, row.ai_config)
    resume = AnalysisTerminalResume(
        project_id=project_id,
        record_kind=kind,
        record_id=row.id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        ai_config=configuration_snapshot(config),
        rows=payload.rows,
        cols=payload.cols,
    )
    db.add(resume)
    db.flush()
    view, _ = project_session(row, resume)
    db.commit()
    return {"session": view}


def cancel(project_id, kind: RecordKind, record_id, execution_id, actor, db):
    row = own(project_id, kind, record_id, actor, db, lock=True)
    resume = db.scalar(
        resumes(project_id, kind, row)
        .where(AnalysisTerminalResume.id == execution_id)
        .with_for_update()
    )
    if resume is None:
        raise AppError(404, "analysis_terminal_not_found")
    if resume.status in ACTIVE:
        resume.status, resume.updated_at = "CANCELLED", datetime.now(UTC)
    view, _ = project_session(row, resume)
    db.commit()
    return {"session": view}
