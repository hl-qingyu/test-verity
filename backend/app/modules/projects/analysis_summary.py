"""Public scalar projections for project analysis summaries; never select source bodies."""

from collections import Counter

from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH

from app.db.models import UserAccount


def metadata(model, project_id):
    return (
        select(
            model.id,
            model.title,
            model.status,
            model.created_at,
            UserAccount.display_name.label("actor"),
            model.metadata_snapshot["origin"].astext.label("origin"),
        )
        .outerjoin(UserAccount, UserAccount.id == model.actor_id)
        .where(model.project_id == project_id, model.deleted_at.is_(None))
    )


def keys(column, path):
    return func.jsonb_path_query_array(column, cast(path, JSONPATH))


def states(column, field="status", *, history=False):
    entries = func.jsonb_each(func.coalesce(column, cast(literal("{}"), JSONB))).table_valued(
        "key", "value"
    )
    value = cast(entries.c.value, JSONB)
    if history:
        value = value[-1]
    return (
        select(func.jsonb_object_agg(entries.c.key, value[field]))
        .select_from(entries)
        .correlate_except(entries)
        .scalar_subquery()
    )


def item_counts(item_keys, handling, default):
    return Counter((handling or {}).get(key) or default for key in set(item_keys or []))


def record(row, module, counts, *, outcome=None):
    return {
        "module": module,
        "record_type": "run" if module in {"generate", "coverage"} else "task",
        "record_id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "created_at": row["created_at"],
        "actor": row["actor"] or "已删除账号",
        "imported": row["origin"] == "IMPORT",
        "outcome": outcome,
        "application_failed": False,
        "counts": counts,
    }
