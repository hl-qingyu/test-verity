import copy
import json
import unittest
from pathlib import Path

from app.modules.change_analysis import batch_merge, contract

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/change-impact/examples"


def fixture(name="code"):
    return tuple(
        json.loads((EXAMPLES / f"{name}-{kind}.json").read_text(encoding="utf-8"))
        for kind in ("input", "report")
    )


def plan(*reports):
    return {
        "version": 2,
        "batches": [
            {
                "id": n,
                "kind": "ANALYSIS" if n == 1 else "INTEGRATION",
                "status": "COMPLETED",
                "report": copy.deepcopy(report),
                "history_refs": [h["history_ref"] for h in report["historical_reviews"]],
            }
            for n, report in enumerate(reports, 1)
        ],
    }


def validate(data, report):
    contract.validate_report(
        contract.AnalysisInput.model_validate(data), contract.Report.model_validate(report)
    )


class ChangeBatchMergeTests(unittest.TestCase):
    def test_reviewed_same_root_merges_different_wording_and_maps_previous_manual_keys(self):
        data, first = fixture()
        second = copy.deepcopy(first)
        second["risks"][0].update(
            trigger="另一批描述同一空列表输入",
            actual="未保护的索引访问导致异常",
            root_cause="共享首项访问缺少空列表保护",
        )
        second["evidence"][0]["observation"] = "同一原文的另一种观察表述"
        review = copy.deepcopy(first)
        review["risks"][0].update(
            trigger="统一核查：调用时列表为空",
            actual="统一核查：首项访问失败",
            root_cause="统一核查：共享读取未处理空列表",
        )
        original = copy.deepcopy((first, second, review))
        prior = batch_merge.aggregate(data, plan(first, second))
        self.assertEqual(
            len(prior["risks"]), 2, "without a review decision different causes stay distinct"
        )
        value = plan(first, second, review)
        value["batches"][2]["kind"] = "INTEGRATION"
        value["batches"][2]["reconciliations"] = [
            {
                "kind": "SAME_ROOT",
                "risk_refs": [{"batch_id": 1, "key": "R1"}, {"batch_id": 2, "key": "R1"}],
                "result_risk_key": "R1",
                "note": "核查固定代码，同一个共享读取错误。",
            }
        ]
        result = batch_merge.aggregate(data, value)
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(len(result["evidence"]), 3)
        self.assertEqual(result["risks"][0]["root_cause"], review["risks"][0]["root_cause"])
        retained = "".join(x["description"] for x in result["limitations"])
        self.assertIn(second["risks"][0]["root_cause"], retained)
        self.assertIn(first["risks"][0]["trigger"], retained)
        self.assertTrue(any("另一种观察" in e["observation"] for e in result["evidence"]))
        for risk in prior["risks"]:
            self.assertEqual(value["result_aliases"][risk["key"]], result["risks"][0]["key"])
        self.assertEqual((first, second, review), original)
        validate(data, result)

    def test_review_conflict_keeps_sources_even_when_the_exact_fingerprint_matches(self):
        data, report = fixture()
        value = plan(report, report, report)
        value["batches"][2]["reconciliations"] = [
            {
                "kind": "CONFLICT",
                "risk_refs": [{"batch_id": 1, "key": "R1"}, {"batch_id": 2, "key": "R1"}],
                "result_risk_key": "",
                "note": "同一描述的外部约束判断相反，不能合并结论。",
            }
        ]
        result = batch_merge.aggregate(data, value)
        self.assertGreaterEqual(len(result["risks"]), 2)
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertTrue(value["result_alias_conflicts"])
        self.assertTrue(any("外部约束判断相反" in x["description"] for x in result["limitations"]))
        validate(data, result)

    def test_same_root_deduplicates_across_batches_and_keeps_every_reference_valid(self):
        data, report = fixture()
        first, second = copy.deepcopy(report), copy.deepcopy(report)
        second["changes"][0]["title"] = "同一变化的另一种标题"
        second["changes"][0]["business_effect"] = "另一个批次补充的影响说明"
        second["risks"][0]["title"] = "同根因的另一种标题"
        second["risks"][0]["impact"] += " 另一批补充影响。"
        original = copy.deepcopy((data, first, second))
        result = batch_merge.aggregate(data, plan(first, second))
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(len(result["evidence"]), 3)
        self.assertIn("另一批补充影响", result["risks"][0]["impact"])
        self.assertIn("另一个批次补充的影响说明", result["changes"][0]["business_effect"])
        self.assertEqual(result["outcome"], "COMPLETE")
        self.assertIn(report["summary"]["conclusion"], result["summary"]["conclusion"])
        validate(data, result)
        self.assertEqual((data, first, second), original)
        retry = {**data, "request_id": "another-request"}
        after_retry = batch_merge.aggregate(retry, plan(first, second))
        self.assertEqual(result["risks"][0]["key"], after_retry["risks"][0]["key"])

    def test_equal_titles_do_not_merge_different_root_causes(self):
        data, report = fixture()
        other = copy.deepcopy(report)
        other["risks"][0]["root_cause"] = "完全不同的边界处理错误"
        result = batch_merge.aggregate(data, plan(report, other))
        self.assertEqual(len(result["risks"]), 2)
        validate(data, result)

    def test_same_root_merges_different_targets_without_losing_their_comparisons(self):
        data, bug = fixture()
        req_data, _ = fixture("requirement")
        snapshot = copy.deepcopy(req_data["snapshots"][1])
        snapshot["snapshot_ref"] = "rule"
        data["snapshots"].append(snapshot)
        data["context_refs"] = ["rule"]
        data["targets"] = ["BUG", "REQUIREMENT_DEVIATION"]
        unit = snapshot["units"][0]
        seg = unit["segments"][0]
        rule = {
            "key": "ER",
            "side": "CONTEXT",
            "pair_ref": "",
            "snapshot_ref": "rule",
            "unit_id": unit["unit_id"],
            "segment_id": seg["segment_id"],
            "kind": "TEXT",
            "start_line": None,
            "end_line": None,
            "excerpt": seg["text"],
            "observation": "",
        }
        bug["evidence"].append(rule)
        bug["coverage"].append(
            {
                "snapshot_ref": "rule",
                "unit_id": unit["unit_id"],
                "side": "CONTEXT",
                "pair_ref": "",
                "status": "CHECKED",
                "segment_reviews": [
                    {"segment_id": s["segment_id"], "status": "CHECKED", "note": "合成规则核对"}
                    for s in unit["segments"]
                ],
                "note": "本批规则核对",
                "limitation_refs": [],
            }
        )
        deviation = copy.deepcopy(bug)
        deviation["target_results"][0]["target"] = "REQUIREMENT_DEVIATION"
        risk = deviation["risks"][0]
        risk["target_refs"] = ["REQUIREMENT_DEVIATION"]
        risk["evidence_refs"].append("ER")
        view = risk["target_views"][0]
        view.update(
            target="REQUIREMENT_DEVIATION",
            basis="合成固定需求",
            basis_refs=["ER"],
            comparison_rows=[
                {
                    "label": "规则和实现",
                    "left": {"statement": "合成规则要求", "evidence_refs": ["ER"]},
                    "right": {"statement": "合成代码行为", "evidence_refs": ["E2"]},
                }
            ],
        )
        validate({**data, "targets": ["BUG"]}, bug)
        validate({**data, "targets": ["REQUIREMENT_DEVIATION"]}, deviation)
        result = batch_merge.aggregate(data, plan(bug, deviation))
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(set(result["risks"][0]["target_refs"]), set(data["targets"]))
        self.assertEqual(len(result["risks"][0]["target_views"]), 2)
        self.assertEqual(result["outcome"], "COMPLETE")
        validate(data, result)

    def test_check_conflict_preserves_supported_risk_and_marks_partial(self):
        data, report = fixture()
        consistent = copy.deepcopy(report)
        consistent["risks"] = []
        consistent["summary"]["priority_risk_refs"] = []
        consistent["target_results"][0]["risk_refs"] = []
        check = consistent["target_results"][0]["checks"][0]
        check.update(assessment="CONSISTENT", risk_refs=[])
        for row in consistent["regression_scope"]:
            row["risk_refs"] = []
        validate(data, consistent)
        result = batch_merge.aggregate(data, plan(report, consistent))
        self.assertEqual(len(result["risks"]), 1)
        self.assertEqual(len(result["target_results"][0]["checks"]), 2)
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertTrue(any(x["code"] == "REVIEW_WARNING" for x in result["limitations"]))
        self.assertIn("跨批不一致", result["summary"]["conclusion"])
        validate(data, result)

    def test_conflicting_same_target_risk_retains_both_variants_for_review(self):
        data, report = fixture()
        other = copy.deepcopy(report)
        other["risks"][0]["target_views"][0]["expected"] = "另一批不同预期，待核对"
        result = batch_merge.aggregate(data, plan(report, other))
        self.assertEqual(len(result["risks"]), 2)
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertTrue(all(r["limitation_refs"] for r in result["risks"]))
        validate(data, result)

    def test_case_action_conflict_keeps_original_variants(self):
        data, report = fixture("requirement")
        other = copy.deepcopy(report)
        other["case_impacts"][0].update(action="KEEP", proposed_fields=[])
        other["regression_scope"][0]["action"] = "KEEP"
        validate(data, other)
        result = batch_merge.aggregate(data, plan(report, other))
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertEqual(
            {c["action"] for c in result["case_impacts"] if c["case_ref"] == "case-note"},
            {"KEEP", "UPDATE"},
        )
        self.assertTrue(
            any(
                x["code"] == "REVIEW_WARNING" and "case-note" in x["description"]
                for x in result["limitations"]
            )
        )
        validate(data, result)

    def test_pending_integration_cannot_be_complete_and_blocked_target_gets_gap(self):
        data, report = fixture()
        value = plan(report, report)
        value["batches"][1].update(status="QUEUED", depends_on=[1], report=None)
        result = batch_merge.aggregate(data, value)
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertTrue(any(x["code"] == "SCOPE_GAP" for x in result["limitations"]))
        value = {
            "version": 2,
            "batches": [
                {
                    "id": 1,
                    "status": "FAILED",
                    "callable": False,
                    "blocked_targets": ["BUG"],
                    "report": None,
                }
            ],
        }
        blocked = batch_merge.aggregate(data, value)
        self.assertEqual(blocked["outcome"], "BLOCKED")
        self.assertEqual(blocked["target_results"][0]["status"], "BLOCKED")
        validate(data, blocked)

    def test_conflicting_history_never_becomes_an_unqualified_improvement(self):
        data, report = fixture()
        data["historical_items"] = [
            {
                "history_ref": "h1",
                "module": "CODE_REVIEW",
                "report_id": 1,
                "item_key": "prior",
                "title": "旧问题",
                "statement": "合成历史",
                "handling_revision": 1,
                "handling_snapshot": "",
                "basis_refs": ["code-old", "code-new"],
                "review_warnings": [],
            }
        ]
        report["historical_reviews"] = [
            {
                "key": "H1",
                "history_ref": "h1",
                "result": "STILL_PRESENT",
                "note": "仍有证据",
                "evidence_refs": ["E1", "E2"],
                "risk_refs": ["R1"],
                "limitation_refs": [],
            }
        ]
        other = copy.deepcopy(report)
        other["historical_reviews"][0].update(result="STATIC_IMPROVED", note="本批改善判断")
        validate(data, report)
        validate(data, other)
        result = batch_merge.aggregate(data, plan(report, other))
        self.assertEqual(result["historical_reviews"][0]["result"], "UNVERIFIABLE")
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertEqual(len(result["risks"]), 1)
        self.assertTrue(result["historical_reviews"][0]["risk_refs"])
        validate(data, result)

    def test_failed_related_batch_cannot_upgrade_one_batch_history_improvement(self):
        data, report = fixture()
        data["historical_items"] = [
            {
                "history_ref": "h1",
                "module": "CODE_REVIEW",
                "report_id": 1,
                "item_key": "prior",
                "title": "旧问题",
                "statement": "合成历史",
                "handling_revision": 1,
                "handling_snapshot": "",
                "basis_refs": ["code-old", "code-new"],
                "review_warnings": [],
            }
        ]
        report["historical_reviews"] = [
            {
                "key": "H1",
                "history_ref": "h1",
                "result": "STATIC_IMPROVED",
                "note": "本批静态判断",
                "evidence_refs": ["E1", "E2"],
                "risk_refs": [],
                "limitation_refs": [],
            }
        ]
        value = plan(report, report)
        value["batches"][1].update(status="FAILED", report=None)
        result = batch_merge.aggregate(data, value)
        self.assertEqual(result["historical_reviews"][0]["result"], "UNVERIFIABLE")
        self.assertEqual(result["outcome"], "PARTIAL")
        validate(data, result)

    def test_long_summary_is_preserved_in_contiguous_limitations(self):
        data, report = fixture()
        other = copy.deepcopy(report)
        report["summary"]["conclusion"] = "甲" * 9000
        other["summary"]["conclusion"] = "乙" * 9000
        result = batch_merge.aggregate(data, plan(report, other))
        self.assertLessEqual(len(result["summary"]["conclusion"]), 10000)
        retained = "".join(x["description"] for x in result["limitations"])
        self.assertIn("甲" * 9000, retained)
        self.assertIn("乙" * 9000, retained)
        validate(data, result)
