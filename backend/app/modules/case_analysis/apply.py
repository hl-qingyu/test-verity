import copy
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.core.errors import AppError
from app.db.models import CaseAnalysisApplication, CaseRecord, UserAccount
from app.modules.case_analysis import contract, service
from app.modules.cases import service as cases
from app.modules.cases.schemas import DESIGN_FIELDS, CaseValues


def preview(project_id, run_id, actor, db):
    run = service.own(project_id, run_id, actor, db)
    result = []
    for key, h in run.handling.items():
        if not isinstance(h, dict) or not h.get("draft") or h.get("applied"):
            continue
        matches = (
            [
                dict(c)
                for c in db.execute(cases.case_query(project_id)).mappings()
                if all(c[f] == h["draft"][f] for f in DESIGN_FIELDS)
            ]
            if not h.get("target")
            else []
        )
        result.append(
            {
                "key": key,
                "draft_revision": h["draft_revision"],
                "design": h["draft"],
                "target": h.get("target"),
                "category_id": h.get("category_id"),
                "matches": matches,
            }
        )
    return {"items": result}


def submit(project_id, run_id, payload, actor, db):
    run = service.own(project_id, run_id, actor, db, True)
    fingerprint = contract.digest(payload.model_dump(mode="json"))
    prior = db.scalar(
        select(CaseAnalysisApplication).where(
            CaseAnalysisApplication.run_id == run_id,
            CaseAnalysisApplication.request_id == str(payload.request_id),
        )
    )
    if prior:
        contract.require(prior.fingerprint == fingerprint)
        return service.detail(project_id, run_id, actor, db)
    contract.require(len({i.key for i in payload.items}) == len(payload.items))
    fixed = []
    for i in payload.items:
        h = run.handling.get(i.key, {})
        contract.require(
            h.get("draft") and not h.get("applied") and h["draft_revision"] == i.draft_revision
        )
        cases.category(project_id, i.category_id or None, db)
        fixed.append(
            {
                **i.model_dump(mode="json"),
                "design": h["draft"],
                "target": h.get("target"),
                "status": "PENDING",
            }
        )
    contract.require(
        not db.scalar(
            select(CaseAnalysisApplication.id).where(
                CaseAnalysisApplication.run_id == run_id,
                CaseAnalysisApplication.status.in_(service.ACTIVE),
            )
        ),
        "case_analysis_application_busy",
    )
    db.add(
        CaseAnalysisApplication(
            run_id=run_id,
            project_id=project_id,
            actor_id=actor.id,
            request_id=str(payload.request_id),
            fingerprint=fingerprint,
            items=fixed,
            status="QUEUED",
        )
    )
    db.commit()
    return service.detail(project_id, run_id, actor, db)


def apply_one(app, item, actor, db):
    library = cases.lock(app.project_id, actor, db)
    run = service.own(app.project_id, app.run_id, actor, db, True)
    h = run.handling.get(item["key"], {})
    contract.require(
        h.get("draft_revision") == item["draft_revision"]
        and h.get("draft") == item["design"]
        and not h.get("applied"),
        "case_analysis_draft_changed",
    )
    contract.require(all(item["design"][f].strip() for f in ("title", "steps", "expected")))
    rows = [dict(c) for c in db.execute(cases.case_query(app.project_id)).mappings()]
    target = item.get("target")
    current = next((c for c in rows if target and c["id"] == target["id"]), None)
    if target:
        contract.require(
            current
            and current["version"] == target["version"]
            and current["lifecycle"] == "ACTIVE"
            and all(current[f] == target[f] for f in DESIGN_FIELDS),
            "case_analysis_target_changed",
        )
    matches = (
        [c for c in rows if all(c[f] == item["design"][f] for f in DESIGN_FIELDS)]
        if not target
        else []
    )
    source = {"analysis_id": run.id, "key": item["key"], "application_id": app.id}
    if not target and matches and item["action"] != "include":
        current = next((c for c in matches if c["id"] == item["target_id"]), None)
        contract.require(
            item["action"] == "reuse"
            and current
            and current["version"] == item["target_version"]
            and current["lifecycle"] == "ACTIVE",
            "case_analysis_duplicate_decision_required",
        )
        db.add(
            CaseRecord(
                project_id=app.project_id,
                version_id=current["version_id"],
                kind="REVIEW",
                review_status="已审核",
                source_kind="CASE_REVIEW",
                recorded_by=actor.id,
                recorded_at=app.created_at,
            )
        )
        library.revision += 1
        return {"case_id": current["id"], "version": current["version"], "kind": "REUSE"}
    contract.require(
        item["action"] != "reuse" and (not matches or item["reason"].strip()),
        "case_analysis_duplicate_decision_required",
    )
    cases.category(app.project_id, item["category_id"] or None, db)
    if not target:
        row = cases.insert_case(
            app.project_id,
            library,
            CaseValues(**item["design"]),
            actor,
            db,
            category_id=item["category_id"] or None,
            request_id=str(uuid5(NAMESPACE_URL, f"case-review:{run.id}:{item['key']}")),
            result="未测",
            tester="",
            review_status="已审核",
            source=source,
            source_kind="CASE_REVIEW",
            review_at=app.created_at,
        )
    else:
        row = cases.own_case(app.project_id, current["id"], db)
        changed = any(current[f] != item["design"][f] for f in DESIGN_FIELDS)
        values = CaseValues(
            **item["design"],
            category_id=item["category_id"] or None,
            result=current["result"],
            tester=current["tester"],
            review_status=current["review_status"],
        )
        cases.apply_case_update(
            app.project_id,
            row,
            values,
            actor,
            db,
            source_kind="CASE_REVIEW",
            source=source,
            design_review="已审核",
            review_at=app.created_at,
        )
        if not changed:
            db.add(
                CaseRecord(
                    project_id=app.project_id,
                    version_id=current["version_id"],
                    kind="REVIEW",
                    review_status="已审核",
                    source_kind="CASE_REVIEW",
                    recorded_by=actor.id,
                    recorded_at=app.created_at,
                )
            )
    library.revision += 1
    return {
        "case_id": row.id,
        "version": row.current_version,
        "kind": "UPDATE" if target else "NEW",
    }


def execute(app_id, factory):
    while True:
        try:
            with factory() as db:
                app = db.get(CaseAnalysisApplication, app_id)
                if not app or app.status != "RUNNING":
                    return
                project_id, run_id, actor_id = app.project_id, app.run_id, app.actor_id
                actor = db.get(UserAccount, actor_id)
                service.own(project_id, run_id, actor, db)
                index = next(
                    (i for i, item in enumerate(app.items) if item["status"] == "PENDING"), None
                )
                if index is None:
                    app.status, app.updated_at = "COMPLETED", datetime.now(UTC)
                    db.commit()
                    return
                item = copy.deepcopy(app.items[index])
                mapping = apply_one(app, item, actor, db)
                app = db.get(CaseAnalysisApplication, app_id, with_for_update=True)
                run = service.own(project_id, run_id, actor, db, True)
                data, handling = copy.deepcopy(app.items), copy.deepcopy(run.handling)
                data[index].update(status="SUCCESS", mapping=mapping)
                handling[item["key"]]["applied"] = mapping
                app.items, app.updated_at = data, datetime.now(UTC)
                run.handling, run.revision, run.updated_at = (
                    handling,
                    run.revision + 1,
                    datetime.now(UTC),
                )
                db.commit()
        except Exception as exc:
            code = exc.detail if isinstance(exc, AppError) else "case_analysis_application_failed"
            with factory() as db:
                app = db.get(CaseAnalysisApplication, app_id, with_for_update=True)
                if not app or app.status != "RUNNING":
                    return
                if isinstance(exc, AppError) and exc.status_code not in (401, 403):
                    data = copy.deepcopy(app.items)
                    data[index].update(status="FAILED", error_code=code)
                    app.items = data
                else:
                    app.status, app.error_code = "FAILED", code
                db.commit()
            if app.status == "FAILED":
                return
