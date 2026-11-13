"""Merge reviewed batches by evidence identity and retain conflicting conclusions."""

import copy
import hashlib
import json
from collections import defaultdict

from app.modules.change_analysis import comparison, contract

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
REFS = {
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
MAX_TEXT = 10000


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity(prefix, value):
    return prefix + "-" + hashlib.sha256(_json(value).encode()).hexdigest()[:32]


def _unique(values):
    result, seen = [], set()
    for value in values:
        key = _json(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _replace(value, mapping):
    if isinstance(value, list):
        return [_replace(v, mapping) for v in value]
    if isinstance(value, dict):
        return {
            k: mapping.get(v, v)
            if k == "key"
            else _unique([mapping.get(x, x) for x in v])
            if k in REFS
            else _replace(v, mapping)
            for k, v in value.items()
        }
    return value


def _without_key(item):
    return {k: v for k, v in item.items() if k != "key"}


def _compatible(left, right):
    if left["attribution"]["kind"] != right["attribution"]["kind"]:
        return False
    if (
        left["attribution"]["kind"] == "introduced"
        and left["evidence_state"] != right["evidence_state"]
    ):
        return False
    views = {v["target"]: v for v in left["target_views"]}
    return all(
        not views.get(view["target"])
        or all(
            views[view["target"]][key] == view[key]
            for key in ("expected", "basis", "evidence_state")
        )
        for view in right["target_views"]
    )


def _variant_key(cause, risk):
    return _identity("risk-variant", [cause, risk["target_views"], risk["attribution"]["kind"]])


def _coalesce(reports, group, identity=None):
    """Deduplicate an exact semantic object after its dependency keys are canonical."""
    entries, aliases = {}, {}
    for report in reports:
        for item in report[group]:
            value = identity(item) if identity else _without_key(item)
            key = _identity(group, value)
            aliases[item["key"]] = key
            if key not in entries:
                entries[key] = {**copy.deepcopy(item), "key": key}
            else:
                prior = entries[key]
                for field in REFS | {"questions", "mapping_refs", "diff_refs"}:
                    if field in item:
                        prior[field] = _unique(prior[field] + item[field])
    for n, report in enumerate(reports):
        reports[n] = _replace(report, aliases)
    return list(entries.values())


def aggregate(data, plan):
    """Combine fixed reports without inventing evidence or dropping unresolved variants."""
    reports, conclusions, inheritances, namespaces = [], [], [], {}
    batches = plan["batches"]
    completed = [b for b in batches if b["status"] == "COMPLETED"]
    for batch in completed:
        report = copy.deepcopy(batch["report"])
        report["request_id"] = data["request_id"]
        namespace = {
            item["key"]: f"b{batch['id']}-{hashlib.sha256(item['key'].encode()).hexdigest()[:24]}"
            for group in GROUPS
            for item in report[group]
        }
        namespaces[batch["id"]] = namespace
        reports.append(_replace(report, namespace))
        conclusions.append(f"第{batch['id']}批：{report['summary']['conclusion']}")
        if report["summary"]["inheritance_note"]:
            inheritances.append(f"第{batch['id']}批：{report['summary']['inheritance_note']}")
    result = comparison.unchanged_report(data)
    for group in GROUPS:
        result[group] = []
    result["target_results"] = []
    warnings = []

    def limitation(description, *, code="REVIEW_WARNING", needed="人工核对原批结论与固定证据"):
        key = _identity("platform", [code, description, needed])
        if not any(x["key"] == key for x in result["limitations"]):
            for n, start in enumerate(range(0, max(1, len(description)), MAX_TEXT)):
                result["limitations"].append(
                    {
                        "key": key if n == 0 else f"{key}-{n}",
                        "code": code,
                        "description": description[start : start + MAX_TEXT],
                        "affects": data["targets"],
                        "needed": needed,
                    }
                )
        return key

    def warn(description):
        warnings.append(description)
        return limitation(description)

    def combined(values, label):
        text = "\n\n".join(_unique([x for x in values if x]))
        if len(text) <= MAX_TEXT:
            return text
        key = limitation(text, needed=f"{label}完整内容保存在此处的连续说明项")
        return f"{label}完整内容见限制说明 {key} 及后续连续项。"

    result["evidence"] = _coalesce(
        reports,
        "evidence",
        lambda item: {
            k: v
            for k, v in item.items()
            if k != "key" and not (item["kind"] == "TEXT" and k == "observation")
        },
    )
    result["limitations"] = _coalesce(reports, "limitations")
    observations = defaultdict(list)
    for report in reports:
        for item in report["evidence"]:
            observations[item["key"]].append(item["observation"])
    for item in result["evidence"]:
        item["observation"] = combined(observations[item["key"]], "原文证据观察")
    result["chains"] = _coalesce(reports, "chains")
    change_fields = (
        "pair_ref",
        "mapping_refs",
        "diff_refs",
        "kind",
        "evidence_state",
        "before",
        "after",
        "evidence_refs",
    )
    result["changes"] = _coalesce(
        reports,
        "changes",
        lambda item: {
            k: sorted(item[k]) if isinstance(item[k], list) else item[k] for k in change_fields
        },
    )
    # Keep differing business explanations even when their fixed change identity is the same.
    change_variants = defaultdict(list)
    for report in reports:
        for item in report["changes"]:
            change_variants[item["key"]].append(item)
    for change in result["changes"]:
        for field in ("function", "business_effect"):
            change[field] = combined([x[field] for x in change_variants[change["key"]]], field)

    evidence = {e["key"]: e for e in result["evidence"]}
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}

    def risk_identity(risk):
        refs = [evidence[k] for k in risk["evidence_refs"]]
        code = [e for e in refs if snapshots[e["snapshot_ref"]]["kind"] == "CODE"]
        anchors = code or refs
        return [
            risk["trigger"],
            risk["actual"],
            risk["root_cause"],
            sorted(e["key"] for e in anchors),
        ]

    risk_items = {r["key"]: r for report in reports for r in report["risks"]}
    original_keys = {
        mapped: key for namespace in namespaces.values() for key, mapped in namespace.items()
    }
    old_risk_keys, old_variants = {}, defaultdict(list)
    for key, item in risk_items.items():
        cause = risk_identity(item)
        old_root = _identity("risk", cause)
        prior = next((r for r in old_variants[old_root] if _compatible(r, item)), None)
        if prior is None:
            prior = copy.deepcopy(item)
            prior["key"] = old_root if not old_variants[old_root] else _variant_key(cause, item)
            old_variants[old_root].append(prior)
        else:
            prior["target_views"] = _unique(prior["target_views"] + item["target_views"])
        old_risk_keys[key] = prior["key"]
    old_reports = [_replace(report, old_risk_keys) for report in reports]
    other_keys = {
        (n, group, i): _identity(group, _without_key(item))
        for n, report in enumerate(old_reports)
        for group in ("function_impacts", "code_impacts", "case_impacts", "regression_scope")
        for i, item in enumerate(report[group])
    }
    risk_batches = {
        r["key"]: batch
        for batch, report in zip(completed, reports, strict=True)
        for r in report["risks"]
    }
    parents = {key: key for key in risk_items}

    def root_of(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    decisions, conflicted = [], set()
    for batch in completed:
        for decision in batch.get("reconciliations", []):
            references = []
            for ref in decision["risk_refs"]:
                key = namespaces.get(ref["batch_id"], {}).get(ref["key"])
                contract.require(key in risk_items)
                references.append(key)
            target = namespaces[batch["id"]].get(decision.get("result_risk_key", ""))
            if target:
                contract.require(target in risk_items)
                references.append(target)
            contract.require(references and decision["note"].strip())
            if decision["kind"] == "CONFLICT":
                conflicted.update(references)
                key = warn("关联复核发现原批风险结论存在冲突，保留原发现：" + decision["note"])
                for ref in references:
                    risk_items[ref]["limitation_refs"] = _unique(
                        risk_items[ref]["limitation_refs"] + [key]
                    )
            else:
                contract.require(decision["kind"] == "SAME_ROOT" and target)
                for ref in references[1:]:
                    parents[root_of(ref)] = root_of(references[0])
                decisions.append((references, target, decision["note"]))
    groups, review_values = defaultdict(list), {}
    for references, target, note in decisions:
        root = root_of(target)
        groups[root].extend(references)
        previous = review_values.get(root)
        values = {field: risk_items[target][field] for field in ("trigger", "actual", "root_cause")}
        if previous and previous != values:
            warn("同一风险组的关联复核给出不同根因说明，保留各项复核依据待人工核对。")
        else:
            review_values[root] = values
        source_text = [
            f"批次{risk_batches[ref]['id']} / 原风险{original_keys[ref]}："
            + _json(
                {field: risk_items[ref][field] for field in ("trigger", "actual", "root_cause")}
            )
            for ref in _unique(references)
        ]
        audit = limitation(
            "关联复核明确判定同根因：" + note + "\n" + "\n".join(source_text),
            needed="原措辞完整保留于此处及原批报告；复核不替代原文证据",
        )
        for ref in references:
            risk_items[ref]["limitation_refs"] = _unique(
                risk_items[ref]["limitation_refs"] + [audit]
            )
    forced_roots = {}
    for root, references in groups.items():
        references = _unique(references)
        sources = [
            ref for ref in references if risk_batches[ref].get("kind") != "INTEGRATION"
        ] or references
        stable = min(_identity("risk", risk_identity(risk_items[ref])) for ref in sources)
        for ref in references:
            if ref not in conflicted:
                forced_roots[ref] = stable
                risk_items[ref].update(review_values[root])

    risks, risk_aliases, by_cause = [], {}, defaultdict(list)
    for report in reports:
        for item in report["risks"]:
            cause = risk_identity(item)
            root = (
                _identity("risk-conflict", [old_risk_keys[item["key"]], item["key"]])
                if item["key"] in conflicted
                else forced_roots.get(item["key"]) or _identity("risk", cause)
            )
            prior = next((r for r in by_cause[root] if _compatible(r, item)), None)
            if prior is None:
                prior = copy.deepcopy(item)
                prior["key"] = root if not by_cause[root] else _variant_key(cause, item)
                if by_cause[root]:
                    key = warn(
                        f"同一固定根因出现不一致的目标对照或归因，保留各批变体待核对：{item['root_cause']}"
                    )
                    for variant in [*by_cause[root], prior]:
                        variant["limitation_refs"] = _unique(variant["limitation_refs"] + [key])
                risks.append(prior)
                by_cause[root].append(prior)
            else:
                for field in (
                    "target_refs",
                    "change_refs",
                    "history_refs",
                    "evidence_refs",
                    "chain_refs",
                    "limitation_refs",
                ):
                    prior[field] = _unique(prior[field] + item[field])
                views = {v["target"]: v for v in prior["target_views"]}
                for view in item["target_views"]:
                    if view["target"] not in views:
                        prior["target_views"].append(copy.deepcopy(view))
                    else:
                        view_prior = views[view["target"]]
                        for field in ("basis_refs", "comparison_rows"):
                            view_prior[field] = _unique(view_prior[field] + view[field])
                for field in (
                    "impact",
                    "severity_reason",
                    "counterevidence_note",
                    "fix_suggestion",
                    "verification_suggestion",
                ):
                    prior[field] = combined([prior[field], item[field]], field)
                for field in ("before_refs", "after_refs", "causal_change_refs", "limitation_refs"):
                    prior["attribution"][field] = _unique(
                        prior["attribution"][field] + item["attribution"][field]
                    )
                for field in ("explanation", "impact_expansion"):
                    prior["attribution"][field] = combined(
                        [prior["attribution"][field], item["attribution"][field]], field
                    )
                severity = ("UNASSESSED", "LOW", "MEDIUM", "HIGH")
                if prior["severity"] != item["severity"]:
                    key = warn(
                        f"同一风险的严重程度评估不一致，保留较高等级待核对：{prior['title']}"
                    )
                    prior["limitation_refs"] = _unique(prior["limitation_refs"] + [key])
                    prior["severity"] = max(
                        (prior["severity"], item["severity"]), key=severity.index
                    )
                prior["evidence_state"] = (
                    "INSUFFICIENT"
                    if any(v["evidence_state"] == "INSUFFICIENT" for v in prior["target_views"])
                    else "STATIC_SUPPORTED"
                )
            risk_aliases[item["key"]] = prior["key"]
    reports = [_replace(report, risk_aliases) for report in reports]
    result["risks"] = risks
    for group in ("function_impacts", "code_impacts", "case_impacts", "regression_scope"):
        result[group] = _coalesce(reports, group)
    aliases = defaultdict(set)
    for previous, current in risk_aliases.items():
        aliases[old_risk_keys[previous]].add(current)
    for n, report in enumerate(reports):
        for group in ("function_impacts", "code_impacts", "case_impacts", "regression_scope"):
            for i, item in enumerate(report[group]):
                aliases[other_keys[n, group, i]].add(item["key"])
    plan["result_aliases"] = {
        key: next(iter(values)) for key, values in aliases.items() if len(values) == 1
    }
    plan["result_alias_conflicts"] = {
        key: sorted(values) for key, values in aliases.items() if len(values) > 1
    }

    cases = defaultdict(list)
    for item in result["case_impacts"]:
        cases[item["case_ref"]].append(item)
    for case_ref, items in cases.items():
        proposals = defaultdict(set)
        for item in items:
            for field in item["proposed_fields"]:
                proposals[field["field"]].add(field["proposal"])
        if len({i["action"] for i in items}) > 1 or any(len(v) > 1 for v in proposals.values()):
            key = warn(
                f"用例 {case_ref} 的维护动作或字段建议跨批不一致，保留原建议，尚未形成统一结论。"
            )
            for item in items:
                item["limitation_refs"] = _unique(item["limitation_refs"] + [key])

    all_done = bool(batches) and len(completed) == len(batches)
    blocked = {target for b in batches for target in b.get("blocked_targets", [])}
    gaps = not all_done or bool(blocked)
    gap = (
        limitation(
            "存在未完成批次、未核查范围或未配对目标，不能按零风险或整体完成解读。",
            code="SCOPE_GAP",
            needed="完成计划中的原文分析与关联复核；失败仅人工重试",
        )
        if gaps
        else None
    )
    coverage = defaultdict(list)
    target_rows = defaultdict(list)
    histories = defaultdict(list)
    for report in reports:
        for row in report["coverage"]:
            coverage[(row["pair_ref"], row["side"], row["snapshot_ref"], row["unit_id"])].append(
                row
            )
        for row in report["target_results"]:
            target_rows[row["target"]].append(row)
        for row in report["historical_reviews"]:
            histories[row["history_ref"]].append(row)
    for row in result["coverage"]:
        key = (row["pair_ref"], row["side"], row["snapshot_ref"], row["unit_id"])
        candidates = coverage[key]
        if candidates:
            chosen = max(
                candidates, key=lambda r: (r["status"] != "CHECKED", r["status"] == "UNAVAILABLE")
            )
            row.update(copy.deepcopy(chosen))
        else:
            if gap is None:
                gap = limitation(
                    "固定根输入含未进入任何成功核查批次的文件，不能判定无影响。", code="SCOPE_GAP"
                )
            row.update(status="PARTIAL", note="未进入成功核查批次", limitation_refs=[gap])
            for segment in row["segment_reviews"]:
                segment.update(status="UNPROCESSED", note="未进入成功核查批次")
    for history in data["historical_items"]:
        rows = histories[history["history_ref"]]
        expected = sum(history["history_ref"] in b.get("history_refs", []) for b in batches)
        same = rows and len({r["result"] for r in rows}) == 1
        incomplete = expected > len(rows)
        if same and not (incomplete and rows[0]["result"] == "STATIC_IMPROVED"):
            item = copy.deepcopy(rows[0])
            item["key"] = _identity("history", history["history_ref"])
            item["note"] = combined([r["note"] for r in rows], "历史复核说明")
            for field in ("evidence_refs", "risk_refs", "limitation_refs"):
                item[field] = _unique([x for row in rows for x in row[field]])
        else:
            warning = warn(
                f"历史问题 {history['history_ref']} 的跨批结论不一致或复核尚未完成，保留为待核对。"
            )
            item = {
                "key": _identity("history", history["history_ref"]),
                "history_ref": history["history_ref"],
                "result": "UNVERIFIABLE" if rows else "NOT_CHECKED",
                "note": "原批复核结论见报告与调用审计，尚未形成统一结论",
                "evidence_refs": _unique([x for row in rows for x in row["evidence_refs"]]),
                "risk_refs": _unique([x for row in rows for x in row["risk_refs"]]),
                "limitation_refs": [warning],
            }
        result["historical_reviews"].append(item)
    for target in data["targets"]:
        rows = target_rows[target]
        checks = _unique([check for row in rows for check in row["checks"]])
        assessments = defaultdict(set)
        for check in checks:
            if check["evidence_refs"]:
                assessments[_json(sorted(check["evidence_refs"]))].add(check["assessment"])
        if any("CONSISTENT" in v and v & {"DEVIATION", "SUSPECTED"} for v in assessments.values()):
            warn(f"目标 {target} 对相同固定证据出现符合与偏差两种判断，保留检查条目待跨批核对。")
        risks = [r["key"] for r in result["risks"] if target in r["target_refs"]]
        complete = (
            all_done
            and target not in blocked
            and rows
            and all(r["status"] == "COMPLETE" for r in rows)
        )
        status = "COMPLETE" if complete else "PARTIAL" if checks or risks else "BLOCKED"
        limits = _unique([key for row in rows for key in row["limitation_refs"]])
        if status != "COMPLETE":
            if gap is None:
                gap = limitation(
                    "部分目标尚未完成或证据不足，按各批检查与限制说明核对。", code="SCOPE_GAP"
                )
            limits = _unique(limits + [gap])
        result["target_results"].append(
            {
                "target": target,
                "status": status,
                "scope": combined([r["scope"] for r in rows], "目标核查范围")
                or "本目标尚无成功核查",
                "checks": checks,
                "risk_refs": risks,
                "limitation_refs": limits,
            }
        )
    if warnings:
        conflict = limitation("\n".join(_unique(warnings)))
        for target in result["target_results"]:
            if target["status"] == "COMPLETE":
                target["status"] = "PARTIAL"
            target["limitation_refs"] = _unique(target["limitation_refs"] + [conflict])
    result["summary"] = {
        "conclusion": combined(
            [
                f"已完成{len(completed)}/{len(batches)}批原文及关联核查。",
                *conclusions,
                *(["跨批不一致结论尚待核对，见REVIEW_WARNING。"] if warnings else []),
            ],
            "各批分析结论",
        ),
        "inheritance_note": combined(inheritances, "各批继承说明"),
        "priority_risk_refs": [r["key"] for r in result["risks"] if r["severity"] == "HIGH"],
    }
    complete = all(t["status"] == "COMPLETE" for t in result["target_results"]) and all(
        c["status"] == "CHECKED" for c in result["coverage"]
    )
    blocked_outcome = (
        all(t["status"] == "BLOCKED" for t in result["target_results"])
        and not result["changes"]
        and not result["risks"]
    )
    result["outcome"] = "COMPLETE" if complete else "BLOCKED" if blocked_outcome else "PARTIAL"
    contract.validate_report(
        contract.AnalysisInput.model_validate(data), contract.Report.model_validate(result)
    )
    return result
