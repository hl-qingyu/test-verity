import copy
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import CaseGenerationChatTurn
from app.modules.ai.service import analysis_configuration, configuration_snapshot
from app.modules.case_generation import contract, service, sources


def view(turn, actor):
    return {
        "id": turn.id,
        "function_key": turn.function_key,
        "finding_key": turn.finding_key,
        "question": turn.question,
        "answer": turn.answer,
        "status": turn.status,
        "error_code": turn.error_code,
        "actor_id": turn.actor_id,
        "can_cancel": turn.actor_id == actor.id and turn.status in service.ACTIVE,
        "created_at": turn.created_at.isoformat(),
    }


def listing(project_id, run_id, function_key, actor, db, before=None):
    service.own(project_id, run_id, actor, db)
    query = select(CaseGenerationChatTurn).where(
        CaseGenerationChatTurn.run_id == run_id, CaseGenerationChatTurn.function_key == function_key
    )
    if before:
        query = query.where(CaseGenerationChatTurn.id < before)
    rows = list(db.scalars(query.order_by(CaseGenerationChatTurn.id.desc()).limit(51)))
    return {"items": [view(t, actor) for t in reversed(rows[:50])], "has_more": len(rows) > 50}


def enqueue(project_id, run_id, payload, actor, db):
    run = service.own(project_id, run_id, actor, db, True)
    previous = db.scalar(
        select(CaseGenerationChatTurn).where(
            CaseGenerationChatTurn.run_id == run_id,
            CaseGenerationChatTurn.request_id == str(payload.request_id),
        )
    )
    if previous:
        contract.require(
            previous.actor_id == actor.id
            and previous.question == payload.question
            and previous.function_key == payload.function_key
            and previous.finding_key == payload.finding_key,
            "generation_request_conflict",
        )
        return view(previous, actor)
    pairs = service.reports(run, db)
    contract.require(pairs, "generation_report_not_ready")
    fs, finding_functions = service.function_views(run, db)
    contract.require(not payload.function_key or payload.function_key in fs)
    selected = {**service.suggestion_map(run, db), **service.question_map(run, db)}
    contract.require(
        not payload.finding_key
        or payload.finding_key in selected
        and (
            not payload.function_key
            or finding_functions[payload.finding_key] == payload.function_key
            or selected[payload.finding_key][1]["function_ref"] == payload.function_key
        )
    )
    contract.require(payload.question.strip())
    contract.require(
        not db.scalar(
            select(CaseGenerationChatTurn.id).where(
                CaseGenerationChatTurn.run_id == run_id,
                CaseGenerationChatTurn.function_key == payload.function_key,
                CaseGenerationChatTurn.status.in_(service.ACTIVE),
            )
        ),
        "generation_chat_busy",
    )
    sources.recheck(project_id, run.metadata_snapshot, actor, db)
    config, _ = analysis_configuration(actor, db)
    messages = []
    for turn in db.scalars(
        select(CaseGenerationChatTurn)
        .where(
            CaseGenerationChatTurn.run_id == run_id,
            CaseGenerationChatTurn.function_key == payload.function_key,
            CaseGenerationChatTurn.status == "COMPLETED",
        )
        .order_by(CaseGenerationChatTurn.id)
    ):
        messages.extend(
            [
                {"role": "user", "content": turn.question},
                {"role": "assistant", "content": turn.answer},
            ]
        )
    selected_items = {
        k: copy.deepcopy(v[1])
        for k, v in selected.items()
        if not payload.function_key
        or finding_functions[k] == payload.function_key
        or v[1]["function_ref"] == payload.function_key
    }
    handling = copy.deepcopy(run.handling)
    if payload.function_key:
        handling["suggestions"] = {
            k: v for k, v in handling.get("suggestions", {}).items() if k in selected_items
        }
        handling["decisions"] = [
            d for d in handling.get("decisions", []) if d["questionKey"] in selected_items
        ]
        handling.pop("applications", None)
        handling["failures"] = [
            f for f in handling.get("failures", []) if f["key"] in selected_items
        ]
        handling["failure_history"] = [
            f for f in handling.get("failure_history", []) if f["key"] in selected_items
        ]
    context = {
        "run_id": run_id,
        "function_key": payload.function_key,
        "finding_key": payload.finding_key,
        "inputs": [copy.deepcopy(i) for i, _ in pairs],
        "items": selected_items,
        "evidence": [
            copy.deepcopy(e)
            for _, r in pairs
            for e in r["evidence"]
            if any(e["key"] in item["evidence_refs"] for item in selected_items.values())
        ],
        "handling": handling,
        "messages": messages,
    }
    contract.require(
        len(json.dumps(context, ensure_ascii=False).encode()) <= contract.LIMIT,
        "generation_chat_too_large",
    )
    row = CaseGenerationChatTurn(
        run_id=run_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        function_key=payload.function_key,
        finding_key=payload.finding_key,
        question=payload.question.strip(),
        context=context,
        ai_config=configuration_snapshot(config),
    )
    db.add(row)
    db.commit()
    return view(row, actor)


def cancel(project_id, run_id, turn_id, actor, db):
    service.own(project_id, run_id, actor, db, True)
    turn = db.get(CaseGenerationChatTurn, turn_id, with_for_update=True)
    contract.require(
        turn and turn.run_id == run_id and turn.actor_id == actor.id, "generation_owner_only"
    )
    if turn.status in service.ACTIVE:
        turn.status, turn.updated_at = "CANCELLED", datetime.now(UTC)
        db.commit()
    return view(turn, actor)


def create_draft(project_id, run_id, turn_id, payload, actor, db):
    run = service.own(project_id, run_id, actor, db, True)
    turn = db.get(CaseGenerationChatTurn, turn_id)
    contract.require(
        turn and turn.run_id == run_id and turn.status == "COMPLETED", "generation_reply_not_ready"
    )
    sources.recheck(project_id, run.metadata_snapshot, actor, db)
    contract.require(
        payload.note.strip()
        and all(getattr(payload.design, k).strip() for k in ("title", "steps", "expected"))
    )
    h = copy.deepcopy(run.handling)
    key = f"manual:{payload.request_id}"
    prior = h.get("manual_suggestions", {}).get(key)
    fingerprint = contract.digest(payload.model_dump(mode="json"))
    if prior:
        contract.require(
            prior["fingerprint"] == fingerprint and prior["turn_id"] == turn_id,
            "generation_request_conflict",
        )
        return service.projection(run, actor, db)
    chosen = None
    for data, report in service.reports(run, db):
        ev = {e["key"]: e for e in report["evidence"]}
        if set(payload.evidence_refs) <= set(ev):
            selected = [ev[k] for k in payload.evidence_refs]
            mats = {m["snapshot_ref"]: m for m in data["materials"]}
            decisions = {d["decision_ref"]: d for d in data["decisions"]}
            business = [
                e
                for e in selected
                if e["kind"] == "MATERIAL"
                and mats[e["target_ref"]]["kind"] != "CODE"
                and e["side"] in {"CURRENT", "SUPPLEMENT", "CONTEXT"}
                or e["kind"] == "DECISION"
                and decisions[e["target_ref"]]["applicability"] == "VERIFIED_CURRENT"
            ]
            contract.require(business, "generation_business_basis_required")
            chosen = data, selected
            break
    contract.require(chosen, "generation_business_basis_required")
    data, selected = chosen
    function_ref = data["batch"]["function_refs"][0]
    suggestion = {
        "key": key,
        "kind": "NEW",
        "function_ref": function_ref,
        "scenario_refs": [],
        "case_ref": None,
        "base_version": None,
        "design": payload.design.model_dump(),
        "changes": [],
        "reason": f"从已完成对话#{turn_id}人工填写草案：{payload.note}",
        "priority_reason": "人工设计建议",
        "evidence_refs": payload.evidence_refs,
        "basis_status": "SUPPORTED",
    }
    h.setdefault("manual_suggestions", {})[key] = {
        "input": copy.deepcopy(data),
        "suggestion": suggestion,
        "evidence": copy.deepcopy(selected),
        "turn_id": turn_id,
        "fingerprint": fingerprint,
        "actor_id": actor.id,
        "at": datetime.now(UTC).isoformat(),
    }
    h.setdefault("suggestions", {})[key] = [
        {
            "draft": payload.design.model_dump(),
            "note": payload.note,
            "status": "待审阅",
            "actor": actor.display_name,
            "time": datetime.now(UTC).isoformat(),
            "revision": 1,
            "evidenceChecked": True,
            "resolved": True,
        }
    ]
    run.handling, run.revision = h, run.revision + 1
    db.commit()
    return service.projection(run, actor, db)
