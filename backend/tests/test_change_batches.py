import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.errors import AppError
from app.modules.change_analysis import batching, contract

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/change-impact/examples"


def fixture():
    data = json.loads((EXAMPLES / "code-input.json").read_text(encoding="utf-8"))
    report = json.loads((EXAMPLES / "code-report.json").read_text(encoding="utf-8"))
    for s in data["snapshots"]:
        original = s["units"][0]
        original["path"] = "First.py"
        other = copy.deepcopy(original)
        other.update(unit_id="u2", path="Second.py")
        s["units"].append(other)
    pair = data["comparison_pairs"][0]
    pair["unit_mappings"].append(
        {
            **copy.deepcopy(pair["unit_mappings"][0]),
            "mapping_id": "m2",
            "before_unit_ids": ["u2"],
            "after_unit_ids": ["u2"],
        }
    )
    diff = copy.deepcopy(pair["text_diffs"][0])
    diff.update(diff_id="d2", mapping_ref="m2")
    for side in ("before", "after"):
        diff[side + "_segment_refs"][0]["unit_id"] = "u2"
    pair["text_diffs"].append(diff)
    return data, report


def reply(report, batch):
    second = batch["primary"] == [["p1", "m2"]]

    def walk(value):
        if isinstance(value, dict):
            return {k: walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v) for v in value]
        return (
            {"u1": "u2", "m1": "m2", "d1": "d2"}.get(value, value)
            if second and isinstance(value, str)
            else value
        )

    return walk(copy.deepcopy(report))


class ChangeBatchTests(unittest.TestCase):
    def test_one_successful_batch_cannot_mark_history_improved_when_another_batch_failed(self):
        data, report = fixture()
        data["historical_items"] = [
            {
                "history_ref": "h1",
                "module": "CODE_REVIEW",
                "report_id": 1,
                "item_key": "old-risk",
                "title": "历史问题",
                "statement": "合成问题",
                "handling_revision": 1,
                "handling_snapshot": "",
                "basis_refs": ["code-old", "code-new"],
                "review_warnings": [],
            }
        ]
        refs = [
            next(e["key"] for e in report["evidence"] if e["side"] == side)
            for side in ("BEFORE", "AFTER")
        ]
        report["historical_reviews"] = [
            {
                "key": "H1",
                "history_ref": "h1",
                "result": "STATIC_IMPROVED",
                "note": "合成单批结论",
                "evidence_refs": refs,
                "risk_refs": [],
                "limitation_refs": [],
            }
        ]
        with patch.object(batching, "LEGACY_TARGET_BYTES", 1):
            plan = batching.plan(data, version=1)
        plan["batches"][0].update(status="COMPLETED", report=reply(report, plan["batches"][0]))
        plan["batches"][1].update(status="FAILED", error_code="ai_gateway_timeout")
        merged = batching.aggregate(data, plan)
        self.assertEqual(merged["historical_reviews"][0]["result"], "UNVERIFIABLE")

    def test_batches_preserve_versions_and_merge_references_without_another_model_call(self):
        data, report = fixture()
        original = copy.deepcopy(data)
        with patch.object(batching, "LEGACY_TARGET_BYTES", 1):
            plan = batching.plan(data, version=1)
        self.assertEqual(len(plan["batches"]), 2)
        for batch in plan["batches"]:
            subset = batching.input_for(data, batch)
            contract.validate_input(contract.AnalysisInput.model_validate(subset))
            self.assertEqual([len(s["units"]) for s in subset["snapshots"]], [1, 1])
            batch.update(status="COMPLETED", report=reply(report, batch))
        merged = batching.aggregate(data, plan)
        self.assertEqual(len(merged["risks"]), 2)
        self.assertEqual(len({r["key"] for r in merged["risks"]}), 2)
        self.assertEqual(len(merged["coverage"]), 4)
        self.assertEqual(merged["outcome"], "PARTIAL")
        self.assertEqual(data, original)
        retried = {**data, "request_id": "manual-retry"}
        self.assertEqual(batching.fingerprint(data), batching.fingerprint(retried))
        self.assertEqual(batching.aggregate(retried, plan)["request_id"], "manual-retry")

    def test_failed_batch_is_unprocessed_and_does_not_erase_successful_evidence(self):
        data, report = fixture()
        with patch.object(batching, "LEGACY_TARGET_BYTES", 1):
            plan = batching.plan(data, version=1)
        plan["batches"][0].update(status="COMPLETED", report=reply(report, plan["batches"][0]))
        plan["batches"][1].update(status="FAILED", error_code="ai_gateway_timeout")
        merged = batching.aggregate(data, plan)
        self.assertEqual(len(merged["risks"]), 1)
        missing = [c for c in merged["coverage"] if c["unit_id"] == "u2"]
        self.assertTrue(all(c["status"] == "PARTIAL" for c in missing))
        self.assertTrue(all(c["segment_reviews"][0]["status"] == "UNPROCESSED" for c in missing))
        self.assertEqual(batching.summary(plan)["failed"], 1)
        with self.assertRaises(AppError):
            batching.validate_result(data, plan["batches"][0], reply(report, plan["batches"][1]))

    def test_static_dependency_candidate_is_carried_without_losing_full_fixed_input(self):
        data, _ = fixture()
        data["comparison_pairs"][0]["text_diffs"] = data["comparison_pairs"][0]["text_diffs"][:1]
        for s in data["snapshots"]:
            unit = s["units"][0]
            unit["segments"][0]["text"] += "\n# Second"
            unit["content_sha256"] = hashlib.sha256(
                unit["segments"][0]["text"].encode()
            ).hexdigest()
        original = copy.deepcopy(data)
        with patch.object(batching, "LEGACY_TARGET_BYTES", 1):
            plan = batching.plan(data, version=1)
        self.assertEqual(plan["batches"][0]["primary"], [["p1", "m1"]])
        self.assertIn(["p1", "m2"], plan["batches"][0]["mappings"])
        self.assertEqual(data, original)
