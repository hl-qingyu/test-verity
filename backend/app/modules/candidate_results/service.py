"""Common candidate visibility and immutable manual drafts, without model calls or DB access."""

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.core.config import Settings
from app.core.errors import AppError
from app.modules.candidate_results.json_candidates import (
    Pairs,
    display,
    duplicate_fields,
    original_json,
)

KINDS = {"requirements", "code_analysis", "change_analysis", "case_analysis"}


def fingerprint(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def current(kind, task_id, original, metadata):
    history = metadata.get("candidate_review_history", [])
    if not history:
        return original
    record = history[-1]
    prefix = f"{kind}-{task_id}-"
    try:
        name = record["artifact"]
        if (
            kind not in KINDS
            or not isinstance(name, str)
            or not name.startswith(prefix)
            or not name.endswith(".json")
        ):
            raise ValueError()
        UUID(name[len(prefix) : -5])
        root = Settings().document_storage_path.resolve().parent / "candidate-reviews"
        path = root / name
        if path.is_symlink() or path.resolve().parent != root:
            raise ValueError()
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != record["artifact_sha256"]:
            raise ValueError()
        value = json.loads(body)
        if value["original_sha256"] != fingerprint(original):
            raise ValueError()
        return value["candidate_json"]
    except (OSError, ValueError, KeyError, TypeError):
        raise AppError(503, "candidate_review_unavailable") from None


def inspect(raw, error_code=""):
    items = []
    conflicts = []
    parse_error = False
    text = raw
    fence = re.fullmatch(r"\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*", text)
    if fence:
        text = fence[1]
    try:
        root = json.loads(text, object_pairs_hook=Pairs)
        conflicts = duplicate_fields(root)
        if isinstance(root, Pairs):
            for group, values in root:
                if isinstance(values, list) and not isinstance(values, Pairs):
                    for index, value in enumerate(values):
                        local = duplicate_fields(value)
                        title = ""
                        if isinstance(value, Pairs):
                            title = next(
                                (
                                    v
                                    for k, v in value
                                    if k in ("title", "name", "statement", "question", "conclusion")
                                    and isinstance(v, str)
                                ),
                                "",
                            )
                        items.append(
                            {
                                "group": display(group),
                                "ordinal": index + 1,
                                "title": display(title),
                                "rawJson": original_json(value),
                                "conflicts": local,
                            }
                        )
    except (ValueError, UnicodeError, RecursionError):
        parse_error = True
    # This is a readable candidate workspace, never a claim that references/business rules passed.
    return {
        "candidateJson": display(raw),
        "sha256": fingerprint(raw),
        "items": items,
        "conflicts": conflicts,
        "parseError": parse_error,
        "errorCode": error_code,
    }


def view(kind, task_id, original, metadata, error_code, *, can_edit):
    value = current(kind, task_id, original, metadata)
    history = metadata.get("candidate_review_history", [])
    return {
        **inspect(value, error_code),
        "canEdit": can_edit,
        "history": [
            {
                k: v
                for k, v in entry.items()
                if k in ("at", "actor_id", "reason", "error_code", "validation_passed")
            }
            for entry in history
        ],
    }


def replay(metadata, payload):
    found = next(
        (
            entry
            for entry in metadata.get("candidate_review_history", [])
            if entry.get("request_id") == str(payload.request_id)
        ),
        None,
    )
    if not found:
        return False
    if (
        found["candidate_sha256"] != fingerprint(payload.candidate_json)
        or found["reason"] != payload.reason
    ):
        raise AppError(409, "candidate_review_changed")
    return True


def evaluate(kind, task_id, original, metadata, payload, actor_id, validator, *, previous_error=""):
    if kind not in KINDS:
        raise AppError(422, "candidate_review_invalid")
    if fingerprint(current(kind, task_id, original, metadata)) != payload.base_sha256:
        raise AppError(409, "candidate_review_changed")
    if not payload.confirmed:
        raise AppError(422, "candidate_review_invalid")
    try:
        result = validator(payload.candidate_json)
        error = ""
    except AppError as failure:
        result = None
        error = failure.detail
    record = {
        "kind": kind,
        "task_id": task_id,
        "original_sha256": fingerprint(original),
        "candidate_json": payload.candidate_json,
        "request_id": str(payload.request_id),
        "actor_id": actor_id,
        "at": datetime.now(UTC).isoformat(),
        "reason": payload.reason,
        "previous_error_code": previous_error,
        "validation_passed": result is not None,
        "error_code": error,
    }
    encoded = json.dumps(record, ensure_ascii=True, indent=2).encode()
    root = Settings().document_storage_path.resolve().parent / "candidate-reviews"
    name = f"{kind}-{task_id}-{uuid4()}.json"
    try:
        root.mkdir(parents=True, exist_ok=True)
        with (root / name).open("xb") as file:
            file.write(encoded)
    except OSError:
        raise AppError(503, "candidate_review_unavailable") from None
    audit = {k: v for k, v in record.items() if k != "candidate_json"}
    audit.update(
        artifact=name,
        artifact_sha256=hashlib.sha256(encoded).hexdigest(),
        candidate_sha256=fingerprint(payload.candidate_json),
    )
    updated = {
        **metadata,
        "candidate_review_history": [*metadata.get("candidate_review_history", []), audit],
    }
    return result, updated, error
