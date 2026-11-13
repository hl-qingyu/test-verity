"""Immutable private candidate review snapshots; database attempts contain references only."""

import copy
import hashlib
import json
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.candidate_results.json_candidates import display


def folder():
    return Settings().case_generation_result_path.resolve()


def current_attempt(batch):
    return next((a for a in batch.attempts if a.get("request_id") == batch.request_id), {})


def read(batch, descriptor=None):
    descriptor = descriptor or current_attempt(batch).get("candidate_delivery")
    if not descriptor:
        return None
    try:
        name = descriptor["artifact"]
        prefix = f"batch-{batch.id}-{batch.request_id}.delivery-"
        if not isinstance(name, str) or not name.startswith(prefix) or not name.endswith(".json"):
            raise ValueError()
        UUID(name[len(prefix) : -5])
        path = folder() / name
        if path.is_symlink() or path.resolve().parent != folder():
            raise ValueError()
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != descriptor["sha256"]:
            raise ValueError()
        value = json.loads(raw)
        if value["request_id"] != batch.request_id or value["batch_id"] != batch.id:
            raise ValueError()
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise AppError(503, "generation_candidate_review_unavailable") from None


def save(batch, result, *, resolutions=None, audit=None):
    record = {
        "version": 1,
        "batch_id": batch.id,
        "request_id": batch.request_id,
        "issues": result.issues,
        "report": result.report,
        "error_code": result.error_code,
        "resolutions": resolutions or {},
        "audit": audit or {},
    }
    raw = json.dumps(record, ensure_ascii=True, indent=2).encode()
    name = f"batch-{batch.id}-{batch.request_id}.delivery-{uuid4()}.json"
    try:
        folder().mkdir(parents=True, exist_ok=True)
        with (folder() / name).open("xb") as stream:
            stream.write(raw)
    except OSError:
        raise AppError(503, "generation_candidate_review_unavailable") from None
    attempts = copy.deepcopy(batch.attempts)
    attempt = next((a for a in attempts if a.get("request_id") == batch.request_id), None)
    if attempt is None:
        attempt = {"request_id": batch.request_id, "actor_id": batch.actor_id}
        attempts.append(attempt)
    if attempt.get("candidate_delivery"):
        attempt.setdefault("candidate_delivery_history", []).append(attempt["candidate_delivery"])
    attempt["candidate_delivery"] = {
        "artifact": name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "pending": sum(i["status"] == "PENDING" for i in result.issues),
        "issues": len(result.issues),
        "resolution_request_id": (audit or {}).get("request_id"),
    }
    batch.attempts = attempts


def views(batch, actor):
    saved = read(batch)
    if not saved:
        return []
    owner = actor.id == batch.actor_id
    return [
        {
            "key": f"{batch.id}:{item['key']}",
            "issueId": item["key"],
            "batchId": batch.id,
            "kind": item["kind"],
            "ordinal": item["ordinal"],
            "status": item["status"],
            "reason": item["error_code"],
            "rawJson": display(item["raw_json"]) if owner else "",
            "correctedJson": display(item.get("corrected_json", "")) if owner else "",
            "duplicates": item["duplicates"] if owner else [],
            "note": item.get("resolution_note", "") if owner else "",
            "canEdit": owner
            and batch.status in ("FAILED", "COMPLETED")
            and item["status"] != "RESOLVED",
        }
        for item in saved["issues"]
    ]
