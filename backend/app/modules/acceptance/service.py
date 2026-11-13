"""Independent human acceptance and record-based metrics for the five analysis modules."""

import copy
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.db.models import AnalysisAcceptance
from app.modules.acceptance import schemas, sources
from app.modules.projects.service import access_project


def require(condition, code="acceptance_invalid"):
    if not condition:
        raise AppError(422, code)


def metrics(record, state):
    items = record["items"]
    judgments = record.get("judgments", {})
    result = dict.fromkeys(
        [
            "total",
            "valid",
            "invalid",
            "dismissed",
            "needs_review",
            "unreviewed",
            "evidence_reviewed",
            "evidence_sufficient",
            "false_positives",
            "duplicates",
            "regression_reviewed",
            "regression_usable",
            "repair_total",
            "repair_adopted",
            "baseline_total",
            "baseline_covered",
            "missing",
            "scope_reviewed",
            "records",
            "concluded",
        ],
        0,
    )
    result["records"] = 1
    result["scope_reviewed"] = int(state.get("scope_reviewed", False))
    result["concluded"] = int(state.get("conclusion", "UNREVIEWED") != "UNREVIEWED")
    result["adopted"] = len(record["adopted"])
    for key, item in items.items():
        judgment = judgments.get(key, {})
        verdict = judgment.get("verdict", "UNREVIEWED")
        if item["group"] == "regression_scope":
            result["regression_reviewed"] += judgment.get("usable") is not None
            result["regression_usable"] += judgment.get("usable") is True
            continue
        if item["group"] == "notes":
            continue
        result["total"] += 1
        result[
            {
                "VALID": "valid",
                "INVALID": "invalid",
                "DISMISSED": "dismissed",
                "NEEDS_REVIEW": "needs_review",
                "UNREVIEWED": "unreviewed",
            }[verdict]
        ] += 1
        evidence = judgment.get("evidence", "UNREVIEWED")
        result["evidence_reviewed"] += evidence != "UNREVIEWED"
        result["evidence_sufficient"] += evidence == "SUFFICIENT"
        result["false_positives"] += (
            verdict == "INVALID" and judgment.get("reason") == "FALSE_POSITIVE"
        )
        result["duplicates"] += verdict == "INVALID" and judgment.get("reason") == "DUPLICATE"
        if (
            item["group"] == "findings"
            and item.get("repair")
            and item.get("kind") in {"MISMATCH", "MISSING", "QUALITY"}
        ):
            result["repair_total"] += 1
            result["repair_adopted"] += key in record["adopted"]
    for criterion in state.get("criteria", []):
        result["missing"] += criterion["critical"] and criterion["result"] == "MISSING"
        result["baseline_total"] += criterion["baseline"]
        result["baseline_covered"] += (
            criterion["baseline"]
            and criterion["result"] == "COVERED"
            and judgments.get(criterion["matched_key"], {}).get("verdict") == "VALID"
        )
    return result


def own(module, project_id, record_id, actor, db):
    access_project(project_id, actor, db)
    source = sources.records(module, project_id, db, record_id, full=True).get(record_id)
    if source is None:
        raise AppError(404, "acceptance_report_unavailable")
    return source


def saved(module, project_id, record_id, db):
    return db.scalar(
        select(AnalysisAcceptance).where(
            AnalysisAcceptance.project_id == project_id,
            AnalysisAcceptance.module == module,
            AnalysisAcceptance.record_id == record_id,
        )
    )


def response(module, project_id, record_id, source, row):
    stale = row is not None and row.source_token != source["token"]
    state = (
        copy.deepcopy(row.state) if row is not None and not stale else schemas.State().model_dump()
    )
    state["items"] = source["judgments"]
    return {
        "project_id": project_id,
        "module": module,
        "record_id": record_id,
        "title": source["title"],
        "source_token": source["token"],
        "revision": row.revision if row else 0,
        "stale": stale,
        "state": state,
        "items": list(source["items"].values()),
        "metrics": metrics(source, state),
        "history": row.history if row else [],
    }


def detail(module, project_id, record_id, actor, db):
    source = own(module, project_id, record_id, actor, db)
    return response(module, project_id, record_id, source, saved(module, project_id, record_id, db))


def save(module, project_id, record_id, payload, actor, db):
    access_project(project_id, actor, db, lock=True)
    db.scalar(
        select(sources.MODELS[module])
        .where(
            sources.MODELS[module].id == record_id, sources.MODELS[module].project_id == project_id
        )
        .with_for_update()
    )
    source = own(module, project_id, record_id, actor, db)
    row = saved(module, project_id, record_id, db)
    if payload.revision != (row.revision if row else 0) or payload.source_token != source["token"]:
        raise AppError(409, "acceptance_changed")
    state = payload.state.model_dump()
    if state["items"] != source["judgments"]:
        raise AppError(409, "acceptance_use_detail")
    require(set(state["items"]) <= set(source["items"]))
    for key, judgment in state["items"].items():
        item = source["items"][key]
        invalid = judgment["verdict"] == "INVALID"
        require(bool(judgment["reason"]) == invalid)
        require(judgment["usable"] is None or item["group"] == "regression_scope")
        require(judgment["usable"] is not True or judgment["verdict"] == "VALID")
        require(judgment["reason"] != "FALSE_POSITIVE" or module in {"code", "changes", "coverage"})
    identities, titles = set(), set()
    for criterion in state["criteria"]:
        title = " ".join(criterion["title"].split())
        basis = " ".join(criterion["basis"].split())
        require(
            title and basis and criterion["id"] not in identities and (title, basis) not in titles,
            "acceptance_criterion_duplicate",
        )
        identities.add(criterion["id"])
        titles.add((title, basis))
        if criterion["result"] == "COVERED":
            require(
                state["items"].get(criterion["matched_key"], {}).get("verdict") == "VALID",
                "acceptance_coverage_unverified",
            )
        else:
            require(not criterion["matched_key"])
    require(not state["scope_reviewed"] or state["note"].strip(), "acceptance_note_required")
    require(
        state["conclusion"] == "UNREVIEWED" or state["scope_reviewed"] and state["note"].strip(),
        "acceptance_scope_required",
    )
    if row is None:
        row = AnalysisAcceptance(
            project_id=project_id,
            module=module,
            record_id=record_id,
            updated_by=actor.id,
            source_token=source["token"],
            state={},
            history=[],
            revision=0,
        )
        db.add(row)
    if row.state != state or row.source_token != source["token"]:
        now = datetime.now(UTC)
        row.state, row.source_token, row.revision, row.updated_by, row.updated_at = (
            state,
            source["token"],
            row.revision + 1,
            actor.id,
            now,
        )
        row.history = [
            *row.history,
            {
                "revision": row.revision,
                "actor_id": actor.id,
                "actor": actor.display_name,
                "time": now.isoformat(),
                "source_token": source["token"],
                "state": copy.deepcopy(state),
            },
        ]
    db.commit()
    return response(module, project_id, record_id, source, row)


def project_summary(project_id, actor, db):
    if actor.platform_role != "ADMIN":
        raise AppError(403, "admin_required")
    if project_id is not None:
        access_project(project_id, actor, db)
    query = select(
        AnalysisAcceptance.project_id,
        AnalysisAcceptance.module,
        AnalysisAcceptance.record_id,
        AnalysisAcceptance.source_token,
        AnalysisAcceptance.state,
    )
    if project_id is not None:
        query = query.where(AnalysisAcceptance.project_id == project_id)
    rows = {(r["project_id"], r["module"], r["record_id"]): r for r in db.execute(query).mappings()}
    result = []
    for module in sources.MODELS:
        try:
            with db.begin_nested():
                records = sources.records(module, project_id, db)
        except (SQLAlchemyError, ValueError, TypeError, KeyError):
            result.append({"module": module, "available": False, "metrics": None})
            continue
        total = metrics({"items": {}, "adopted": set()}, {})
        total["records"] = 0
        for identity, record in records.items():
            row = rows.get((record["project_id"], module, identity))
            state = row["state"] if row and row["source_token"] == record["token"] else {}
            for key, value in metrics(record, state).items():
                total[key] += value
        result.append({"module": module, "available": True, "metrics": total})
    return result
