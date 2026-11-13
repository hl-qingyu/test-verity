import copy
import json
import unittest
from pathlib import Path

from app.core.errors import AppError
from app.modules.change_analysis import batch_execution

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/change-impact/examples"


class AssociationExecutionTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((EXAMPLES / "code-input.json").read_text(encoding="utf-8"))
        self.report = json.loads((EXAMPLES / "code-report.json").read_text(encoding="utf-8"))
        self.batch = {
            "plan_version": 2,
            "kind": "INTEGRATION",
            "mappings": [["p1", "m1"]],
            "context_units": {},
            "case_refs": [],
            "history_refs": [],
            "blocked_targets": [],
            "limitations": [],
        }
        self.previous = [{"id": n, "report": copy.deepcopy(self.report)} for n in (1, 2)]
        self.decision = {
            "kind": "SAME_ROOT",
            "risk_refs": [{"batch_id": n, "key": "R1"} for n in (1, 2)],
            "result_risk_key": "R1",
            "note": "同一旧新代码片段支持相同根因，合并保留两批来源",
        }

    def test_integration_decisions_are_bound_to_supplied_risks_and_actual_source_anchors(self):
        raw = json.dumps(
            {"report": self.report, "reconciliations": [self.decision]}, ensure_ascii=False
        )
        output, _ = batch_execution.candidate(self.data, self.batch, raw, previous=self.previous)
        self.assertEqual(output["risks"][0]["key"], "R1")
        self.assertEqual(self.batch["reconciliations"], [self.decision])
        for change in (
            "foreign_batch",
            "foreign_risk",
            "missing_result",
            "untrusted_type",
            "blank_note",
        ):
            decision = copy.deepcopy(self.decision)
            if change == "foreign_batch":
                decision["risk_refs"][0]["batch_id"] = 99
            if change == "foreign_risk":
                decision["risk_refs"][0]["key"] = "invented"
            if change == "missing_result":
                decision["result_risk_key"] = "invented"
            if change == "untrusted_type":
                decision["kind"] = []
            if change == "blank_note":
                decision["note"] = "   "
            with self.subTest(change=change), self.assertRaises(AppError):
                batch_execution.validate_reconciliations([decision], self.previous, self.report)
        other = copy.deepcopy(self.previous)
        for evidence in other[0]["report"]["evidence"]:
            evidence["snapshot_ref"] = "unprovided-source"
        with self.assertRaises(AppError):
            batch_execution.validate_reconciliations([self.decision], other, self.report)

    def test_merging_findings_preserves_human_history_and_conflicts_need_review(self):
        def handled(status, at):
            event = {
                "status": status,
                "note": "人工核查",
                "actor_id": 7,
                "actor_name": "测试",
                "at": at,
            }
            return {**event, "history": [{**event, "previous_status": "PENDING"}]}

        report = {group: [] for group in batch_execution.batching.GROUPS}
        report["risks"] = [{"key": "merged"}]
        original = {
            "old-one": handled("CONFIRMED", "2026-10-26T01:00:00Z"),
            "old-two": handled("FALSE_POSITIVE", "2026-10-26T02:00:00Z"),
        }
        plan = {"result_aliases": {"old-one": "merged", "old-two": "merged"}}
        before = copy.deepcopy(original)
        result = batch_execution.reconcile_handling(original, report, plan)
        self.assertEqual(result["merged"]["status"], "PENDING")
        self.assertEqual(len(result["merged"]["history"]), 3)
        self.assertEqual(plan["handling_merge_audit"][0]["original"], original)
        self.assertEqual(original, before)
        same = {"old-one": original["old-one"]}
        merged = batch_execution.reconcile_handling(
            same, report, {"result_aliases": {"old-one": "merged"}}
        )
        self.assertEqual(merged["merged"]["status"], "CONFIRMED")
        self.assertEqual(merged["merged"]["history"], same["old-one"]["history"])

    def test_review_can_express_transitive_same_root_relations(self):
        previous = [*self.previous, {"id": 3, "report": copy.deepcopy(self.report)}]
        second = {
            **copy.deepcopy(self.decision),
            "risk_refs": [{"batch_id": n, "key": "R1"} for n in (2, 3)],
        }
        decisions = [self.decision, second]
        self.assertEqual(
            batch_execution.validate_reconciliations(decisions, previous, self.report), decisions
        )

    def test_review_can_merge_one_prior_risk_with_its_current_evidence_based_risk(self):
        decision = {**self.decision, "risk_refs": [{"batch_id": 1, "key": "R1"}]}
        self.assertEqual(
            batch_execution.validate_reconciliations([decision], self.previous[:1], self.report),
            [decision],
        )
        with self.assertRaises(AppError):
            batch_execution.validate_reconciliations(
                [{**decision, "kind": "CONFLICT", "result_risk_key": ""}],
                self.previous,
                self.report,
            )
