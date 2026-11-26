import copy
import json
import unittest
from pathlib import Path

from app.core.errors import AppError
from app.modules.change_analysis import contract, legacy_batches

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


def saved_plan(data):
    batches = []
    for pair in data["comparison_pairs"]:
        for diff in pair["text_diffs"]:
            mapping = [[pair["pair_id"], diff["mapping_ref"]]]
            batch = {
                "id": len(batches) + 1,
                "primary": mapping,
                "mappings": mapping,
                "context_units": {},
                "case_refs": [case["case_ref"] for case in data["cases"]],
                "history_refs": [item["history_ref"] for item in data["historical_items"]],
                "status": "QUEUED",
                "error_code": "",
                "report": None,
                "candidate_task_id": None,
                "attempts": [],
            }
            subset = legacy_batches.input_for(data, batch)
            batch["input_bytes"] = len(json.dumps(subset, ensure_ascii=False).encode())
            batch["files"] = [
                unit["path"] for source in subset["snapshots"] for unit in source["units"]
            ]
            batches.append(batch)
    return {"version": 1, "input_hash": "f" * 64, "batches": batches}


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
        plan = saved_plan(data)
        plan["batches"][0].update(status="COMPLETED", report=reply(report, plan["batches"][0]))
        plan["batches"][1].update(status="FAILED", error_code="ai_gateway_timeout")
        merged = legacy_batches.aggregate(data, plan)
        self.assertEqual(merged["historical_reviews"][0]["result"], "UNVERIFIABLE")

    def test_batches_preserve_versions_and_merge_references_without_another_model_call(self):
        data, report = fixture()
        original = copy.deepcopy(data)
        plan = saved_plan(data)
        self.assertEqual(len(plan["batches"]), 2)
        for batch in plan["batches"]:
            subset = legacy_batches.input_for(data, batch)
            contract.validate_input(contract.AnalysisInput.model_validate(subset))
            self.assertEqual([len(s["units"]) for s in subset["snapshots"]], [1, 1])
            batch.update(status="COMPLETED", report=reply(report, batch))
        merged = legacy_batches.aggregate(data, plan)
        self.assertEqual(len(merged["risks"]), 2)
        self.assertEqual(len({r["key"] for r in merged["risks"]}), 2)
        self.assertEqual(len(merged["coverage"]), 4)
        self.assertEqual(merged["outcome"], "PARTIAL")
        self.assertEqual(data, original)
        retried = {**data, "request_id": "manual-retry"}
        self.assertEqual(legacy_batches.aggregate(retried, plan)["request_id"], "manual-retry")

    def test_failed_batch_is_unprocessed_and_does_not_erase_successful_evidence(self):
        data, report = fixture()
        plan = saved_plan(data)
        plan["batches"][0].update(status="COMPLETED", report=reply(report, plan["batches"][0]))
        plan["batches"][1].update(status="FAILED", error_code="ai_gateway_timeout")
        merged = legacy_batches.aggregate(data, plan)
        self.assertEqual(len(merged["risks"]), 1)
        missing = [c for c in merged["coverage"] if c["unit_id"] == "u2"]
        self.assertTrue(all(c["status"] == "PARTIAL" for c in missing))
        self.assertTrue(all(c["segment_reviews"][0]["status"] == "UNPROCESSED" for c in missing))
        self.assertEqual(legacy_batches.summary(plan)["failed"], 1)
        with self.assertRaises(AppError):
            legacy_batches.validate_result(
                data, plan["batches"][0], reply(report, plan["batches"][1])
            )
