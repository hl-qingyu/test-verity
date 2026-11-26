"""Deterministic no-change result: explicit skipped targets, no paid model call."""


def has_changes(data, bindings):
    if any(p["text_diffs"] for p in data["comparison_pairs"]):
        return True
    hashes = {b["snapshot_ref"]: b.get("binary_sha256") for b in bindings}
    visual = {
        s["snapshot_ref"]
        for s in data["snapshots"]
        if any(seg["image_ref"] for u in s["units"] for seg in u["segments"])
    }
    return any(
        p["before_ref"] in visual and hashes.get(p["before_ref"]) != hashes.get(p["after_ref"])
        for p in data["comparison_pairs"]
    )


def unchanged_report(data, *, include_coverage=True):
    snapshots = {s["snapshot_ref"]: s for s in data["snapshots"]}
    coverage = []
    used = [
        (p["pair_id"], side, ref)
        for p in data["comparison_pairs"]
        for side, ref in (("BEFORE", p["before_ref"]), ("AFTER", p["after_ref"]))
    ]
    used += [("", "CONTEXT", ref) for ref in data["context_refs"]]
    for pair, side, ref in used if include_coverage else ():
        s = snapshots[ref]
        for u in s["units"]:
            partial = not s["scope_complete"] or u["read_state"] != "READABLE"
            coverage.append(
                {
                    "snapshot_ref": ref,
                    "unit_id": u["unit_id"],
                    "side": side,
                    "pair_ref": pair,
                    "status": "PARTIAL" if partial else "CHECKED",
                    "segment_reviews": [
                        {
                            "segment_id": seg["segment_id"],
                            "status": "IRRELEVANT",
                            "note": "主比较范围无变化，未进行风险目标审查",
                        }
                        for seg in u["segments"]
                    ],
                    "note": "仅核对调用方固定内容差异，不作为业务或代码正确结论",
                    "limitation_refs": ["L-no-change"],
                }
            )
    result = {
        k: data[k]
        for k in (
            "contract_version",
            "analysis_type",
            "request_id",
            "project_id",
            "revision",
            "mode",
        )
    }
    result.update(
        outcome="BLOCKED",
        summary={
            "conclusion": (
                "已读取范围无内容差异，未调用AI，也未执行所选风险检查；"
                "未读部分不能判为无变化；可回原模块审查现状。"
            ),
            "priority_risk_refs": [],
            "inheritance_note": "未变规则不列变化卡片。",
        },
        target_results=[
            {
                "target": t,
                "status": "BLOCKED",
                "scope": "本次固定范围无变化，未进行AI分析",
                "checks": [],
                "risk_refs": [],
                "limitation_refs": ["L-no-change"],
            }
            for t in data["targets"]
        ],
        changes=[],
        function_impacts=[],
        code_impacts=[],
        case_impacts=[],
        risks=[],
        historical_reviews=[
            {
                "key": f"H-no-change-{n}",
                "history_ref": h["history_ref"],
                "result": "NOT_CHECKED",
                "note": "主范围无变化，未复核历史问题",
                "evidence_refs": [],
                "risk_refs": [],
                "limitation_refs": ["L-no-change"],
            }
            for n, h in enumerate(data["historical_items"])
        ],
        regression_scope=[],
        evidence=[],
        chains=[],
        limitations=[
            {
                "key": "L-no-change",
                "code": "UNPROCESSED",
                "description": "没有主范围变化，所选分析目标与历史问题未执行；不等于零风险或无影响",
                "affects": data["targets"],
                "needed": "补选真实变化范围，或回到代码/需求分析审查现状",
            }
        ],
    )
    if include_coverage:
        result["coverage"] = coverage
    return result
