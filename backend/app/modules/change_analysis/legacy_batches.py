"""Read and locally revalidate historical change batches without model calls."""

import copy
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime

from pydantic import ValidationError

from app.core.errors import AppError
from app.modules.change_analysis import artifacts, batch_merge, comparison, contract, evidence
from app.modules.requirements.risk_service import json_object

GROUPS = (
    "changes",
    "function_impacts",
    "code_impacts",
    "case_impacts",
    "risks",
    "historical_reviews",
    "regression_scope",
    "evidence",
    "chains",
    "limitations",
)
RESULT_REFS = {
    "evidence_refs",
    "basis_refs",
    "expected_basis_refs",
    "before_refs",
    "after_refs",
    "change_refs",
    "causal_change_refs",
    "risk_refs",
    "priority_risk_refs",
    "limitation_refs",
    "chain_refs",
}


def _input_for_v2(data, batch):
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    selected, pairs = defaultdict(set), []
    mapping_keys = {tuple(k) for k in batch["mappings"]}
    for pair in data["comparison_pairs"]:
        mappings = [
            m for m in pair["unit_mappings"] if (pair["pair_id"], m["mapping_id"]) in mapping_keys
        ]
        if not mappings:
            continue
        paths = set()
        for side in ("before", "after"):
            ref = pair[side + "_ref"]
            selected[ref].update(uid for m in mappings for uid in m[side + "_unit_ids"])
            paths.update(
                u["path"] for u in snapshots[ref]["units"] if u["unit_id"] in selected[ref]
            )
        pairs.append(
            {
                **pair,
                "scope": sorted(paths),
                "unit_mappings": mappings,
                "text_diffs": [
                    d
                    for d in pair["text_diffs"]
                    if (pair["pair_id"], d["mapping_ref"]) in mapping_keys
                ],
            }
        )
    context_refs = []
    for ref, ids in batch["context_units"].items():
        selected[ref].update(ids)
        context_refs.append(ref)
    histories = [h for h in data["historical_items"] if h["history_ref"] in batch["history_refs"]]
    for history in histories:
        for ref in history["basis_refs"]:
            if ref not in selected:
                selected[ref].update(u["unit_id"] for u in snapshots[ref]["units"])
                context_refs.append(ref)
    result = {
        **data,
        "comparison_pairs": pairs,
        "snapshots": [
            {**s, "units": [u for u in s["units"] if u["unit_id"] in selected[s["snapshot_ref"]]]}
            for s in data["snapshots"]
            if s["snapshot_ref"] in selected
        ],
        "context_refs": list(dict.fromkeys(context_refs)),
        "cases": [c for c in data["cases"] if c["case_ref"] in batch["case_refs"]],
        "historical_items": histories,
        "targets": [t for t in data["targets"] if t not in batch.get("blocked_targets", [])],
        "input_limitations": [*data["input_limitations"], *batch.get("limitations", [])],
    }
    return copy.deepcopy(result)


def input_for(data, batch):
    if batch.get("plan_version") == 2:
        return _input_for_v2(data, batch)
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    selections = defaultdict(set)
    for pair, mapping in batch["mappings"]:
        selections[pair].add(mapping)
    # Keep the opposite code role available to the existing strict consistency contract.
    if "FRONTEND_BACKEND_MISMATCH" in data["targets"]:
        for p in data["comparison_pairs"]:
            if p["unit_mappings"] and p["pair_id"] not in selections:
                selections[p["pair_id"]].add(p["unit_mappings"][0]["mapping_id"])
    pairs, selected = [], {}
    for p in data["comparison_pairs"]:
        if p["pair_id"] not in selections:
            continue
        mappings = [m for m in p["unit_mappings"] if m["mapping_id"] in selections[p["pair_id"]]]
        paths = set()
        for side in ("before", "after"):
            ref = p[side + "_ref"]
            ids = {uid for m in mappings for uid in m[side + "_unit_ids"]}
            units = [u for u in snapshots[ref]["units"] if u["unit_id"] in ids]
            selected[ref] = {**snapshots[ref], "units": units}
            paths.update(u["path"] for u in units)
        pairs.append(
            {
                **p,
                "scope": sorted(paths),
                "unit_mappings": mappings,
                "text_diffs": [
                    d for d in p["text_diffs"] if d["mapping_ref"] in selections[p["pair_id"]]
                ],
            }
        )
    cases = [c for c in data["cases"] if c["case_ref"] in batch.get("case_refs", [])]
    histories = [
        h for h in data["historical_items"] if h["history_ref"] in batch.get("history_refs", [])
    ]
    context_units = batch.get("context_units", {})
    context_refs = list(context_units)
    for h in histories:
        for ref in h["basis_refs"]:
            if ref not in selected and ref not in context_refs:
                context_refs.append(ref)
    for ref in context_refs:
        units = [
            u
            for u in snapshots[ref]["units"]
            if ref not in context_units or u["unit_id"] in context_units[ref]
        ]
        selected.setdefault(ref, {**snapshots[ref], "units": units})
    if "FRONTEND_BACKEND_MISMATCH" in data["targets"]:
        after = {p["after_ref"] for p in pairs} | set(context_refs)
        roles = {
            selected[ref]["repository_kind"]
            for ref in after
            if any(u["segments"] for u in selected[ref]["units"])
        }
        for required in ({"BACKEND"}, {"WEB", "FLUTTER"}):
            if roles & required:
                continue
            available = {p["after_ref"] for p in data["comparison_pairs"]} | set(
                data["context_refs"]
            )
            choices = [
                (len(json.dumps(u, ensure_ascii=False).encode()), ref, u)
                for ref in available
                if snapshots[ref]["repository_kind"] in required
                for u in snapshots[ref]["units"]
                if u["segments"]
            ]
            if choices:
                _, ref, unit = min(choices, key=lambda x: x[0])
                selected[ref] = {**snapshots[ref], "units": [unit]}
                if ref not in context_refs:
                    context_refs.append(ref)
    result = {
        **data,
        "comparison_pairs": pairs,
        "context_refs": context_refs,
        "snapshots": list(selected.values()),
        "cases": cases,
        "historical_items": histories,
        "input_limitations": [
            *data["input_limitations"],
            "这是完整固定快照的一个文件批次；静态依赖匹配不能证明已覆盖动态调用及全部跨批关系。",
        ],
    }
    return copy.deepcopy(result)


def summary(plan):
    if not plan:
        return None
    rows = plan["batches"]
    return {
        "version": plan["version"],
        "total": len(rows),
        "completed": sum(b["status"] == "COMPLETED" for b in rows),
        "failed": sum(b["status"] == "FAILED" for b in rows),
        "planned_calls": sum(b.get("callable", True) for b in rows),
        "remaining_calls": sum(
            b.get("callable", True) and b["status"] != "COMPLETED" for b in rows
        ),
        "review_batches": sum(b.get("kind") == "INTEGRATION" for b in rows),
        "batches": [
            {
                k: b.get(k)
                for k in (
                    "id",
                    "status",
                    "error_code",
                    "input_bytes",
                    "files",
                    "kind",
                    "depends_on",
                    "blocked_targets",
                    "blocking_reason",
                    "oversized",
                    "callable",
                )
            }
            for b in rows
        ],
    }


def validate_result(data, batch, report):
    parsed = contract.AnalysisInput.model_validate(input_for(data, batch))
    output = contract.Report.model_validate(report)
    contract.validate_report(parsed, output)
    return output


def aggregate(data, plan):
    if plan.get("version") == 2:
        return batch_merge.aggregate(data, plan)
    result = comparison.unchanged_report(data)
    for group in GROUPS:
        result[group] = []
    coverage, reviews, targets = defaultdict(list), defaultdict(list), defaultdict(list)
    for batch in plan["batches"]:
        if batch["status"] != "COMPLETED":
            continue
        raw = copy.deepcopy(batch["report"])
        raw["request_id"] = data["request_id"]
        validate_result(data, batch, raw)
        keys = {
            item["key"]: f"b{batch['id']}-{hashlib.sha256(item['key'].encode()).hexdigest()[:24]}"
            for group in GROUPS
            for item in raw[group]
        }

        def rename(value):
            if isinstance(value, list):
                return [rename(v) for v in value]
            if isinstance(value, dict):
                return {
                    k: keys[v]
                    if k == "key"
                    else [keys[x] for x in v]
                    if k in RESULT_REFS
                    else rename(v)
                    for k, v in value.items()
                }
            return value

        report = rename(raw)
        for group in GROUPS:
            if group != "historical_reviews":
                result[group].extend(report[group])
        for h in report["historical_reviews"]:
            reviews[h["history_ref"]].append(h)
        for t in report["target_results"]:
            targets[t["target"]].append(t)
        for c in report["coverage"]:
            coverage[(c["pair_ref"], c["side"], c["snapshot_ref"], c["unit_id"])].append(c)
    limit = "L-platform-batches"
    completed = sum(b["status"] == "COMPLETED" for b in plan["batches"])
    result["limitations"].append(
        {
            "key": limit,
            "code": "SCOPE_GAP",
            "affects": data["targets"],
            "description": (
                "按文件及静态依赖分批；未发送、失败及动态/跨批关系未核查，不能解释为无影响。"
            ),
            "needed": ("人工核对跨批关系与重复发现；失败批次人工重试，动态依赖按需补充固定依据。"),
        }
    )
    result["summary"] = {
        "conclusion": (
            f"分批分析完成{completed}/{len(plan['batches'])}批；"
            "以下为已校验批次的证据汇总，未处理范围见覆盖与缺口。"
        ),
        "inheritance_note": (
            "未变资料完整保留；没有主变化或静态依赖关联的文件未发送模型，不据此宣称全范围正确。"
        ),
        "priority_risk_refs": [r["key"] for r in result["risks"] if r["severity"] == "HIGH"],
    }
    for c in result["coverage"]:
        candidates = coverage.get((c["pair_ref"], c["side"], c["snapshot_ref"], c["unit_id"]), [])
        if candidates:
            chosen = next((v for v in candidates if v["status"] == "CHECKED"), candidates[0])
            c.update(copy.deepcopy(chosen))
        else:
            c.update(
                status="PARTIAL",
                note="未进入成功批次；未核查，不等于无影响",
                limitation_refs=[limit],
            )
            for seg in c["segment_reviews"]:
                seg.update(status="UNPROCESSED", note="未进入成功批次")
    result["target_results"] = []
    for target in data["targets"]:
        rows = targets[target]
        checks = [c for r in rows for c in r["checks"]]
        risks = [r["key"] for r in result["risks"] if target in r["target_refs"]]
        result["target_results"].append(
            {
                "target": target,
                "status": "PARTIAL" if checks or risks else "BLOCKED",
                "scope": "按文件批次汇总；跨批次关系及未审查范围不作完成结论",
                "checks": checks,
                "risk_refs": risks,
                "limitation_refs": [limit],
            }
        )
    for h in data["historical_items"]:
        rows = reviews[h["history_ref"]]
        expected = sum(h["history_ref"] in b["history_refs"] for b in plan["batches"])
        if (
            rows
            and len({r["result"] for r in rows}) == 1
            and not (rows[0]["result"] == "STATIC_IMPROVED" and len(rows) != expected)
        ):
            chosen = copy.deepcopy(rows[0])
            for field in ("evidence_refs", "risk_refs", "limitation_refs"):
                chosen[field] = list(dict.fromkeys(x for r in rows for x in r[field]))
        else:
            chosen = {
                "key": f"H-batch-{len(result['historical_reviews'])}",
                "history_ref": h["history_ref"],
                "result": "UNVERIFIABLE" if rows else "NOT_CHECKED",
                "evidence_refs": [],
                "risk_refs": [],
                "limitation_refs": [limit],
                "note": "跨批结论不一致或没有成功复核，需人工核对",
            }
        result["historical_reviews"].append(chosen)
    result["outcome"] = (
        "BLOCKED"
        if (
            all(t["status"] == "BLOCKED" for t in result["target_results"])
            and not result["changes"]
            and not result["risks"]
        )
        else "PARTIAL"
    )
    contract.validate_report(
        contract.AnalysisInput.model_validate(data), contract.Report.model_validate(result)
    )
    return result


def candidate(data, batch, raw, *, previous=()):
    try:
        value = json_object(raw)
        decisions = []
        if batch.get("plan_version") == 2 and batch.get("kind") == "INTEGRATION":
            contract.require(
                isinstance(value, dict) and set(value) == {"report", "reconciliations"}
            )
            decisions = value["reconciliations"]
            value = value["report"]
        output = contract.Report.model_validate(value)
    except (ValidationError, TypeError, ValueError, AppError):
        raise AppError(422, "change_contract_invalid") from None
    subset = contract.AnalysisInput.model_validate(input_for(data, batch))
    output, corrections = evidence.normalize_coordinates(subset, output)
    validate_result(data, batch, output.model_dump(by_alias=True))
    if batch.get("plan_version") == 2 and batch.get("kind") == "INTEGRATION":
        batch["reconciliations"] = validate_reconciliations(
            decisions, previous, output.model_dump(by_alias=True)
        )
    return output.model_dump(by_alias=True), corrections


def validate_reconciliations(decisions, previous, report):
    """A review may reconcile only supplied risks grounded in its current source evidence."""
    contract.require(isinstance(decisions, list))
    supplied = {
        (b["id"], risk["key"]): (b["report"], risk)
        for b in previous
        for risk in b["report"]["risks"]
    }
    targets = {risk["key"]: risk for risk in report["risks"]}

    def anchors(source, risk):
        return [e for e in source["evidence"] if e["key"] in risk["evidence_refs"]]

    def overlap(left, right):
        if any(
            left[k] != right[k] for k in ("side", "snapshot_ref", "unit_id", "segment_id", "kind")
        ):
            return False
        if left["start_line"] is not None and right["start_line"] is not None:
            return (
                left["start_line"] <= right["end_line"] and right["start_line"] <= left["end_line"]
            )
        return left["excerpt"] == right["excerpt"] and (
            left["kind"] == "TEXT" or left["observation"] == right["observation"]
        )

    for row in decisions:
        contract.require(
            isinstance(row, dict) and set(row) == {"kind", "risk_refs", "result_risk_key", "note"}
        )
        contract.require(isinstance(row["kind"], str) and row["kind"] in {"SAME_ROOT", "CONFLICT"})
        contract.require(
            isinstance(row["note"], str) and bool(row["note"].strip()) and len(row["note"]) <= 10000
        )
        contract.require(isinstance(row["risk_refs"], list) and len(row["risk_refs"]) >= 1)
        refs = []
        for ref in row["risk_refs"]:
            contract.require(isinstance(ref, dict) and set(ref) == {"batch_id", "key"})
            contract.require(type(ref["batch_id"]) is int and isinstance(ref["key"], str))
            identity = (ref["batch_id"], ref["key"])
            contract.require(identity in supplied and identity not in refs)
            refs.append(identity)
        contract.require(isinstance(row["result_risk_key"], str))
        contract.require(bool(row["result_risk_key"]) or len(refs) >= 2)
        if row["kind"] == "SAME_ROOT" or row["result_risk_key"]:
            contract.require(row["result_risk_key"] in targets)
            current = anchors(report, targets[row["result_risk_key"]])
            contract.require(
                all(
                    any(overlap(a, b) for a in anchors(*supplied[ref]) for b in current)
                    for ref in refs
                )
            )
    return copy.deepcopy(decisions)


def finish(row, data, plan):
    done = sum(b["status"] == "COMPLETED" for b in plan["batches"])
    failed = any(b["status"] != "COMPLETED" for b in plan["batches"])
    row.report = aggregate(data, plan) if done else {}
    if done and plan["version"] == 2:
        row.handling = reconcile_handling(row.handling, row.report, plan)
    row.status = "COMPLETED" if done else "FAILED"
    row.error_code = "change_batches_failed" if failed else ""
    if not any(b.get("callable", True) for b in plan["batches"]):
        row.error_code = "change_batch_pairing_unavailable"
    row.updated_at = datetime.now(UTC)


def reconcile_handling(handling, report, plan):
    """Keep human audit trails when reviewed findings acquire a shared identity."""
    allowed = {item["key"] for group in GROUPS for item in report[group]}
    aliases = plan.get("result_aliases", {})
    conflicts = plan.get("result_alias_conflicts", {})
    grouped = {}
    changed = False
    for key, entry in handling.items():
        destinations = conflicts.get(key, [aliases.get(key, key)])
        changed |= destinations != [key]
        for target in destinations:
            if target in allowed:
                grouped.setdefault(target, []).append((key, entry))
    if not changed:
        return handling
    plan.setdefault("handling_merge_audit", []).append(
        {
            "at": datetime.now(UTC).isoformat(),
            "original": copy.deepcopy(handling),
            "aliases": copy.deepcopy(aliases),
            "conflicts": copy.deepcopy(conflicts),
        }
    )
    result = {}
    for key, entries in grouped.items():
        histories = []
        for old, entry in entries:
            for event in entry.get("history", []):
                if event not in histories:
                    histories.append(copy.deepcopy(event))
        histories.sort(key=lambda e: e["at"])
        latest = max((entry for _, entry in entries), key=lambda e: e["at"])
        result[key] = {**copy.deepcopy(latest), "history": histories}
        if len({e["status"] for _, e in entries}) > 1 or any(
            old in conflicts for old, _ in entries
        ):
            event = {
                "status": "PENDING",
                "note": "关联复核合并后的人工结论存在冲突，原处理历史已保留，请重新核对",
                "actor_id": None,
                "actor_name": "平台合并待核对",
                "at": datetime.now(UTC).isoformat(),
                "previous_status": latest["status"],
            }
            result[key] = {**event, "history": [*histories, event]}
    return result


def revalidate(row):
    plan = copy.deepcopy(row.metadata_snapshot["batch_plan"])
    for batch in plan["batches"]:
        if batch["status"] == "COMPLETED" or batch["candidate_task_id"] != row.id:
            continue
        path = artifacts.batch_candidate_path(row.id, batch["id"])
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8")
            previous = [b for b in plan["batches"] if b["id"] in batch.get("depends_on", [])]
            report, corrections = candidate(row.input_snapshot, batch, raw, previous=previous)
        except AppError:
            continue
        except (OSError, UnicodeError):
            raise AppError(503, "change_candidate_storage_unavailable") from None
        batch.update(
            status="COMPLETED",
            error_code="",
            report=report,
            evidence_corrections=corrections,
            revalidated_at=datetime.now(UTC).isoformat(),
        )
    row.metadata_snapshot = {**row.metadata_snapshot, "batch_plan": plan}
    finish(row, row.input_snapshot, plan)
