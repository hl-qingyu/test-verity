"""Native results stay as independent review rounds in their original record."""

import copy
import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import (
    AnalysisAcceptance,
    CaseGenerationApplication,
    CaseGenerationBatch,
    CaseGenerationChatTurn,
    CaseGenerationRun,
)
from app.integrations import native_candidates
from app.modules.candidate_results.json_candidates import Pairs, display
from app.modules.case_generation import (
    contract,
    delivery,
    delivery_files,
    execution,
    native_rounds,
    native_terminal,
    service,
    sources,
)


def own(project_id, run_id, actor, db, lock=False):
    row = service.own(project_id, run_id, actor, db, lock)
    # A manual retry may belong to another authorized member's personal CLI.
    # Reuse the same execution-owner rule as the native history view.
    if native_terminal.generation(project_id, run_id, actor, db) is None:
        raise AppError(404, "generation_native_result_not_found")
    return row


def generation_json(text):
    fence = re.fullmatch(r"\s*```(?:json)?\s*\n([\s\S]*?)\n```\s*", text)
    raw = fence[1] if fence else text
    return raw if raw.lstrip().startswith("{") and re.search(r'"cases"\s*:', raw) else None


def candidates(project_id, row, actor, db):
    main = native_terminal.generation(project_id, row.id, actor, db)
    if not main:
        raise AppError(404, "generation_native_result_not_found")
    result = []
    for item in native_candidates.completed_messages(main["terminal"]["identity"]):
        raw = generation_json(item["text"])
        if raw is None:
            continue
        counts = {"case_count": 0, "note_count": 0, "complete": None}
        try:
            root = json.loads(raw, object_pairs_hook=Pairs)
            if (
                isinstance(root, Pairs)
                and len(root) == 3
                and {k for k, _ in root} == {"cases", "notes", "complete"}
            ):
                value = dict(root)
                if all(
                    isinstance(value[k], list) and not isinstance(value[k], Pairs)
                    for k in ("cases", "notes")
                ):
                    counts.update(
                        case_count=len(value["cases"]),
                        note_count=len(value["notes"]),
                        complete=value["complete"] if type(value["complete"]) is bool else None,
                    )
        except (ValueError, UnicodeError, RecursionError):
            pass
        # Malformed generation JSON remains selectable for the existing issue-review flow.
        result.append({**item, "batch_id": main["id"], **counts})
    saved = {
        native_rounds.info(b)["id"]: b for b in service.batches(row, db) if native_rounds.info(b)
    }
    for item in result:
        batch = saved.get(item["id"])
        item.update(saved=batch is not None, saved_batch_id=batch.id if batch else None)
    known = {v["id"] for v in result}
    for identity, batch in saved.items():
        if identity in known or batch.actor_id != actor.id:
            continue
        info = native_rounds.info(batch)
        try:
            raw = execution.candidate_path(batch).read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            raise AppError(503, "generation_native_results_unavailable") from None
        output = batch.report.get("model_output", {})
        result.append(
            {
                **info,
                "text": raw,
                "batch_id": info["source_batch_id"],
                "case_count": len(output.get("cases", [])),
                "note_count": len(output.get("notes", [])),
                "complete": output.get("complete"),
                "saved": True,
                "saved_batch_id": batch.id,
            }
        )
    return sorted(result, key=lambda item: item["timestamp"], reverse=True)


def listing(project_id, run_id, actor, db):
    row = own(project_id, run_id, actor, db)
    items = candidates(project_id, row, actor, db)
    return {
        "items": [
            {
                k: item[k]
                for k in (
                    "id",
                    "timestamp",
                    "case_count",
                    "note_count",
                    "complete",
                    "saved",
                    "saved_batch_id",
                )
            }
            for item in items
        ]
    }


def selected(project_id, row, result_id, actor, db):
    if not re.fullmatch(r"[0-9a-f]{64}", result_id):
        raise AppError(404, "generation_native_result_not_found")
    item = next(
        (item for item in candidates(project_id, row, actor, db) if item["id"] == result_id), None
    )
    if item is None:
        raise AppError(404, "generation_native_result_not_found")
    batch = db.get(CaseGenerationBatch, item.get("saved_batch_id") or item["batch_id"])
    saved = delivery_files.read(batch) if item.get("saved") else None
    return (
        item,
        batch,
        delivery.process(
            batch.input_snapshot,
            item["text"],
            (saved or {}).get("resolutions", {}),
            preserve_partition=bool(batch.report.get("source_indices")),
        ),
    )


def preview(project_id, run_id, result_id, actor, db):
    row = own(project_id, run_id, actor, db)
    item, _, result = selected(project_id, row, result_id, actor, db)
    return {
        "id": item["id"],
        "raw_json": display(item["text"]),
        "valid_cases": len((result.report or {}).get("suggestions", [])),
        "issues": len(result.issues),
        "can_save": row.status not in service.ACTIVE,
        "saved": item.get("saved", False),
        "saved_batch_id": item.get("saved_batch_id"),
    }


def add_round(
    source, original_batch, item, request_id, actor, db, *, legacy_run_id=None, automatic=False
):
    data = native_rounds.review_input(original_batch.input_snapshot, item["id"])
    delivered = delivery.process(data, item["text"])
    report = contract.validate_report(data, delivered.report) if delivered.report else {}
    provenance = {k: item[k] for k in ("id", "thread_id", "turn_id", "timestamp", "sha256")}
    provenance.update(
        source_run_id=source.id,
        source_batch_id=original_batch.id,
        save_request_id=str(request_id),
        actor_id=actor.id,
        saved_at=datetime.now(UTC).isoformat(),
        source_input_sha256=contract.digest(original_batch.input_snapshot),
        previous_run_status=source.status,
    )
    if automatic:
        provenance["save_mode"] = "AUTO"
    if legacy_run_id is not None:
        provenance["archived_run_id"] = legacy_run_id
    captured = False
    if (
        original_batch.run_id == source.id
        and legacy_run_id is None
        and original_batch.report
        and original_batch.status == "COMPLETED"
        and native_rounds.info(original_batch) is None
    ):
        try:
            captured = (
                hashlib.sha256(execution.candidate_path(original_batch).read_bytes()).hexdigest()
                == item["sha256"]
            )
        except OSError:
            pass
    if captured:
        batch = original_batch
        attempts = copy.deepcopy(batch.attempts)
        current = next((v for v in attempts if v.get("request_id") == batch.request_id), None)
        if current is None:
            current = {
                "request_id": batch.request_id,
                "actor_id": batch.actor_id,
                "candidate": True,
            }
            attempts.append(current)
        current["native_result"] = provenance
        batch.attempts = attempts
        report = batch.report
    else:
        batch = CaseGenerationBatch(
            run_id=source.id,
            actor_id=actor.id,
            batch_ref=data["batch"]["batch_ref"],
            request_id=data["request_id"],
            status="COMPLETED" if report else "FAILED",
            input_snapshot=data,
            report=report,
            ai_config={
                k: v for k, v in original_batch.ai_config.items() if k != "generation_terminal"
            },
            attempts=[
                {
                    "request_id": data["request_id"],
                    "actor_id": actor.id,
                    "candidate": True,
                    "kind": "NATIVE_MANUAL_REVIEW",
                    "source_result_id": item["id"],
                    "native_result": provenance,
                }
            ],
            error_code="" if report else delivered.error_code,
        )
        db.add(batch)
        db.flush()
        execution.save_candidate(batch, item["text"])
        if delivered.issues:
            delivery_files.save(batch, delivered, audit=provenance)
        execution.record_format_repairs(
            batch, delivered.repairs, delivered.original or report, report
        )
    source.metadata_snapshot = {
        **source.metadata_snapshot,
        "native_results": {
            **source.metadata_snapshot.get("native_results", {}),
            item["id"]: {**provenance, "batch_id": batch.id},
        },
    }
    source.revision += 1
    source.status = (
        "COMPLETED"
        if report or any(b.status == "COMPLETED" for b in service.batches(source, db))
        else "FAILED"
    )
    source.updated_at = datetime.now(UTC)
    return batch


def archive_legacy(project_id, source, old, payload, actor, db):
    """Move only untouched, unapplied legacy copies; retain originals as audited archives."""
    service.require_visible(old)
    if (
        old.actor_id != actor.id
        or old.metadata_snapshot.get("native_result", {}).get("source_run_id") != source.id
    ):
        raise AppError(403, "generation_owner_only")
    if (
        old.metadata_snapshot.get("skill") != source.metadata_snapshot.get("skill")
        or old.metadata_snapshot.get("bindings") != source.metadata_snapshot.get("bindings")
        or old.input_snapshot != source.input_snapshot
    ):
        raise AppError(409, "generation_native_result_migration_requires_review")
    if old.handling or db.scalar(
        select(CaseGenerationApplication.id)
        .where(CaseGenerationApplication.run_id == old.id)
        .limit(1)
    ):
        raise AppError(409, "generation_native_result_migration_requires_review")
    acceptance = db.scalar(
        select(AnalysisAcceptance).where(
            AnalysisAcceptance.project_id == project_id,
            AnalysisAcceptance.module == "generate",
            AnalysisAcceptance.record_id == old.id,
        )
    )
    if acceptance is not None and (acceptance.state or acceptance.history):
        raise AppError(409, "generation_native_result_migration_requires_review")
    origin = old.metadata_snapshot["native_result"]
    originals = service.batches(old, db)
    if len(originals) != 1:
        raise AppError(409, "generation_native_result_migration_requires_review")
    original = originals[0]
    try:
        raw = execution.candidate_path(original).read_bytes().decode("utf-8")
    except (OSError, UnicodeError):
        raise AppError(503, "generation_native_results_unavailable") from None
    if hashlib.sha256(raw.encode()).hexdigest() != origin["sha256"]:
        raise AppError(409, "generation_native_result_migration_requires_review")
    item = {**origin, "text": raw}
    batch = add_round(source, original, item, payload.request_id, actor, db, legacy_run_id=old.id)
    old.metadata_snapshot = {
        **old.metadata_snapshot,
        "native_result_archive": {
            "destination_run_id": source.id,
            "destination_batch_id": batch.id,
            "actor_id": actor.id,
            "at": datetime.now(UTC).isoformat(),
            "reason": "归回原生CLI所属对话，原始记录留档",
        },
    }
    old.deleted_at = datetime.now(UTC)
    old.deleted_by = actor.id
    old.revision += 1
    return batch


def save(project_id, run_id, result_id, payload, actor, db):
    source = own(project_id, run_id, actor, db, True)
    if not re.fullmatch(r"[0-9a-f]{64}", result_id):
        raise AppError(404, "generation_native_result_not_found")
    rounds = source.metadata_snapshot.get("native_results", {})
    if any(
        v.get("save_request_id") == str(payload.request_id) and key != result_id
        for key, v in rounds.items()
    ):
        raise AppError(409, "generation_request_conflict")
    if result_id in rounds:
        return service.projection(source, actor, db)
    if source.status in service.ACTIVE:
        raise AppError(409, "generation_native_result_not_ready")
    sources.recheck(project_id, source.metadata_snapshot, actor, db)
    old = db.scalar(
        select(CaseGenerationRun)
        .where(
            CaseGenerationRun.project_id == project_id,
            CaseGenerationRun.actor_id == actor.id,
            CaseGenerationRun.metadata_snapshot["native_result"]["source_run_id"].as_integer()
            == source.id,
            CaseGenerationRun.metadata_snapshot["native_result"]["id"].astext == result_id,
        )
        .with_for_update()
    )
    if old:
        archive_legacy(project_id, source, old, payload, actor, db)
    else:
        item, original, _ = selected(project_id, source, result_id, actor, db)
        add_round(source, original, item, payload.request_id, actor, db)
    db.commit()
    return service.projection(source, actor, db)


def save_completed_turns(project_id, run_id, identity, finished, actor, db, *, execution_id):
    items = [
        item
        for item in native_candidates.completed_messages(identity)
        if (item["thread_id"], item["turn_id"]) in finished
    ]
    if not items:
        return set()
    source = own(project_id, run_id, actor, db, True)
    execution_row = db.get(
        CaseGenerationChatTurn, execution_id, with_for_update=True, populate_existing=True
    )
    if (
        execution_row is None
        or execution_row.run_id != source.id
        or execution_row.actor_id != actor.id
        or execution_row.status != "RUNNING"
        or execution_row.context.get("native_terminal", {}).get("identity") != identity
    ):
        raise AppError(409, "generation_chat_cancelled")
    main = native_terminal.generation(project_id, run_id, actor, db)
    if main["terminal"]["identity"] != identity:
        raise AppError(409, "generation_terminal_bound_to_batch")
    if source.status in service.ACTIVE:
        return set()
    sources.recheck(project_id, source.metadata_snapshot, actor, db)
    original = db.get(CaseGenerationBatch, main["id"])
    for item in reversed(items):
        if item["id"] in source.metadata_snapshot.get("native_results", {}):
            continue
        raw = generation_json(item["text"])
        if raw is None:
            continue
        try:
            json.loads(raw)
        except (ValueError, RecursionError):
            continue  # Incomplete JSON remains available for manual recovery.
        request_id = uuid5(NAMESPACE_URL, f"verity:generation-native-result:{item['id']}")
        add_round(source, original, item, request_id, actor, db, automatic=True)
    db.commit()
    return {(item["thread_id"], item["turn_id"]) for item in items}


def execute_chat(turn_id, factory):
    with factory() as db:
        turn = db.get(CaseGenerationChatTurn, turn_id)
        native = bool(turn and "native_terminal" in turn.context)
    if native:
        return native_terminal.execute(turn_id, factory, save_completed_turns=save_completed_turns)
    return execution.execute_chat(turn_id, factory)
