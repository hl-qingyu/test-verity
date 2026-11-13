"""Fixed report identities and scalar item projections; no model calls or business writes."""

import hashlib
import json

from sqlalchemy import Text, cast, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB

from app.db.models import (
    CaseAnalysisRun,
    CaseGenerationBatch,
    CaseGenerationRun,
    ChangeAnalysisTask,
    CodeAnalysisTask,
    Project,
    RequirementRiskReport,
)
from app.modules.projects.analysis_summary import states

MODELS = {
    "requirements": RequirementRiskReport,
    "generate": CaseGenerationRun,
    "coverage": CaseAnalysisRun,
    "code": CodeAnalysisTask,
    "changes": ChangeAnalysisTask,
}
GROUPS = {
    "requirements": ["risks"],
    "generate": ["suggestions"],
    "coverage": ["findings", "notes"],
    "code": ["findings"],
    "changes": [
        "function_impacts",
        "code_impacts",
        "case_impacts",
        "risks",
        "historical_reviews",
        "regression_scope",
    ],
}


def projection(report, group, full, fixed_input=None):
    entries = func.jsonb_array_elements(
        func.coalesce(report[group], cast(literal("[]"), JSONB))
    ).table_valued("value")
    item = cast(entries.c.value, JSONB)
    pairs = [
        "key",
        item["key"],
        "kind",
        item["kind"],
        "repair",
        func.coalesce(item["suggestion"].astext != "", False),
    ]
    if full:
        pairs += [
            "title",
            func.coalesce(item["title"].astext, item["design"]["title"].astext, item["key"].astext),
            "description",
            func.coalesce(item["description"].astext, item["reason"].astext, ""),
            "suggestion",
            func.coalesce(item["suggestion"].astext, ""),
        ]
        if fixed_input is not None:
            targets = func.jsonb_array_elements(
                func.coalesce(fixed_input["cases"], cast(literal("[]"), JSONB))
            ).table_valued("value")
            target = cast(targets.c.value, JSONB)
            baseline = (
                select(target["design"])
                .select_from(targets)
                .where(target["case_ref"].astext == item["case_ref"].astext)
                .correlate_except(targets)
                .limit(1)
                .scalar_subquery()
            )
            pairs += [
                "original_design",
                func.coalesce(func.nullif(item["design"], cast(literal("null"), JSONB)), baseline),
                "changes",
                item["changes"],
            ]
    return (
        select(func.jsonb_agg(func.jsonb_build_object(*pairs)))
        .select_from(entries)
        .correlate_except(entries)
        .scalar_subquery()
        .label(group)
    )


def records(module, project_id, db, record_id=None, full=False):
    model = MODELS[module]
    if module == "generate":
        batch = CaseGenerationBatch
        query = (
            select(
                model.id,
                model.project_id,
                model.title,
                batch.id.label("batch_id"),
                batch.status,
                func.encode(
                    func.sha256(func.convert_to(cast(batch.report, Text), "UTF8")), "hex"
                ).label("token"),
                projection(batch.report, "suggestions", full, batch.input_snapshot),
                states(model.handling["suggestions"], history=True).label("handling"),
                states(model.handling["suggestions"], "evidenceChecked", history=True).label(
                    "checked"
                ),
            )
            .join(batch, batch.run_id == model.id)
            .where(batch.status == "COMPLETED")
            .order_by(batch.id)
        )
    else:
        query = select(
            model.id,
            model.project_id,
            model.title,
            func.encode(
                func.sha256(func.convert_to(cast(model.report, Text), "UTF8")), "hex"
            ).label("token"),
            *[projection(model.report, g, full) for g in GROUPS[module]],
        )
        if module != "requirements":
            query = query.where(model.status == "COMPLETED")
        if module == "coverage":
            query = query.add_columns(
                states(model.handling, "applied").label("handling"),
                states(model.handling, "state").label("review_status"),
                states(model.handling, "draft_revision").label("checked"),
            )
        else:
            query = query.add_columns(states(model.handling).label("review_status"))
    if project_id is not None:
        query = query.where(model.project_id == project_id)
    if record_id is not None:
        query = query.where(model.id == record_id)
    query = query.where(
        model.deleted_at.is_(None),
        model.project_id.in_(select(Project.id).where(Project.deleted_at.is_(None))),
    )
    output = {}
    for row in db.execute(query).mappings():
        record = output.setdefault(
            row["id"],
            {
                "id": row["id"],
                "project_id": row["project_id"],
                "title": row["title"],
                "tokens": [],
                "items": {},
                "adopted": set(),
                "judgments": {},
            },
        )
        record["tokens"].append(row["token"])
        for group in GROUPS[module]:
            for item in row[group] or []:
                key = item.get("key")
                if (
                    not isinstance(key, str)
                    or not key
                    or (
                        module == "generate"
                        and (item.get("kind") not in {"NEW", "UPDATE"} or key.startswith("manual:"))
                    )
                ):
                    continue
                identity = group + ":" + key
                if full and module == "generate":
                    design = dict(item.pop("original_design", None) or {})
                    for change in item.pop("changes", None) or []:
                        design[change["field"]] = change["after"]
                    labels = {
                        "module": "功能模块",
                        "structure": "功能结构",
                        "case_type": "用例类型",
                        "priority": "优先级",
                        "description": "用例描述",
                        "title": "验证子项",
                        "preconditions": "前置条件",
                        "steps": "操作步骤",
                        "expected": "预期结果",
                        "data_requirements": "数据要求",
                        "cleanup": "清理要求",
                        "remark": "备注",
                    }
                    if design:
                        item["description"] = "\n\n".join(
                            f"{label}：\n{design[field]}"
                            for field, label in labels.items()
                            if design.get(field)
                        )
                        item["title"] = design.get("title") or item["title"]
                record["items"][identity] = {
                    **item,
                    "key": identity,
                    "source_key": key,
                    "group": group,
                }
                handling = row.get("handling") or {}
                status = (
                    handling.get(key)
                    if module == "generate"
                    else (row.get("review_status") or {}).get(key)
                )
                record["judgments"][identity] = judgment(
                    module, status, (row.get("checked") or {}).get(key), handling.get(key), group
                )
                if module == "generate" and handling.get(key) == "已应用":
                    record["adopted"].add(identity)
                if (
                    module == "coverage"
                    and item.get("kind") not in {"SETUP", "QUESTION"}
                    and item["repair"]
                    and (handling.get(key) or {}).get("kind") in {"NEW", "UPDATE"}
                ):
                    record["adopted"].add(identity)
        record["token"] = hashlib.sha256(json.dumps(record["tokens"]).encode()).hexdigest()
    return output


def judgment(module, status, checked=False, applied=None, group=""):
    result = {
        "verdict": "UNREVIEWED",
        "reason": "",
        "evidence": "UNREVIEWED",
        "usable": None,
        "note": "",
    }
    if group == "regression_scope":
        if status in {"ACCEPTED", "REJECTED"}:
            result.update(
                verdict="VALID" if status == "ACCEPTED" else "DISMISSED",
                usable=status == "ACCEPTED",
            )
        elif status == "DEFERRED":
            result["verdict"] = "NEEDS_REVIEW"
        return result
    recognized = {
        "requirements": {"NEEDS_INFO", "RESOLVED"},
        "code": {"CONFIRMED", "RESOLVED"},
        "changes": {"CONFIRMED", "RESOLVED"},
        "coverage": {"已确认待处理", "已解决"},
        "generate": {"已应用", "已复用"},
    }
    if status in recognized[module] or module == "coverage" and applied:
        result["verdict"] = "VALID"
    elif status == "FALSE_POSITIVE":
        result.update(verdict="INVALID", reason="FALSE_POSITIVE")
    elif status in {"NOT_APPLICABLE", "不适用", "已忽略"}:
        result["verdict"] = "DISMISSED"
    elif status in {"NEEDS_EVIDENCE", "需人工确认"}:
        result["verdict"] = "NEEDS_REVIEW"
    if module == "generate" and checked is True or module == "coverage" and checked and applied:
        result["evidence"] = "SUFFICIENT"
    elif status == "NEEDS_EVIDENCE":
        result["evidence"] = "INSUFFICIENT"
    return result
