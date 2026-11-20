"""Soft-delete project analysis records without removing fixed evidence or applications."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import (
    AnalysisTerminalResume,
    CaseAnalysisApplication,
    CaseAnalysisChatTurn,
    CaseAnalysisRun,
    CaseGenerationApplication,
    CaseGenerationBatch,
    CaseGenerationChatTurn,
    CaseGenerationRun,
    ChangeAnalysisChatTurn,
    ChangeAnalysisTask,
    CodeAnalysisChatTurn,
    CodeAnalysisTask,
    RequirementChatTurn,
    RequirementRiskAnalysis,
    RequirementRiskReport,
)
from app.modules.documents.service import access
from app.modules.projects.service import access_project

MODELS = {
    "requirement-task": RequirementRiskAnalysis,
    "requirements": RequirementRiskReport,
    "code": CodeAnalysisTask,
    "changes": ChangeAnalysisTask,
    "generate": CaseGenerationRun,
    "coverage": CaseAnalysisRun,
}
CHILDREN = {
    "requirements": [(RequirementChatTurn, "report_id")],
    "code": [(CodeAnalysisChatTurn, "task_id")],
    "changes": [(ChangeAnalysisChatTurn, "task_id")],
    "generate": [
        (CaseGenerationBatch, "run_id"),
        (CaseGenerationChatTurn, "run_id"),
        (CaseGenerationApplication, "run_id"),
    ],
    "coverage": [(CaseAnalysisChatTurn, "run_id"), (CaseAnalysisApplication, "run_id")],
}
ACTIVE = ("QUEUED", "RUNNING")


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    revision: int | None = Field(default=None, ge=1)


def require_visible(row):
    if row is not None and getattr(row, "deleted_at", None) is not None:
        raise AppError(404, "analysis_record_deleted")


def requirement_permissions(project_id, rows, actor, db):
    """Project/report ownership in two scalar queries, including shared report creators."""
    project = access_project(project_id, actor, db)
    if actor.platform_role == "ADMIN" or project.owner_id == actor.id:
        return {r.id: True for r in rows}
    report_ids = {r.id if isinstance(r, RequirementRiskReport) else r.report_id for r in rows} - {
        None
    }
    owners = {key: set() for key in report_ids}
    if report_ids:
        for key, owner in db.execute(
            select(RequirementRiskReport.id, RequirementRiskReport.created_by).where(
                RequirementRiskReport.project_id == project_id,
                RequirementRiskReport.id.in_(report_ids),
            )
        ):
            owners[key].add(owner)
        for key, owner in db.execute(
            select(RequirementRiskAnalysis.report_id, RequirementRiskAnalysis.actor_id).where(
                RequirementRiskAnalysis.project_id == project_id,
                RequirementRiskAnalysis.report_id.in_(report_ids),
            )
        ):
            owners[key].add(owner)
    return {
        r.id: (r.created_by if isinstance(r, RequirementRiskReport) else r.actor_id) == actor.id
        and owners.get(r.id if isinstance(r, RequirementRiskReport) else r.report_id, set())
        <= {actor.id}
        for r in rows
    }


def related(module, row, db, *, lock=False):
    rows = [row]
    report_id = row.report_id if module == "requirement-task" else row.id
    if module not in {"requirement-task", "requirements"} or report_id is None:
        return rows
    if module == "requirement-task":
        query = select(RequirementRiskReport).where(
            RequirementRiskReport.id == report_id,
            RequirementRiskReport.project_id == row.project_id,
        )
        report = db.scalar(query.with_for_update() if lock else query)
        if report is not None:
            rows.append(report)
    query = (
        select(RequirementRiskAnalysis)
        .where(
            RequirementRiskAnalysis.project_id == row.project_id,
            RequirementRiskAnalysis.report_id == report_id,
        )
        .order_by(RequirementRiskAnalysis.id)
    )
    rows.extend(r for r in db.scalars(query.with_for_update() if lock else query) if r is not row)
    return rows


def active(rows, db):
    for row in rows:
        if getattr(row, "status", None) in ACTIVE:
            return True
        module = next(k for k, model in MODELS.items() if isinstance(row, model))
        terminal_kind = "requirements" if module == "requirement-task" else module
        if (
            module in {"requirement-task", "code", "changes", "coverage"}
            and db.scalar(
                select(AnalysisTerminalResume.id)
                .where(
                    AnalysisTerminalResume.project_id == row.project_id,
                    AnalysisTerminalResume.record_kind == terminal_kind,
                    AnalysisTerminalResume.record_id == row.id,
                    AnalysisTerminalResume.status.in_(ACTIVE),
                )
                .limit(1)
            )
            is not None
        ):
            return True
        for model, foreign_key in CHILDREN.get(module, []):
            if (
                db.scalar(
                    select(model.id)
                    .where(getattr(model, foreign_key) == row.id, model.status.in_(ACTIVE))
                    .limit(1)
                )
                is not None
            ):
                return True
    return False


def context(project_id, module, record_id, actor, db, *, lock=False):
    access(project_id, actor, db, lock=lock)
    project = access_project(project_id, actor, db)
    model = MODELS[module]
    query = select(model).where(model.project_id == project_id, model.id == record_id)
    query = query.execution_options(populate_existing=True)
    row = db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise AppError(404, "analysis_record_not_found")
    rows = related(module, row, db, lock=lock)
    manager = actor.platform_role == "ADMIN" or project.owner_id == actor.id
    allowed = manager or all(
        (r.created_by if isinstance(r, RequirementRiskReport) else r.actor_id) == actor.id
        for r in rows
    )
    return row, rows, allowed


def info(project_id, module, record_id, actor, db):
    row, rows, allowed = context(project_id, module, record_id, actor, db)
    require_visible(row)
    return {
        "id": row.id,
        "project_id": project_id,
        "title": row.title,
        "revision": getattr(row, "revision", None),
        "can_delete": allowed,
        "active": active(rows, db) if allowed else False,
    }


def remove(project_id, module, record_id, payload, actor, db):
    row, rows, allowed = context(project_id, module, record_id, actor, db, lock=True)
    if not allowed:
        raise AppError(403, "analysis_delete_forbidden")
    if row.deleted_at is None:
        if getattr(row, "revision", None) != payload.revision:
            raise AppError(409, "analysis_delete_changed")
        if active(rows, db):
            raise AppError(409, "analysis_delete_active")
        now = datetime.now(UTC)
        for item in rows:
            if item.deleted_at is None:
                item.deleted_at, item.deleted_by = now, actor.id
                if hasattr(item, "revision"):
                    item.revision += 1
                item.updated_at = now
        db.commit()
    return {"id": row.id, "project_id": project_id, "deleted": True}
