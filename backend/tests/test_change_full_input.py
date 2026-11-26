import base64
import copy
import hashlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.integrations import responses
from app.modules.change_analysis import comparison, contract, model_view
from app.modules.requirements.analysis_materials import model_content
from tests.test_response_input import restore

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/change-impact/examples"


class ChangeFullInputTests(unittest.TestCase):
    def test_v3_keeps_large_unchanged_ranges_as_metadata(self):
        data = json.loads((EXAMPLES / "code-input.json").read_text(encoding="utf-8"))
        pair = data["comparison_pairs"][0]
        body = "UNCHANGED_FIXED_CONTENT\n" * 200
        for number in range(1, 3001):
            uid = f"same-{number}"
            for snapshot in data["snapshots"]:
                unit = copy.deepcopy(snapshot["units"][0])
                unit.update(unit_id=uid, path=f"same-{number}.py")
                unit["segments"][0]["text"] = body
                unit["content_sha256"] = hashlib.sha256(body.encode()).hexdigest()
                snapshot["units"].append(unit)
            pair["unit_mappings"].append(
                {
                    **pair["unit_mappings"][0],
                    "mapping_id": uid,
                    "before_unit_ids": [uid],
                    "after_unit_ids": [uid],
                }
            )
        projected = model_view.build(data, "RESPONSES_API")
        self.assertEqual(projected["view"]["omitted_unit_count"], 6000)
        self.assertNotIn(body[:100], json.dumps(projected, ensure_ascii=False))
        self.assertEqual(projected["comparison_pairs"][0]["unchanged_mapping_count"], 3000)
        self.assertIn("@@", projected["comparison_pairs"][0]["text_diffs"][0]["hunks"])

    def test_one_http_request_contains_all_fixed_input_and_original_binary(self):
        data = json.loads((EXAMPLES / "code-input.json").read_text(encoding="utf-8"))
        rules = json.loads((EXAMPLES / "requirement-input.json").read_text(encoding="utf-8"))[
            "snapshots"
        ]
        for n, original in enumerate(rules, 1):
            source = copy.deepcopy(original)
            source["snapshot_ref"] = f"rule-{n}"
            source["units"][0]["segments"][0]["text"] = "完整规则😀\n" * 200000
            source["units"][0]["content_sha256"] = hashlib.sha256(
                "\n".join(s["text"] for s in source["units"][0]["segments"]).encode()
            ).hexdigest()
            data["snapshots"].append(source)
            data["context_refs"].append(source["snapshot_ref"])
        data["cases"] = [
            {
                "case_ref": "case-1",
                "case_id": 1,
                "design_version": 2,
                "library_revision": 3,
                "display_number": "TC-001",
                "title": "固定用例全文",
                "design": {
                    "preconditions": "完整条件",
                    "data_requirements": "完整数据",
                    "steps": "第一步\n第二步",
                    "expected": "原始预期",
                },
            }
        ]
        data["historical_items"] = [
            {
                "history_ref": "history-1",
                "module": "CODE_REVIEW",
                "report_id": 1,
                "item_key": "risk-1",
                "title": "固定旧问题",
                "statement": "原始完整问题",
                "handling_revision": 2,
                "handling_snapshot": "人工处理原文",
                "basis_refs": ["code-old"],
                "review_warnings": ["旧版本尚待核对"],
            }
        ]
        attachment = {
            "snapshot_ref": "attachment",
            "source_id": "attachment",
            "kind": "PROTOTYPE",
            "repository_kind": "NONE",
            "name": "完整PDF",
            "provenance": {
                "source_kind": "UPLOAD",
                "version_ref": "fixed-v1",
                "commit": "",
                "captured_at": "2026-10-26T00:00:00Z",
            },
            "scope_complete": True,
            "scope_note": "",
            "units": [
                {
                    "unit_id": "pdf",
                    "path": "prototype.pdf",
                    "presence": "PRESENT",
                    "read_state": "READABLE",
                    "read_note": "",
                    "content_sha256": hashlib.sha256(b"").hexdigest(),
                    "segments": [
                        {
                            "segment_id": "pdf",
                            "location": "整份PDF",
                            "start_line": None,
                            "text": "",
                            "image_ref": "attachment",
                        }
                    ],
                }
            ],
        }
        data["snapshots"].append(attachment)
        data["context_refs"].append("attachment")
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        original = copy.deepcopy(data)
        report = comparison.unchanged_report(data)
        contract.validate_report(
            contract.AnalysisInput.model_validate(data), contract.Report.model_validate(report)
        )
        completed = {
            "status": "completed",
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(report, ensure_ascii=False),
                        }
                    ]
                }
            ],
        }
        response = io.BytesIO(
            (
                "data: "
                + json.dumps(
                    {
                        "type": "response.completed",
                        "response": completed,
                    },
                    ensure_ascii=False,
                )
                + "\n\n"
            ).encode()
        )
        response.headers = {"Content-Type": "text/event-stream"}
        opener = MagicMock()
        opener.open.return_value = response
        binary = b"%PDF-synthetic-original\n"
        file = MagicMock(spec=Path)
        file.read_bytes.return_value = binary
        stats = {}
        with patch("app.integrations.responses.build_opener", return_value=opener):
            output = responses.analyze(
                "https://example.invalid",
                "model",
                "synthetic-key",
                "high",
                "fixed Skill",
                model_content(
                    data, [(file, "pdf", "attachment", "prototype.pdf")], attachment_key="image_ref"
                ),
                diagnostics=stats,
            )
        opener.open.assert_called_once()
        self.assertIsNone(opener.open.call_args.kwargs["timeout"])
        payload = json.loads(opener.open.call_args.args[0].data)
        parts = payload["input"][0]["content"]
        texts = [p["text"] for p in parts if p["type"] == "input_text"]
        self.assertEqual(restore("".join(texts[:-1])), original)
        self.assertEqual(base64.b64decode(parts[-1]["file_data"].split(",", 1)[1]), binary)
        self.assertEqual(data, original)
        self.assertEqual(json.loads(output), report)
        self.assertGreater(stats["reused_text_count"], 0)
        self.assertGreater(stats["split_text_count"], 0)
        self.assertTrue(response.closed)
