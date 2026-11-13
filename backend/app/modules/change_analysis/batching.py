"""Fixed file batches and deterministic, evidence-preserving report aggregation."""

import copy
import hashlib
import json
import re
from collections import defaultdict
from pathlib import PurePosixPath

from app.modules.change_analysis import batch_merge, batch_planning, comparison, contract

TARGET_BYTES = 1024 * 1024
LEGACY_TARGET_BYTES = 512 * 1024
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
NOTE = (
    "\n\n平台分批执行说明：用户已授权按文件分批，本次是一个子输入；"
    "历史Skill中的完整单次提交约定在此次执行中以本批范围为准，模型不自行追加调用。"
    "本次只分析所给固定文件范围。主变化映射为下列清单；"
    "其他文件是依赖或共同依据，不额外生成其独立变化项。原文及行号未裁剪，"
    "未提供的文件不能声称已读；动态依赖、跨批次关系不明确时必须记录证据缺口。"
    "仍按原CHANGE_IMPACT契约返回完整本批报告、覆盖清单及引用，不输出全项目完成结论。\n"
)


def size(value):
    return len(json.dumps(value, ensure_ascii=False).encode())


def fingerprint(data):
    return hashlib.sha256(
        json.dumps(
            {k: v for k, v in data.items() if k != "request_id"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def input_for(data, batch):
    if batch.get("plan_version") == 2:
        return batch_planning.input_for(data, batch)
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
                (size(u), ref, u)
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


def plan(data, *, version=2):
    if version == 2:
        return batch_planning.plan(data, TARGET_BYTES)
    contract.require(version == 1, "change_batch_snapshot_mismatch")
    return legacy_plan(data)


def legacy_plan(data):
    if size(data) <= LEGACY_TARGET_BYTES:
        return None
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    atoms, changed, names = {}, [], defaultdict(set)
    for p in data["comparison_pairs"]:
        diffs = {d["mapping_ref"] for d in p["text_diffs"]}
        for m in p["unit_mappings"]:
            key = (p["pair_id"], m["mapping_id"])
            units = [
                u
                for side in ("before", "after")
                for u in snapshots[p[side + "_ref"]]["units"]
                if u["unit_id"] in m[side + "_unit_ids"]
            ]
            atoms[key] = units
            for u in units:
                stem = PurePosixPath(u["path"]).stem
                if len(stem) >= 3 and re.fullmatch(r"[A-Za-z_$][\w$]*", stem):
                    names[(snapshots[p["before_ref"]]["source_id"], stem)].add(key)
            if m["mapping_id"] in diffs:
                changed.append(key)
    if not changed:
        return None
    neighbors = defaultdict(set)
    source_ids = {
        p["pair_id"]: snapshots[p["before_ref"]]["source_id"] for p in data["comparison_pairs"]
    }
    for key, units in atoms.items():
        tokens = set(
            re.findall(
                r"[A-Za-z_$][\w$]*", "\n".join(seg["text"] for u in units for seg in u["segments"])
            )
        )
        for token in tokens:
            matches = names.get((source_ids[key[0]], token), set())
            if len(matches) == 1:
                other = next(iter(matches))
                if other != key:
                    neighbors[key].add(other)
                    neighbors[other].add(key)
    weights = {key: size(units) for key, units in atoms.items()}
    seeds, seed, used = [], [], 0
    for primary in sorted(changed, key=lambda k: (k[0], atoms[k][0]["path"])):
        if seed and used + weights[primary] > LEGACY_TARGET_BYTES // 2:
            seeds.append(seed)
            seed, used = [], 0
        seed.append(primary)
        used += weights[primary]
    if seed:
        seeds.append(seed)
    # Assign shared dependency candidates once; cross-batch relations remain explicit gaps.
    owner = {key: n for n, seed in enumerate(seeds) for key in seed}
    assigned = defaultdict(set)
    for dependency in atoms.keys() - owner.keys():
        votes = defaultdict(int)
        for related in neighbors[dependency]:
            if related in owner:
                votes[owner[related]] += 1
        if votes:
            assigned[min(votes, key=lambda n: (-votes[n], n))].add(dependency)
    batches = []
    for n, seed in enumerate(seeds):
        selected = set(seed)
        primary_bytes = sum(weights[k] for k in seed)
        used = primary_bytes
        budget = max(LEGACY_TARGET_BYTES, primary_bytes + LEGACY_TARGET_BYTES // 2)
        for dep in sorted(assigned[n]):
            if len(selected) > len(seed) and used + weights[dep] > budget:
                batches.append(
                    {
                        "primary": [list(k) for k in seed],
                        "mappings": [list(k) for k in sorted(selected)],
                    }
                )
                selected, used = set(seed), primary_bytes
            selected.add(dep)
            used += weights[dep]
        batches.append(
            {"primary": [list(k) for k in seed], "mappings": [list(k) for k in sorted(selected)]}
        )
    common = []
    for ref in data["context_refs"]:
        common.extend(("unit", ref, u["unit_id"], size(u)) for u in snapshots[ref]["units"])
    common.extend(("case", c["case_ref"], "", size(c)) for c in data["cases"])
    common.extend(("history", h["history_ref"], "", size(h)) for h in data["historical_items"])
    expanded = []
    for batch in batches:
        groups, group, used = [], [], 0
        room = max(
            64 * 1024, LEGACY_TARGET_BYTES - sum(weights[tuple(k)] for k in batch["mappings"])
        )
        for item in common:
            if group and used + item[3] > room:
                groups.append(group)
                group, used = [], 0
            group.append(item)
            used += item[3]
        groups.append(group)
        for group in groups:
            context = defaultdict(list)
            for kind, ref, uid, _ in group:
                if kind == "unit":
                    context[ref].append(uid)
            expanded.append(
                {
                    **batch,
                    "context_units": dict(context),
                    "case_refs": [ref for kind, ref, _, _ in group if kind == "case"],
                    "history_refs": [ref for kind, ref, _, _ in group if kind == "history"],
                }
            )
    batches = expanded
    for n, batch in enumerate(batches, 1):
        projected = input_for(data, batch)
        contract.validate_input(contract.AnalysisInput.model_validate(projected))
        batch.update(
            id=n,
            status="QUEUED",
            error_code="",
            report=None,
            input_bytes=size(projected),
            candidate_task_id=None,
            attempts=[],
            files=sorted(
                {f"{s['name']} / {u['path']}" for s in projected["snapshots"] for u in s["units"]}
            ),
        )
    return {"version": 1, "input_hash": fingerprint(data), "batches": batches}


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
