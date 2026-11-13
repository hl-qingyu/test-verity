"""Review previews and independent, idempotent candidate transactions."""

import copy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.exc import DataError, IntegrityError

from app.core.errors import AppError
from app.db.models import CaseGenerationApplication, CaseRecord, CaseVersion, ManagedCase, Project
from app.modules.case_generation import contract, service, sources
from app.modules.cases import service as cases
from app.modules.cases.schemas import DESIGN_FIELDS, CaseValues


def current_handling(run, key):
    history = run.handling.get("suggestions", {}).get(key, [])
    return history[-1] if history else None


def preview(project_id, run_id, keys, actor, db):
    run = service.own(project_id, run_id, actor, db)
    mapping = service.suggestion_map(run, db)
    contract.require(keys and len(set(keys)) == len(keys) and set(keys) <= set(mapping))
    meta = cases.metadata(project_id, actor, db)
    target_ids = {
        c["case_id"]
        for data, suggestion in (mapping[k] for k in keys)
        for c in data["cases"]
        if suggestion["case_ref"] == c["case_ref"]
    }
    current = {
        c["id"]: dict(c)
        for c in db.execute(
            cases.case_query(project_id).where(ManagedCase.id.in_(target_ids))
        ).mappings()
    }
    seen, items = set(), []
    category_ids = {c["id"] for c in meta["categories"]}
    collision_keys = service.collision_keys(run, db)
    for key in keys:
        data, s = mapping[key]
        c = next((c for c in data["cases"] if c["case_ref"] == s["case_ref"]), None)
        h = current_handling(run, key)
        design = h["draft"] if h else service.design_for(data, s)
        problem = ""
        if h and h["status"] != "待审阅":
            problem = "候选已处理或应用失败，请先人工核对并保存修订。"
        if h and h.get("categoryId") and h["categoryId"] not in category_ids:
            problem = "草稿分类已删除，请修订此用例并重新选择分类。"
        if (s["basis_status"] == "NEEDS_REVIEW" or key in collision_keys) and not (
            h and h["resolved"] and h["evidenceChecked"]
        ):
            problem = "冲突或依据未核对，需人工确认。"
        target = current.get(c["case_id"]) if c else None
        reviewed = h.get("reviewedTarget") if h else None
        if c:
            expected_version = reviewed["version"] if reviewed else c["design_version"]
            expected_design = reviewed["design"] if reviewed else c["design"]
            if (
                not target
                or target["version"] != expected_version
                or any(target[f] != expected_design[f] for f in DESIGN_FIELDS)
            ):
                problem = "目标设计已变化或删除，需人工核对当前版本。"
            if c["case_id"] in seen:
                problem = "同一批次有同目标的多个操作，需人工选择。"
            seen.add(c["case_id"])
            if target and target["lifecycle"] == "RETIRED" and s["kind"] != "RETIRE":
                problem = "目标已停用，不能自动复用或修改，请先人工恢复或选择新增。"
        matches = (
            [
                dict(v)
                for v in db.execute(
                    cases.case_query(project_id).where(
                        *[getattr(CaseVersion, f) == design[f] for f in DESIGN_FIELDS]
                    )
                ).mappings()
            ]
            if s["kind"] == "NEW"
            else []
        )
        contract.require(len(matches) <= 20000, "generation_duplicate_scope_too_large")
        items.append(
            {
                "key": key,
                "kind": s["kind"],
                "design": design,
                "revision": h["revision"] if h else 0,
                "problem": problem,
                "matches": matches,
                "target": target,
                "categoryId": (h.get("categoryId") if h else None)
                if h and h.get("categoryId") is not None
                else target["category_id"]
                if target
                else None,
            }
        )
    return {"items": items, "revision": meta["revision"], "keys": keys}


def submit(project_id, run_id, payload, actor, db):
    run = service.own(project_id, run_id, actor, db, True)
    raw = payload.model_dump(mode="json")
    # Preserve fingerprints for requests created before explicit batch categories existed.
    for item in raw["items"]:
        if item["category_mode"] == "KEEP":
            item.pop("category_mode")
            item.pop("category_id")
    fingerprint = contract.digest(raw)
    previous = db.scalar(
        select(CaseGenerationApplication).where(
            CaseGenerationApplication.run_id == run_id,
            CaseGenerationApplication.request_id == str(payload.request_id),
        )
    )
    if previous:
        contract.require(
            previous.actor_id == actor.id and previous.fingerprint == fingerprint,
            "generation_request_conflict",
        )
        return complete_submission(previous, actor, db)
    contract.require(len({i.key for i in payload.items}) == len(payload.items))
    sources.recheck(project_id, run.metadata_snapshot, actor, db)
    mapping = service.suggestion_map(run, db)
    contract.require(all(i.key in mapping for i in payload.items))
    items = []
    targets = set()
    for requested in payload.items:
        data, suggestion = mapping[requested.key]
        h = current_handling(run, requested.key)
        contract.require(
            requested.draft_revision == (h["revision"] if h else 0), "generation_changed"
        )
        target = requested.target_id or next(
            (c["case_id"] for c in data["cases"] if c["case_ref"] == suggestion["case_ref"]), None
        )
        collision = target is not None and target in targets
        if target:
            targets.add(target)
        category_id = h.get("categoryId") if h else None
        if requested.category_mode != "KEEP":
            contract.require(
                suggestion["kind"] in {"NEW", "UPDATE"}
                and requested.action in {"apply", "include"},
                "generation_category_not_applicable",
            )
            category_id = requested.category_id if requested.category_mode == "SET" else 0
            # Recheck in each item transaction as a category can disappear after confirmation.
            cases.category(project_id, category_id or None, db)
        items.append(
            {
                **requested.model_dump(),
                "design": h["draft"] if h else service.design_for(data, suggestion),
                "status": "PENDING",
                "error": "",
                "mapping": None,
                "target_collision": collision,
                "category_id": category_id,
            }
        )
    application = CaseGenerationApplication(
        run_id=run_id,
        project_id=project_id,
        actor_id=actor.id,
        request_id=str(payload.request_id),
        fingerprint=fingerprint,
        items=items,
        # This is an audit record, never a queued task. Pending items require this request.
        status="FAILED",
        error_code="generation_submission_interrupted",
    )
    db.add(application)
    db.commit()
    return complete_submission(application, actor, db)


def complete_submission(application, actor, db):
    while execute_item(application.id, db, background=False):
        pass
    run = service.own(application.project_id, application.run_id, actor, db)
    return service.projection(run, actor, db)


def lifecycle(project_id, row, state, reason, actor, db, basis):
    cases.set_case_lifecycle(project_id, row, state, reason, actor, db, basis)


def apply_item(app, item, actor, db):
    contract.require(not item.get("target_collision"), "generation_target_collision")
    run = service.own(app.project_id, app.run_id, actor, db, True)
    sources.recheck(app.project_id, run.metadata_snapshot, actor, db)
    data, s = service.suggestion_map(run, db)[item["key"]]
    h = current_handling(run, s["key"])
    if h and h["status"] in {"已应用", "已复用"}:
        return h.get("mapping"), h["status"]
    contract.require(item["draft_revision"] == (h["revision"] if h else 0), "generation_changed")
    view = preview(app.project_id, app.run_id, [s["key"]], actor, db)["items"][0]
    contract.require(not view["problem"], "generation_item_needs_review")
    contract.require(item["design"] == view["design"], "generation_changed")
    library = cases.lock(app.project_id, actor, db)
    source = {
        "run_id": run.id,
        "suggestion_key": s["key"],
        "draft_revision": item["draft_revision"],
        "application_id": app.id,
        "input_request_id": data["request_id"],
    }
    manual = run.handling.get("manual_suggestions", {}).get(s["key"])
    if manual:
        source["chat_turn_id"] = manual["turn_id"]
    action = item["action"]
    c = next((c for c in data["cases"] if c["case_ref"] == s["case_ref"]), None)
    target_id = item["target_id"] if action in {"reuse", "restore"} else c["case_id"] if c else None
    if action in {"include", "ignore", "restore"}:
        contract.require(item["reason"].strip(), "generation_note_required")
    if action == "ignore":
        return None, "已忽略"
    if action in {"reuse", "restore"} or s["kind"] == "REUSE":
        target = cases.own_case(app.project_id, target_id or c["case_id"], db)
        version = db.scalar(
            select(CaseVersion).where(
                CaseVersion.case_id == target.id, CaseVersion.number == target.current_version
            )
        )
        expected_version = item["target_version"] or (
            view["target"]["version"] if view["target"] else None
        )
        contract.require(
            expected_version and target.current_version == expected_version,
            "generation_case_changed",
        )
        contract.require(
            all(getattr(version, f) == item["design"][f] for f in DESIGN_FIELDS),
            "generation_reuse_mismatch",
        )
        if action == "restore":
            lifecycle(app.project_id, target, "ACTIVE", item["reason"], actor, db, source)
            library.revision += 1
        contract.require(target.lifecycle == "ACTIVE", "generation_retired_match")
        db.add(
            CaseRecord(
                project_id=app.project_id,
                version_id=version.id,
                kind="REVIEW",
                review_status="已审核",
                source_kind="GENERATION",
                recorded_by=actor.id,
                recorded_at=app.created_at,
            )
        )
        library.revision += 1
        return {
            "id": target.id,
            "version": target.current_version,
            "ref": f"application-{app.id}:{s['key']}",
        }, "已复用"
    if s["kind"] == "NEW":
        contract.require(
            not view["matches"] or action == "include", "generation_duplicate_requires_decision"
        )
        cases.category(app.project_id, item["category_id"] or None, db)
        row = cases.insert_case(
            app.project_id,
            library,
            CaseValues.model_validate(item["design"]),
            actor,
            db,
            category_id=item["category_id"] or None,
            request_id=str(uuid5(NAMESPACE_URL, f"generation:{run.id}:{s['key']}")),
            result="未测",
            tester="",
            review_status="已审核",
            source_kind="GENERATION",
            source=source,
            review_at=app.created_at,
        )
        cases.category(app.project_id, row.category_id, db)
    else:
        row = cases.own_case(app.project_id, c["case_id"], db)
        contract.require(
            view["target"] and row.current_version == view["target"]["version"],
            "generation_case_changed",
        )
        if s["kind"] == "RETIRE":
            lifecycle(
                app.project_id, row, "RETIRED", item["reason"] or s["reason"], actor, db, source
            )
        else:
            contract.require(row.lifecycle == "ACTIVE", "generation_retired_match")
            current = view["target"]
            values = CaseValues(
                **item["design"],
                category_id=(item["category_id"] or None)
                if item["category_id"] is not None
                else row.category_id,
                result=current["result"],
                tester=current["tester"],
                review_status=current["review_status"],
            )
            cases.category(app.project_id, values.category_id, db)
            changed = any(item["design"][f] != current[f] for f in DESIGN_FIELDS)
            cases.apply_case_update(
                app.project_id,
                row,
                values,
                actor,
                db,
                source_kind="GENERATION",
                source=source,
                design_review="已审核",
                review_at=app.created_at,
            )
            if not changed:
                # No new design/test record for a no-op; record the human confirmation once.

                version = db.scalar(
                    select(CaseVersion).where(
                        CaseVersion.case_id == row.id, CaseVersion.number == row.current_version
                    )
                )
                db.add(
                    CaseRecord(
                        project_id=app.project_id,
                        version_id=version.id,
                        kind="REVIEW",
                        review_status="已审核",
                        source_kind="GENERATION",
                        recorded_by=actor.id,
                        recorded_at=app.created_at,
                    )
                )
    library.revision += 1
    return {
        "id": row.id,
        "version": row.current_version,
        "ref": f"application-{app.id}:{s['key']}",
    }, "已应用"


def execute(application_id, factory):
    """Drain only legacy queued applications; new confirmations execute inside the API."""
    with factory() as db:
        execute_item(application_id, db, background=True)


def execute_item(application_id, db, *, background):
    app = db.get(CaseGenerationApplication, application_id)
    if not app:
        return False
    project_id, run_id, actor_id = app.project_id, app.run_id, app.actor_id
    item = None
    try:
        from app.db.models import UserAccount

        actor = db.get(UserAccount, actor_id)
        contract.require(actor is not None)
        # Project lock covers preview, duplicate/version checks, write, review and mapping.
        cases.lock(project_id, actor, db)
        app = db.get(
            CaseGenerationApplication,
            application_id,
            with_for_update=True,
            populate_existing=True,
        )
        if not (
            app.status == "RUNNING"
            if background
            else app.status == "FAILED" and app.error_code == "generation_submission_interrupted"
        ):
            db.rollback()
            return False
        index = next((n for n, i in enumerate(app.items) if i["status"] == "PENDING"), None)
        if index is None:
            app.status, app.error_code = "COMPLETED", ""
            db.commit()
            return False
        item = copy.deepcopy(app.items[index])
        mapping, status = apply_item(app, item, actor, db)
        run = service.own(project_id, run_id, actor, db, True)
        h = copy.deepcopy(run.handling)
        history = h.setdefault("suggestions", {}).setdefault(item["key"], [])
        history.append(
            {
                "draft": item["design"],
                "note": item["reason"],
                "status": status,
                "actor": actor.display_name,
                "actor_id": actor.id,
                "time": datetime.now(UTC).isoformat(),
                "revision": (history[-1]["revision"] if history else 0) + 1,
                "evidenceChecked": True,
                "resolved": True,
                **(
                    {"categoryId": item["category_id"]}
                    if item.get("category_id") is not None
                    else {}
                ),
                "categoryMode": item.get("category_mode", "KEEP"),
                "mapping": mapping,
            }
        )
        if mapping:
            h.setdefault("applications", {})[str(mapping["id"])] = mapping
        h["failures"] = [f for f in h.get("failures", []) if f["key"] != item["key"]]
        run.handling, run.revision = h, run.revision + 1
        items = copy.deepcopy(app.items)
        items[index].update(status="COMPLETED", mapping=mapping)
        app.items, app.status, app.updated_at = (
            items,
            ("QUEUED" if background else "FAILED")
            if any(i["status"] == "PENDING" for i in items)
            else "COMPLETED",
            datetime.now(UTC),
        )
        app.error_code = "generation_submission_interrupted" if app.status == "FAILED" else ""
        db.commit()
        return any(i["status"] == "PENDING" for i in items)
    except Exception as exc:
        db.rollback()
        # Keep the same project-before-application lock order when saving failures.
        db.get(Project, project_id, with_for_update=True)
        app = db.get(CaseGenerationApplication, application_id, with_for_update=True)
        if isinstance(exc, IntegrityError | DataError):
            exc = AppError(422, "generation_item_write_invalid")
        if item is None or not isinstance(exc, AppError) or exc.status_code in {401, 403, 503}:
            app.status, app.error_code = "FAILED", "generation_application_paused"
            app.updated_at = datetime.now(UTC)
            db.commit()
            return False
        try:
            actor = db.get(UserAccount, actor_id)
            run = service.own(project_id, run_id, actor, db, True)
            failure = {
                "key": item["key"],
                "caseId": item.get("target_id"),
                "version": item.get("target_version"),
                "reason": exc.detail,
                "time": datetime.now(UTC).isoformat(),
                "application_id": application_id,
                "categoryId": item.get("category_id"),
                "categoryMode": item.get("category_mode", "KEEP"),
            }
            h = copy.deepcopy(run.handling)
            h.setdefault("failure_history", []).append(failure)
            h["failures"] = [f for f in h.get("failures", []) if f["key"] != item["key"]] + [
                failure
            ]
            history = h.setdefault("suggestions", {}).setdefault(item["key"], [])
            old = history[-1] if history else {}
            history.append(
                {
                    **old,
                    "draft": item["design"],
                    "status": "需人工确认",
                    "note": exc.detail,
                    "actor": actor.display_name,
                    "time": failure["time"],
                    "revision": old.get("revision", 0) + 1,
                    "evidenceChecked": False,
                    "resolved": False,
                    **(
                        {"categoryId": item["category_id"]}
                        if item.get("category_id") is not None
                        else {}
                    ),
                    "categoryMode": item.get("category_mode", "KEEP"),
                }
            )
            run.handling, run.revision = h, run.revision + 1
            items = copy.deepcopy(app.items)
            items[index].update(status="FAILED", error=exc.detail)
            app.items, app.status = (
                items,
                ("QUEUED" if background else "FAILED")
                if any(i["status"] == "PENDING" for i in items)
                else "COMPLETED",
            )
            app.error_code = "generation_submission_interrupted" if app.status == "FAILED" else ""
            app.updated_at = datetime.now(UTC)
            db.commit()
            return any(i["status"] == "PENDING" for i in items)
        except Exception:
            db.rollback()
            db.get(Project, project_id, with_for_update=True)
            app = db.get(CaseGenerationApplication, application_id, with_for_update=True)
            app.status, app.error_code = "FAILED", "generation_failure_audit_unavailable"
            app.updated_at = datetime.now(UTC)
            db.commit()
    return False
