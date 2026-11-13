"""Read-only project summaries. Business item states remain owned by their source modules."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.db.models import ManagedCase, SourceDocument
from app.modules.case_analysis.overview import project_summary as review_summary
from app.modules.case_generation.overview import project_summary as generation_summary
from app.modules.change_analysis.overview import project_summary as change_summary
from app.modules.code_analysis.overview import project_summary as code_summary
from app.modules.overview import schemas
from app.modules.projects.service import access_project
from app.modules.requirements.overview import project_summary as requirement_summary

PROVIDERS = {
    "requirements": requirement_summary,
    "generate": generation_summary,
    "coverage": review_summary,
    "code": code_summary,
    "changes": change_summary,
}
PARTS = {
    "requirements": [("risks", "PENDING", "待确认"), ("risks", "NEEDS_INFO", "已确认待补充")],
    "generate": [
        ("suggestions", "PENDING", "有待审建议"),
        ("questions", "PENDING", "有待澄清事项"),
    ],
    "coverage": [("findings", "待确认", "待确认"), ("findings", "已确认待处理", "已确认待处理")],
    "code": [
        ("findings", "PENDING", "待处理"),
        ("findings", "CONFIRMED", "已确认"),
        ("findings", "NEEDS_EVIDENCE", "需补充证据"),
    ],
    "changes": [
        ("impacts", "PENDING", "待处理"),
        ("impacts", "CONFIRMED", "已确认"),
        ("impacts", "NEEDS_EVIDENCE", "需补充证据"),
        ("regressions", "PENDING", "回归建议 · 待审阅"),
        ("regressions", "DEFERRED", "回归建议 · 暂缓"),
    ],
}
logger = logging.getLogger(__name__)


def read_module(module, project_id, actor, db):
    try:
        with db.begin_nested():
            return PROVIDERS[module](project_id, actor, db)
    except (SQLAlchemyError, ValueError, TypeError, KeyError):
        logger.warning("project_overview_module_unavailable: %s", module)
        return None


def public_record(item):
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in item.items()
        if key != "counts"
    }


def sorted_records(items):
    return sorted(
        items,
        key=lambda r: (
            -r["created_at"].timestamp(),
            list(PROVIDERS).index(r["module"]),
            -r["record_id"],
        ),
    )


def summary(project_id, actor, db, payload: schemas.Query):
    project = access_project(project_id, actor, db)
    counts = {}
    for purpose, count in db.execute(
        select(SourceDocument.purpose, func.count())
        .where(SourceDocument.project_id == project_id, SourceDocument.deleted_at.is_(None))
        .group_by(SourceDocument.purpose)
    ):
        counts[purpose] = count
    case_count = db.scalar(
        select(func.count())
        .select_from(ManagedCase)
        .where(
            ManagedCase.project_id == project_id,
            ManagedCase.deleted_at.is_(None),
            ManagedCase.lifecycle == "ACTIVE",
        )
    )
    records, attention, unavailable = [], [], []
    for module in PROVIDERS:
        rows = read_module(module, project_id, actor, db)
        if rows is None:
            unavailable.append(module)
        else:
            records.extend(rows)
        attention.append(
            {
                "module": module,
                "available": rows is not None,
                "parts": [
                    {
                        "group": group,
                        "state": state,
                        "label": label,
                        "count": sum(r["counts"].get(f"{group}:{state}", 0) for r in rows)
                        if rows is not None
                        else None,
                    }
                    for group, state, label in PARTS[module]
                ],
            }
        )
    statuses = {"running": {"QUEUED", "RUNNING"}, "completed": {"COMPLETED"}, "failed": {"FAILED"}}
    recent = (
        records
        if payload.filter == "all"
        else [r for r in records if r["status"] in statuses[payload.filter]]
    )
    # A permission change never becomes a partial success with stale project data.
    access_project(project_id, actor, db)
    return {
        "project_id": project_id,
        "project": {
            "name": project.name,
            "identifier": project.identifier,
            "description": project.description,
        },
        "as_of": datetime.now(UTC).isoformat(),
        "filter": payload.filter,
        "counts": {
            "requirements": counts.get("REQUIREMENT", 0),
            "prototypes": counts.get("PROTOTYPE", 0),
            "cases": case_count,
            "queued": sum(r["status"] == "QUEUED" for r in records) if not unavailable else None,
            "running": sum(r["status"] == "RUNNING" for r in records) if not unavailable else None,
        },
        "attention": attention,
        "recent": [public_record(r) for r in sorted_records(recent)[:8]],
        "unavailable": unavailable,
    }


def attention(project_id, actor, db, payload: schemas.AttentionQuery):
    access_project(project_id, actor, db)
    if not any(
        group == payload.group and state == payload.state
        for group, state, _ in PARTS[payload.module]
    ):
        raise AppError(422, "overview_filter_invalid")
    rows = read_module(payload.module, project_id, actor, db)
    if rows is None:
        raise AppError(503, "overview_module_unavailable")
    matched = sorted_records(
        [r for r in rows if r["counts"].get(f"{payload.group}:{payload.state}", 0)]
    )
    start = (payload.page - 1) * 20
    return {
        "project_id": project_id,
        "module": payload.module,
        "group": payload.group,
        "state": payload.state,
        "page": payload.page,
        "total": len(matched),
        "items": [public_record(r) for r in matched[start : start + 20]],
    }
