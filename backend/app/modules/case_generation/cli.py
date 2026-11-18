"""Task-scoped CLI timeline access. Attempt paths always come from authorized records."""

from app.core.errors import AppError
from app.db.models import CaseGenerationBatch, CaseGenerationChatTurn
from app.integrations import codex_events
from app.modules.case_generation import service


def events(project_id, run_id, kind, key, actor, db, cursor=0, attempt=None):
    service.own(project_id, run_id, actor, db)
    model = CaseGenerationBatch if kind == "batch" else CaseGenerationChatTurn
    row = db.get(model, key)
    if row is None or row.run_id != run_id:
        raise AppError(404, "generation_not_found")
    if row.actor_id != actor.id:
        raise AppError(403, "generation_owner_only")
    attempts = (
        row.attempts
        if kind == "batch"
        else [{"status": row.status, "diagnostics": row.context.get("cli_diagnostics", {})}]
    )
    index = len(attempts) - 1 if attempt is None else attempt
    if index < 0 and not attempts:
        current = {}
    elif not 0 <= index < len(attempts):
        raise AppError(404, "generation_cli_log_unavailable")
    else:
        current = attempts[index]
    diagnostics = current.get("diagnostics") or {}
    attempt_id = diagnostics.get("cli_attempt_id")
    result = (
        codex_events.read_events(attempt_id, cursor)
        if attempt_id
        else {"items": [], "next_cursor": cursor, "has_more": False, "available": False}
    )
    return {
        **result,
        "status": current.get("status", row.status),
        "attempt_index": index,
        "attempts": [
            {"index": i, "status": a.get("status", ""), "started_at": a.get("started_at")}
            for i, a in enumerate(attempts)
        ],
    }
