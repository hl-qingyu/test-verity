import copy
import hashlib
import json
import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import test_auth
import test_requirements
from pydantic import ValidationError
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    AIConnection,
    CaseCategory,
    CaseGenerationApplication,
    CaseGenerationBatch,
    CaseGenerationRun,
    Project,
    UserAccount,
)
from app.integrations.response_diagnostics import safe_snapshot
from app.modules.case_generation import apply, chat, compact, contract, execution, service, sources
from app.modules.case_generation.schemas import ApplicationItem, MaterialSelection
from app.modules.cases.schemas import COLUMNS, DESIGN_FIELDS
from app.modules.requirements import analysis_materials

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/case-generation/examples"


def sample(name):
    return tuple(
        json.loads((EXAMPLES / f"{name}-{kind}.json").read_text(encoding="utf-8"))
        for kind in ("input", "report")
    )


class GenerationContractTests(unittest.TestCase):
    def test_ai_missing_new_title_uses_exact_description_and_marks_review_without_mutating_raw(
        self,
    ):
        data, output = sample("compact")
        case = next(c for c in output["cases"] if c["action"] == "NEW")
        output["cases"] = [case]
        original_title = case["design"].pop("title")
        case["note"] = "已有比较限制。"
        original = copy.deepcopy(output)
        with self.assertRaises(AppError):
            contract.validate_report(data, original)
        normalized, fields = contract.normalize_ai_report(output)
        self.assertEqual(output, original)
        self.assertEqual(normalized["cases"][0]["design"]["title"], case["design"]["description"])
        self.assertNotEqual(normalized["cases"][0]["design"]["title"], original_title)
        self.assertEqual(normalized["cases"][0]["design"]["steps"], case["design"]["steps"])
        self.assertEqual(normalized["cases"][0]["design"]["expected"], case["design"]["expected"])
        self.assertEqual(normalized["cases"][0]["sources"], case["sources"])
        self.assertEqual(normalized["cases"][0]["evidence_quotes"], case["evidence_quotes"])
        self.assertEqual(fields, ["cases[0].design.title", "cases[0].note"])
        self.assertIn("已有比较限制。", normalized["cases"][0]["note"])
        self.assertIn("原样沿用用例描述", normalized["cases"][0]["note"])
        saved = contract.validate_report(data, normalized)
        self.assertEqual(saved["suggestions"][0]["basis_status"], "NEEDS_REVIEW")
        self.assertEqual(contract.normalize_ai_report(normalized), (normalized, []))
        self.assertEqual(contract.validate_report(data, saved), saved)
        update = copy.deepcopy(original)
        update["cases"][0].update(action="UPDATE", target="case-1")
        update["cases"][0]["design"] = {"description": "验证当前明确的提交路径。"}
        kept, fields = contract.normalize_ai_report(update)
        self.assertEqual(fields, [])
        self.assertNotIn("title", kept["cases"][0]["design"])
        updated = contract.validate_report(data, kept)
        self.assertEqual(
            [c["field"] for c in updated["suggestions"][0]["changes"]], ["description"]
        )
        for field in ("description", "steps", "expected"):
            invalid = copy.deepcopy(original)
            invalid["cases"][0]["design"].pop(field)
            repaired, _ = contract.normalize_ai_report(invalid)
            with self.subTest(field=field), self.assertRaises(AppError):
                contract.validate_report(data, repaired)
        invented = copy.deepcopy(normalized)
        invented["cases"][0]["evidence_quotes"][0]["quote"] = "不存在于固定资料的伪造摘录"
        warned = contract.validate_report(data, invented)
        self.assertTrue(any(e.get("quote_verified") is False for e in warned["evidence"]))
        self.assertEqual(warned["model_output"], invented)

    def test_design_quality_v3_pair_preserves_patches_sources_and_literal_test_data(self):
        data, report = sample("design-quality")
        saved = contract.validate_report(data, report)
        self.assertEqual(saved["model_output"], report)
        self.assertEqual(saved["outcome"], "PARTIAL")
        self.assertEqual(len(saved["suggestions"]), 9)
        self.assertEqual(saved["suggestions"][0]["kind"], "REUSE")
        update = next(s for s in saved["suggestions"] if s["kind"] == "UPDATE")
        self.assertEqual([c["field"] for c in update["changes"]], ["expected"])
        self.assertIn("30元", update["changes"][0]["after"])
        self.assertEqual(len(COLUMNS), 14)
        for case in report["cases"]:
            if case["action"] == "NEW":
                self.assertTrue(all(isinstance(v, str) for v in case["design"].values()))
                self.assertTrue(
                    all(
                        case["design"][f].strip()
                        for f in ("structure", "case_type", "priority", "description")
                    )
                )
        payload = "\n".join(c["text"] for c in compact.model_content(data, []))
        self.assertIn("A  B", json.dumps(report, ensure_ascii=False))
        self.assertIn(data["materials"][0]["segments"][1]["text"], payload)

    def test_compact_quote_across_contiguous_file_segments_keeps_exact_evidence(self):
        data, _ = sample("initial")
        data["contract_version"] = 3
        material = data["materials"][0]
        quote = "每次赠送使用唯一操作编号；结果未知先查询原记录，超时只补未完成步骤。"
        material["segments"] = analysis_materials.text_segments(
            "x" * 15992 + quote + "y" * 100, "prototype/annotations.js"
        )
        material["content_sha256"] = hashlib.sha256(
            "\n".join(s["text"] for s in material["segments"]).encode()
        ).hexdigest()
        output = {
            "cases": [
                {
                    "action": "NEW",
                    "sources": [material["snapshot_ref"]],
                    "design": {"title": "跨段摘录", "steps": "提交", "expected": "只完成一次"},
                    "evidence_quotes": [{"source": material["snapshot_ref"], "quote": quote}],
                }
            ],
            "notes": [],
            "complete": True,
        }
        frozen = copy.deepcopy((data, output))
        report = contract.validate_report(data, output)
        evidence = report["evidence"][-1]
        self.assertEqual(evidence["quote"], quote)
        self.assertEqual(evidence["segment_id"], "")
        self.assertEqual(contract.validate_report(data, report), report)
        self.assertEqual((data, output), frozen)
        for location in (
            "other.js · 字符16001–16100",
            "prototype/annotations.js · 字符16002–16101",
        ):
            invalid = copy.deepcopy(data)
            invalid["materials"][0]["segments"][1]["location"] = location
            warned = contract.validate_report(invalid, output)
            self.assertFalse(warned["evidence"][-1]["quote_verified"])
            self.assertEqual(warned["evidence"][-1]["segment_id"], "")
        for invented in (quote.replace("只补", "不补"), quote.replace("；", ",")):
            invalid = copy.deepcopy(output)
            invalid["cases"][0]["evidence_quotes"][0]["quote"] = invented
            warned = contract.validate_report(data, invalid)
            self.assertFalse(warned["evidence"][-1]["quote_verified"])
            self.assertEqual(warned["evidence"][-1]["quote"], invented)

    def test_timing_uses_current_attempt_and_freezes_terminal_progress(self):
        attempt = {
            "request_id": "current",
            "started_at": "2026-10-16T12:00:00+08:00",
            "progress_at": "2026-10-16T13:02:03+08:00",
        }
        for status in ("COMPLETED", "FAILED", "CANCELLED"):
            self.assertEqual(
                service.batch_timing("current", status, attempt),
                {"startedAt": attempt["started_at"], "finishedAt": attempt["progress_at"]},
            )
        self.assertIsNone(service.batch_timing("current", "RUNNING", attempt)["finishedAt"])
        self.assertIsNone(service.batch_timing("retry", "QUEUED", attempt)["startedAt"])
        self.assertIsNone(service.batch_timing("current", "FAILED", {})["startedAt"])
        self.assertIsNone(
            service.batch_timing(
                "current", "FAILED", {"request_id": "current", "started_at": attempt["started_at"]}
            )["startedAt"]
        )

    def test_compact_case_quotes_are_verified_per_source_and_old_views_stay_compatible(self):
        data, _ = sample("initial")
        data["contract_version"] = 3
        material = data["materials"][0]
        ref = material["snapshot_ref"]
        quote = material["segments"][0]["text"][:80]
        output = {
            "cases": [
                {
                    "action": "NEW",
                    "sources": [ref],
                    "design": {
                        "title": "合成证据用例",
                        "steps": "提交",
                        "expected": "业务完成",
                    },
                    "evidence_quotes": [{"source": ref, "quote": quote}],
                }
            ],
            "notes": [],
            "complete": True,
        }
        original = copy.deepcopy(output)
        report = contract.validate_report(data, output)
        self.assertEqual(output, original)
        suggestion = report["suggestions"][0]
        cited = [e for e in report["evidence"] if e["key"] in suggestion["evidence_refs"]]
        self.assertEqual(cited[0]["quote"], quote)
        self.assertEqual(cited[0]["segment_id"], material["segments"][0]["segment_id"])
        self.assertEqual(contract.validate_report(data, report), report)
        for excerpt_change in [
            {"source": "missing", "quote": quote},
            {"source": ref, "quote": ""},
        ]:
            invalid = copy.deepcopy(output)
            invalid["cases"][0]["evidence_quotes"] = [excerpt_change]
            with self.assertRaises(AppError):
                contract.validate_report(data, invalid)
        old = copy.deepcopy(output)
        del old["cases"][0]["evidence_quotes"]
        legacy = contract.validate_report(data, old)
        self.assertEqual(legacy["evidence"][0]["quote"], "")
        self.assertEqual(contract.validate_report(data, legacy), legacy)

    def test_unmatched_quote_is_a_warning_and_never_changes_business_or_source_identity(self):
        data, original = sample("compact")
        output = copy.deepcopy(original)
        case = next(c for c in output["cases"] if c["action"] == "NEW")
        case["evidence_quotes"][0]["quote"] = "固定来源未提供这段AI文字"
        output["cases"] = [case]
        output["notes"] = []
        output["complete"] = True
        frozen = copy.deepcopy((data, output))
        saved = contract.validate_report(data, output)
        self.assertEqual((data, output), frozen)
        self.assertEqual(saved["model_output"], output)
        self.assertEqual(saved["outcome"], "COMPLETE")
        self.assertEqual(
            saved["suggestions"][0]["design"],
            contract.validate_report(
                data,
                {
                    **output,
                    "cases": [{**case, "evidence_quotes": []}],
                },
            )["suggestions"][0]["design"],
        )
        unverified = next(e for e in saved["evidence"] if e.get("quote_verified") is False)
        self.assertEqual(unverified["quote"], case["evidence_quotes"][0]["quote"])
        self.assertEqual(unverified["target_ref"], case["evidence_quotes"][0]["source"])
        self.assertEqual(unverified["segment_id"], "")
        self.assertTrue(any("不影响候选保存" in text for text in saved["limitations"]))
        self.assertEqual(contract.validate_report(data, saved), saved)
        altered = copy.deepcopy(saved)
        next(e for e in altered["evidence"] if e.get("quote_verified") is False)[
            "quote_verified"
        ] = True
        with self.assertRaisesRegex(AppError, "generation_compact_projection_mismatch"):
            contract.validate_report(data, altered)
        for invalid_source in ("unknown-snapshot", "case-1"):
            invalid = copy.deepcopy(output)
            invalid["cases"][0]["evidence_quotes"][0]["source"] = invalid_source
            with self.assertRaises(AppError):
                contract.validate_report(data, invalid)

    def test_application_categories_distinguish_keep_clear_and_set(self):
        base = {"key": "C1", "draft_revision": 0}
        self.assertEqual(ApplicationItem(**base).category_mode, "KEEP")
        for mode, category_id in [
            ("KEEP", 7),
            ("CLEAR", 7),
            ("SET", None),
            ("SET", 0),
            ("UNKNOWN", None),
        ]:
            with self.assertRaises(ValidationError):
                ApplicationItem(**base, category_mode=mode, category_id=category_id)
        self.assertEqual(ApplicationItem(**base, category_mode="SET", category_id=7).category_id, 7)
        self.assertIsNone(ApplicationItem(**base, category_mode="CLEAR").category_id)

    def test_four_examples_and_corrupt_candidates(self):
        for name in ("initial", "update", "clarification", "no-baseline"):
            contract.validate_report(*sample(name))
        for name, mutate in (
            ("initial", lambda r: r.update(project_id=2)),
            ("initial", lambda r: r.update(outcome="COMPLETE")),
            ("initial", lambda r: r["evidence"][0].update(side="BEFORE")),
            ("initial", lambda r: r["evidence"][0].update(quote="invented")),
            ("initial", lambda r: r["suggestions"][1]["design"].update(result="通过")),
            ("initial", lambda r: r["coverage"]["input_units"].pop()),
            ("initial", lambda r: r["coverage"]["branches"].pop()),
            ("update", lambda r: r["suggestions"][0]["changes"][0].update(before="not C")),
            (
                "update",
                lambda r: r["conflicts"][0]["field_comparisons"][0].update(baseline="invented G"),
            ),
            ("no-baseline", lambda r: r["suggestions"][0].update(basis_status="SUPPORTED")),
        ):
            data, report = sample(name)
            mutate(report)
            with self.assertRaises(AppError):
                contract.validate_report(data, report)
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"):
            with self.assertRaises(AppError):
                contract.read(raw)

    def test_business_design_with_pending_setup_can_produce_reviewable_case(self):
        data, report = sample("clarification")
        scenario = report["scenarios"][0]
        scenario["state"] = "DESIGN_READY_SETUP_PENDING"
        scenario["entry"] = ""
        scenario["note"] = "业务规则明确，执行准备待补：观察入口需核对。"
        suggestion = report["suggestions"][0]
        suggestion["basis_status"] = "NEEDS_REVIEW"
        suggestion["design"]["data_requirements"] = "执行前准备隔离订单，确认库存观察权限和入口。"
        suggestion["design"]["remark"] = "执行准备待补，执行前需核对，不代表已测。"
        gap = {
            "key": data["batch"]["namespace"] + ":SETUP",
            "kind": "EXECUTION_SETUP",
            "function_ref": scenario["function_ref"],
            "scenario_refs": [scenario["key"]],
            "case_refs": [],
            "material_refs": [data["materials"][0]["snapshot_ref"]],
            "reason": "库存观察入口未提供",
            "next_step": "执行前确认观察方法和权限",
        }
        report["discovery_gaps"].append(gap)
        report["coverage"]["functions"][0]["issue_refs"].append(gap["key"])
        report["coverage"]["functions"][0]["state"] = "PARTIAL"
        report["outcome"] = "PARTIAL"
        contract.validate_report(data, report)
        for mutation in (
            lambda r: r["discovery_gaps"].clear(),
            lambda r: r["suggestions"][0]["design"].update(data_requirements=""),
            lambda r: r["suggestions"][0].update(basis_status="SUPPORTED"),
            lambda r: r["scenarios"][0].update(state="PENDING_DECISION"),
            lambda r: r.update(outcome="COMPLETE"),
            lambda r: r["evidence"][0].update(quote="invented"),
        ):
            invalid = copy.deepcopy(report)
            mutation(invalid)
            with self.assertRaises(AppError):
                contract.validate_report(data, invalid)

    def test_compact_output_has_no_analysis_graph_and_keeps_all_80_cases(self):
        data, _ = sample("initial")
        data["contract_version"] = 3
        # PARTIAL means static source boundary, not a failed business-generation declaration.
        data["materials"][0]["read_state"] = "PARTIAL"
        data["materials"][0]["read_note"] = "完整正文和批注已固定，不执行脚本。"
        source = data["materials"][0]["snapshot_ref"]
        output = {
            "cases": [
                {
                    "action": "NEW",
                    "sources": [source],
                    "design": {
                        "title": f"合成场景{i}",
                        "steps": ["执行取消", "核对订单"],
                        "expected": "释放占用库存",
                        "data_requirements": "执行前核对库存观察入口",
                        "remark": "执行准备待补",
                    },
                }
                for i in range(80)
            ],
            "notes": [{"kind": "EXECUTION_SETUP", "text": "观察入口待补", "sources": [source]}],
            "complete": True,
        }
        original = copy.deepcopy(output)
        normalized, fields = contract.normalize_ai_report(output)
        report = contract.validate_report(data, normalized)
        self.assertEqual(output, original)
        self.assertEqual(len(report["suggestions"]), 80)
        self.assertEqual(len(fields), 80)
        self.assertEqual(report["suggestions"][0]["design"]["steps"], "执行取消\n核对订单")
        self.assertEqual(report["outcome"], "COMPLETE")
        self.assertTrue(
            all(k not in report for k in ["rules", "scenarios", "coverage", "transitions", "flows"])
        )
        self.assertEqual(contract.validate_report(data, report), report)
        report["suggestions"][0]["design"]["title"] = "tampered platform view"
        with self.assertRaises(AppError):
            contract.validate_report(data, report)
        for mutation in [
            lambda r: r["cases"][0].update(sources=["missing"]),
            lambda r: r["cases"][0]["design"].update(tester="伪造"),
            lambda r: r["cases"][0].update(target="case-unknown"),
            lambda r: r["cases"][0]["design"].update(expected=""),
            lambda r: r["cases"][0].update(action={}),
        ]:
            broken = copy.deepcopy(output)
            mutation(broken)
            with self.assertRaises(AppError):
                contract.validate_report(data, broken)
        fenced = "```json\n" + json.dumps(output) + "\n```"
        self.assertEqual(contract.read_ai_report(data, fenced)[1], ["response.code_fence"])
        with self.assertRaises(AppError):
            contract.read_ai_report(data, '{"cases":[],"cases":[],"notes":[],"complete":true}')

    def test_compact_maintenance_preserves_omitted_fields_and_requires_real_targets(self):
        data, _ = sample("update")
        data["contract_version"] = 3
        target = data["cases"][0]
        source = next(
            m["snapshot_ref"] for m in data["materials"] if m["side"] in {"CURRENT", "SUPPLEMENT"}
        )
        output = {
            "cases": [
                {
                    "action": "UPDATE",
                    "target": target["case_ref"],
                    "design": {"title": "明确变化的新标题"},
                    "sources": [source],
                }
            ],
            "notes": [],
            "complete": True,
        }
        report = contract.validate_report(data, output)
        suggestion = report["suggestions"][0]
        self.assertEqual([p["field"] for p in suggestion["changes"]], ["title"])
        self.assertEqual(
            service.design_for(data, suggestion)["cleanup"], target["design"]["cleanup"]
        )
        self.assertEqual(suggestion["basis_status"], "NEEDS_REVIEW")
        output["cases"][0].update(action="RETIRE", design={})
        with self.assertRaises(AppError):
            contract.validate_report(data, output)
        output["cases"][0].update(action="REUSE")
        self.assertEqual(contract.validate_report(data, output)["suggestions"][0]["kind"], "REUSE")

    def test_compact_model_input_contains_full_materials_and_notes_without_segmentation(self):
        data, _ = sample("initial")
        data["contract_version"] = 3
        body = "正文" * 3000
        data["materials"][0]["segments"][0]["text"] = body
        content = compact.model_content(data, [])
        self.assertIn(body, "".join(x["text"] for x in content))
        self.assertNotIn('"coverage"', "".join(x["text"] for x in content))
        output = {
            "cases": [],
            "notes": [
                {
                    "kind": "BUSINESS_QUESTION",
                    "text": "金额精度待确认",
                    "sources": [data["materials"][0]["snapshot_ref"]],
                }
            ],
            "complete": True,
        }
        # Hash is re-bound only in this synthetic fixture.
        data["materials"][0]["content_sha256"] = (
            __import__("hashlib")
            .sha256("\n".join(s["text"] for s in data["materials"][0]["segments"]).encode())
            .hexdigest()
        )
        result = contract.validate_report(data, output)
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertEqual(len(result["requirement_questions"]), 1)

    def test_single_generation_keeps_complete_input_and_scope(self):
        data, _ = sample("initial")
        data["materials"][0]["segments"][0]["text"] *= 400
        data["materials"][0]["content_sha256"] = (
            __import__("hashlib")
            .sha256("\n".join(s["text"] for s in data["materials"][0]["segments"]).encode())
            .hexdigest()
        )
        original = copy.deepcopy(data)
        planned = sources.plan(data)
        self.assertEqual(len(planned), 1)
        self.assertEqual(data, original)
        for p in planned:
            self.assertEqual(p["materials"], data["materials"])
            self.assertEqual(p["cases"], data["cases"])
            self.assertEqual(p["scope"], data["scope"])
            self.assertEqual(p["batch"]["limitations"], data["batch"]["limitations"])
            contract.validate_input(p)

    def test_link_page_annotations_are_frozen_in_actual_model_payload(self):
        selection = MaterialSelection(document_id=9, version="a" * 64, paths=["order.html"])
        row = SimpleNamespace(
            id=9,
            kind="LINK",
            purpose="PROTOTYPE",
            name="订单原型",
            url="https://prototype.geekuat.com/p/Test123/",
        )
        captured = {
            "snapshot_ref": "b" * 64,
            "segments": [
                {"location": "订单 · HTML原文", "text": "<h1>订单</h1>"},
                {"location": "订单 · 批注：规则", "text": "订单金额按合计金额取整"},
                {
                    "location": "批注引用 Markdown · https://prototype.geekuat.com/p/Test123/rules.md",
                    "text": "# 完整业务规则\n取消必须按原扣款明细退款。",
                },
            ],
        }
        with (
            patch.object(sources.change_sources, "document", return_value=row),
            patch.object(sources.prototypes, "link_pages", return_value=captured),
        ):
            material, binding = sources.read_material(
                1, selection, "CURRENT", "M1-current", None, None
            )
        self.assertEqual(binding["paths"], ["order.html"])
        self.assertEqual(binding["annotation_blocks"], 1)
        self.assertEqual(binding["markdown_files"], 1)
        self.assertIn("1块对应批注", material["read_note"])
        data, _ = sample("initial")
        data["materials"] = [material]
        payload = json.loads(
            analysis_materials.model_content(data, [], attachment_key="image_ref")[0]["text"]
        )
        self.assertEqual(
            [s["text"] for s in payload["materials"][0]["segments"]],
            [
                "<h1>订单</h1>",
                "订单金额按合计金额取整",
                "# 完整业务规则\n取消必须按原扣款明细退款。",
            ],
        )
        self.assertIn("批注：规则", payload["materials"][0]["segments"][1]["location"])

    def test_ai_condition_normalization_is_lossless_and_does_not_relax_evidence(self):
        data, report = sample("initial")
        raw = copy.deepcopy(report)
        raw["rules"][0]["branches"][0]["conditions"] = "a; b\nc"
        raw["scenarios"][0]["conditions"] = "原文条件"
        before = copy.deepcopy(raw)
        normalized, fields = contract.normalize_ai_report(raw)
        self.assertEqual(raw, before)
        self.assertEqual(normalized["rules"][0]["branches"][0]["conditions"], ["a; b\nc"])
        self.assertEqual(len(fields), 2)
        contract.validate_report(data, normalized)
        normalized["evidence"][0]["quote"] = "invented"
        with self.assertRaises(AppError):
            contract.validate_report(data, normalized)
        self.assertEqual(contract.normalize_ai_report(report), (report, []))
        self.assertEqual(
            contract.normalize_ai_report({"rules": "malformed"}), ({"rules": "malformed"}, [])
        )

    def test_diagnostics_drop_upstream_prose_secrets_and_unknown_fields(self):
        result = safe_snapshot(
            {
                "message": "secret document",
                "upstream_code": "secret document",
                "request_id": "secret document",
                "phase": "receiving",
                "received_bytes": 120,
                "events": {"response.output_text.delta": 2, "secret document": 1},
            }
        )
        self.assertEqual(
            result,
            {
                "phase": "receiving",
                "received_bytes": 120,
                "events": {"response.output_text.delta": 2},
            },
        )

    def test_input_estimate_warns_without_rejecting_large_input(self):
        self.assertNotIn("输入较大", sources.input_notice({"text": "短资料"}))
        notice = sources.input_notice({"text": "中文" * 20000}, "指令", 1024)
        self.assertIn("输入较大", notice)
        self.assertIn("缩小范围", notice)
        self.assertIn("未计入", notice)
        self.assertIn("不是模型硬限制", notice)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class GenerationDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def setUp(self):
        test_requirements.RequirementDatabaseTests.setUp(self)
        self.api = f"/api/projects/{self.project}/case-generation"
        self.cases_api = f"/api/projects/{self.project}/cases"
        self.artifact_dir = tempfile.TemporaryDirectory()
        self.patch_env = patch.dict(
            os.environ, {"CASE_GENERATION_RESULT_PATH": self.artifact_dir.name}
        )
        self.patch_env.start()
        data, _ = sample("initial")
        content = (
            "\n".join(s["text"] for s in data["materials"][0]["segments"][:2])
            + "\n门店APP订单确认页展示应付总额，先使用单价原值乘数量，"
            "再对合计结果一次四舍五入至2位小数；"
            "示例单价19.955元、数量2，总额39.91元。"
        )
        revision = self.client.get(self.docs).json()["revision"]
        upload = self.client.post(
            self.docs + "/upload",
            params={
                "filename": "synthetic-generation.md",
                "revision": revision,
                "upload_id": str(uuid4()),
            },
            content=content.encode(),
            headers={**test_auth.ORIGIN, "Content-Type": "application/octet-stream"},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        document = upload.json()["documents"][0]
        # Upload returns the full source view with versions.
        self.document_id = document["id"]
        self.version_id = document["current"]["id"]
        with self.factory() as db:
            for aid in (self.member_id, self.admin_id):
                db.add(
                    AIConnection(
                        id=aid,
                        owner_id=aid,
                        name="合成个人配置",
                        base_url="https://api.openai.com/v1",
                        model="test-model",
                        encrypted_key="NOT-A-REAL-CREDENTIAL",
                        version=1,
                        updated_by=aid,
                    )
                )
            db.commit()
        self.config_patches = [
            patch.object(module, "analysis_configuration", side_effect=self.configuration)
            for module in (service, execution, chat)
        ]
        for p in self.config_patches:
            p.start()

    def tearDown(self):
        for p in self.config_patches:
            p.stop()
        self.patch_env.stop()
        self.artifact_dir.cleanup()
        test_requirements.RequirementDatabaseTests.tearDown(self)

    def configuration(self, actor, db, version=None, **kwargs):
        if isinstance(version, dict):
            version = version.get("version")
        current = db.get(UserAccount, actor.id, populate_existing=True)
        if not current or current.status != "ACTIVE":
            raise AppError(403, "generation_access_lost")
        config = db.get(AIConnection, actor.id)
        if config is None:
            raise AppError(422, "ai_personal_required")
        if version is not None and version != config.version:
            raise AppError(409, "ai_configuration_changed")
        return {
            "name": config.name,
            "base_url": config.base_url,
            "reasoning_effort": config.reasoning_effort,
            "model": config.model,
            "version": config.version,
        }, f"synthetic-secret-{actor.id}"

    def post(self, path, payload=None):
        return self.client.post(self.api + path, json=payload, headers=test_auth.ORIGIN)

    def test_partial_candidate_review_free_correction_preserves_applied_case_and_original(self):
        output = {
            "cases": [
                {
                    "action": "NEW",
                    "sources": ["M1-current"],
                    "design": {
                        "title": f"合成独立候选{n}",
                        "steps": "提交",
                        "expected": "显示结果",
                        "priority": "P1",
                    },
                }
                for n in range(3)
            ],
            "notes": [],
            "complete": True,
        }
        raw = json.dumps(output, ensure_ascii=False)
        marker = '"priority": "P1"'
        first = raw.index(marker)
        second = raw.index(marker, first + len(marker))
        raw = raw[:second] + raw[second:].replace(marker, '"priority": "P2", "priority": "P1"', 1)
        done, remote = self.finish(self.prepare(legacy=False), lambda *args, **kwargs: raw)
        remote.assert_called_once()
        self.assertEqual(len(done["suggestions"]), 2)
        self.assertEqual(done["candidateIssues"][0]["status"], "PENDING")
        pending = done["candidateIssues"][0]
        applied = self.apply_all(done, [done["suggestions"][0]["key"]])
        endpoint = (
            f"/{done['id']}/batches/{pending['batchId']}"
            f"/candidate-issues/{pending['issueId']}/resolve"
        )
        payload = {
            "request_id": str(uuid4()),
            "revision": applied["serverRevision"],
            "corrected_json": json.dumps(output["cases"][1]),
            "ignored": False,
            "reason": "人工确认P1",
            "confirmed": True,
        }
        with patch.object(execution.responses, "analyze", side_effect=AssertionError("no AI")):
            response = self.post(endpoint, payload)
            self.assertEqual(response.status_code, 200, response.text)
            fixed = response.json()
            self.assertEqual(len(fixed["suggestions"]), 3)
            self.assertEqual(fixed["candidateIssues"][0]["status"], "RESOLVED")
            self.assertEqual(self.post(endpoint, payload).status_code, 200)
        for old in done["suggestions"]:
            self.assertEqual(next(x for x in fixed["suggestions"] if x["key"] == old["key"]), old)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 1)
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, pending["batchId"])
            self.assertEqual(execution.candidate_path(batch).read_text(encoding="utf-8"), raw)
        payload["reason"] = "变更同一请求的说明"
        self.assertEqual(self.post(endpoint, payload).status_code, 409)
        self.login()
        self.assertEqual(
            self.post(endpoint, {**payload, "request_id": str(uuid4())}).status_code, 403
        )

    def test_prepare_preserves_large_text_and_attachment_size_without_starting_ai(self):
        segment_text = "rule\n" * 400_000
        content = "\n".join([segment_text] * 9)
        original = sources.read_material

        def read_large(*args, **kwargs):
            material, binding = original(*args, **kwargs)
            material["segments"] = [
                {
                    "segment_id": f"large-{n}",
                    "location": "全文",
                    "text": segment_text,
                    "image_ref": "",
                }
                for n in range(9)
            ]
            material["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
            return material, binding

        attachment = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=contract.LIMIT + 1))
        with (
            patch.object(sources, "read_material", side_effect=read_large),
            patch.object(
                sources, "binaries", return_value=[(attachment, "pdf", "M1", "large.pdf")]
            ),
            patch("app.integrations.responses.analyze") as upstream,
        ):
            result = self.prepare(legacy=False)
        upstream.assert_not_called()
        self.assertEqual(result["status"], "PREPARED")
        with self.factory() as db:
            row = db.get(CaseGenerationRun, int(result["id"]))
            self.assertEqual(
                "\n".join(s["text"] for s in row.input_snapshot["materials"][0]["segments"]),
                content,
            )
            self.assertEqual(row.metadata_snapshot["attachment_bytes"], contract.LIMIT + 1)
            batch = db.scalar(
                select(CaseGenerationBatch).where(CaseGenerationBatch.run_id == row.id)
            )
            self.assertEqual(
                "\n".join(s["text"] for s in batch.input_snapshot["materials"][0]["segments"]),
                content,
            )
        with self.assertRaises(AppError):
            contract.read(" " * (contract.LIMIT + 1) + "{}")

    def test_prepare_reuses_request_completed_during_source_reads(self):
        original = sources.prepare
        winners = []

        def finished_during_read(project_id, payload, actor, db):
            fixed = original(project_id, payload, actor, db)
            with patch.object(sources, "prepare", return_value=fixed):
                winners.append(service.prepare(project_id, payload, actor, db)["id"])
            return fixed

        with patch.object(sources, "prepare", side_effect=finished_during_read):
            result = self.prepare(legacy=False)
        self.assertEqual(winners, [result["id"]])
        with self.factory() as db:
            count = db.scalar(
                text("SELECT count(*) FROM case_generation_run WHERE project_id=:id"),
                {"id": self.project},
            )
        self.assertEqual(count, 1)

    def prepare(self, legacy=True):
        payload = {
            "request_id": str(uuid4()),
            "title": "合成用例生成",
            "mode": "INITIAL",
            "scope": "完整所选资料",
            "materials": [{"document_id": self.document_id, "version": str(self.version_id)}],
            "case_ids": [],
            "case_versions": {},
            "case_scope": "实际空库",
        }
        # Legacy report fixtures verify old frozen records; new contract has separate regressions.
        fixed_skill = {**sources.skill(), "contract_version": 2, "version": "1.1.0"}
        with patch.object(sources, "skill", return_value=fixed_skill) if legacy else nullcontext():
            response = self.post("/prepare", payload)
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(self.post("/prepare", payload).json()["id"], response.json()["id"])
        return response.json()

    def answer(self, *args, **kwargs):
        data = json.loads(args[5][0]["text"])
        _, raw = sample("clarification")
        # One synthetic executable suggestion backed by the real fixed uploaded text.
        namespace = data["batch"]["namespace"]

        def walk(value):
            if isinstance(value, dict):
                return {k: walk(v) for k, v in value.items()}
            if isinstance(value, list):
                return [walk(v) for v in value]
            return (
                value.replace("clarification:", namespace + ":")
                if isinstance(value, str)
                else value
            )

        report = walk(raw)
        for k in ("request_id", "project_id", "revision", "mode"):
            report[k] = data[k]
        report["batch_ref"] = data["batch"]["batch_ref"]
        report["limitations"] = data["input_limitations"]
        m, seg = data["materials"][0], data["materials"][0]["segments"][0]
        report["evidence"] = [
            {
                "key": namespace + ":E1",
                "kind": "MATERIAL",
                "target_ref": m["snapshot_ref"],
                "segment_id": seg["segment_id"],
                "side": m["side"],
                "field": "",
                "quote": seg["text"],
                "note": "合成上游",
            }
        ]
        report["rules"][0].update(function_ref="F-SCOPE", evidence_refs=[namespace + ":E1"])
        report["rules"][0]["branches"][0]["evidence_refs"] = [namespace + ":E1"]
        report["scenarios"][0].update(function_ref="F-SCOPE", evidence_refs=[namespace + ":E1"])
        report["suggestions"][0].update(function_ref="F-SCOPE", evidence_refs=[namespace + ":E1"])
        report["coverage"]["input_units"] = [
            {
                "snapshot_ref": m["snapshot_ref"],
                "segment_id": seg["segment_id"],
                "state": "PROCESSED",
                "rule_refs": [namespace + ":R1"],
                "scenario_refs": [namespace + ":S1"],
                "issue_refs": [],
                "note": "合成测试覆盖",
            }
        ]
        report["coverage"]["functions"][0]["function_ref"] = "F-SCOPE"
        return json.dumps(report, ensure_ascii=False)

    def finish(self, row, answer=None):
        started = self.post(
            f"/{row['id']}/start", {"revision": row["serverRevision"], "confirmed": True}
        )
        self.assertEqual(started.status_code, 202, started.text)
        with self.factory() as db:
            bid = execution.claim(db)
        with patch.object(
            execution.responses, "analyze", side_effect=answer or self.answer
        ) as remote:
            execution.execute(bid, self.factory)
        result = self.client.get(self.api + f"/{row['id']}").json()
        self.assertEqual(result["status"], "COMPLETED", result)
        return result, remote

    def apply_all(self, row, keys=None, category_settings=None):
        keys = keys or [s["key"] for s in row["suggestions"]]
        response = self.post(
            f"/{row['id']}/applications",
            {
                "request_id": str(uuid4()),
                "confirmed": True,
                "items": [
                    {
                        "key": k,
                        "draft_revision": row["handling"].get(k, [{}])[-1].get("revision", 0),
                        **(category_settings or {}).get(k, {}),
                    }
                    for k in keys
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["applications"][-1]["status"], "COMPLETED")
        return response.json()

    def test_prepare_confirmation_personal_worker_import_and_comments(self):
        row = self.prepare()
        self.assertEqual(row["status"], "PREPARED")
        with self.factory() as db:
            self.assertIsNone(execution.claim(db))
        done, remote = self.finish(row)
        self.assertEqual(remote.call_args.args[2], f"synthetic-secret-{self.member_id}")
        runtime = remote.call_args.kwargs["instruction_messages"]
        self.assertEqual([message["role"] for message in runtime], ["developer"])
        self.assertEqual(len(runtime[0]["content"]), 10)
        self.assertTrue(done["rawReports"])
        self.assertEqual(self.client.get(self.api).json()["items"][0]["id"], row["id"])
        imported = self.post(
            "/import",
            {
                "title": "导入",
                "input_json": done["inputText"],
                "report_json": done["reportText"],
                "bindings": [
                    {
                        "snapshot_ref": "M1-current",
                        "document_id": self.document_id,
                        "version_id": self.version_id,
                    }
                ],
            },
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        tampered = json.loads(done["inputText"])
        tampered["materials"][0]["segments"][0]["text"] = "wrong original"
        rejected = self.post(
            "/import",
            {
                "title": "伪造",
                "input_json": json.dumps(tampered),
                "report_json": done["reportText"],
                "bindings": [
                    {
                        "snapshot_ref": "M1-current",
                        "document_id": self.document_id,
                        "version_id": self.version_id,
                    }
                ],
            },
        )
        self.assertEqual(rejected.status_code, 422)
        with self.factory() as db:
            for table in (
                "case_generation_run",
                "case_generation_batch",
                "case_generation_application",
                "case_generation_chat_turn",
                "case_lifecycle_record",
            ):
                self.assertTrue(
                    db.scalar(text("SELECT obj_description(to_regclass(:t))"), {"t": table})
                )
                self.assertFalse(
                    db.scalar(
                        text(
                            "SELECT count(*) FROM pg_attribute WHERE attrelid=to_regclass(:t) "
                            "AND attnum>0 AND NOT attisdropped "
                            "AND col_description(attrelid,attnum) IS NULL"
                        ),
                        {"t": table},
                    )
                )

    def test_summary_listing_is_bounded_and_keeps_detail_and_progress_separate(self):
        row = self.prepare()
        with self.factory() as db:
            source = db.get(CaseGenerationRun, int(row["id"]))
            for index in range(21):
                db.add(
                    CaseGenerationRun(
                        project_id=self.project,
                        actor_id=self.member_id,
                        request_id=str(uuid4()),
                        title=f"历史摘要{index}",
                        mode="INITIAL",
                        input_snapshot=source.input_snapshot,
                        metadata_snapshot=source.metadata_snapshot,
                        handling={},
                    )
                )
            batch = db.get(CaseGenerationBatch, row["batches"][0]["id"])
            batch.attempts = [
                {
                    "request_id": batch.request_id,
                    "input_snapshot": {"private_body": "sensitive" * 10000},
                }
            ]
            db.commit()
        statements = []

        def count(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        event.listen(self.connection, "before_cursor_execute", count)
        try:
            with patch.object(service, "projection", side_effect=AssertionError("full projection")):
                first = self.client.get(self.api + "?summary=true").json()
                self.assertEqual(len(first["items"]), 20)
                self.assertTrue(first["has_more"])
                self.assertLessEqual(len(statements), 10)
                second = self.client.get(self.api + "?page=2&summary=true").json()
                self.assertEqual(len(second["items"]), 2)
                self.assertFalse(second["has_more"])
        finally:
            event.remove(self.connection, "before_cursor_execute", count)
        item = next(r for r in second["items"] if r["id"] == row["id"])
        self.assertTrue(item["hasMaterials"])
        self.assertNotIn("materials", item)
        self.assertNotIn("inputText", item)
        self.assertNotIn("private_body", json.dumps(first) + json.dumps(second))
        self.assertEqual(item["timings"], [{"startedAt": None, "finishedAt": None}])
        self.assertEqual(
            self.client.get(self.api + f"/{row['id']}").json()["inputText"], row["inputText"]
        )
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, row["batches"][0]["id"])
            batch.status = "RUNNING"
            batch.attempts = [
                {
                    "request_id": batch.request_id,
                    "started_at": "2026-10-13T11:00:00+08:00",
                    "progress_at": "2026-10-13T12:00:00+08:00",
                }
            ]
            db.commit()
        updated = self.client.get(self.api + "?page=2&summary=true").json()["items"]
        active = next(r for r in updated if r["id"] == row["id"])
        self.assertTrue(active["active"])
        self.assertEqual(
            active["timings"], [{"startedAt": "2026-10-13T11:00:00+08:00", "finishedAt": None}]
        )
        self.assertNotEqual(active["refreshKey"], item["refreshKey"])
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, row["batches"][0]["id"])
            batch.attempts = [
                {"request_id": batch.request_id, "progress_at": "2026-10-13T12:00:05+08:00"}
            ]
            db.commit()
        progress = self.client.get(self.api + "?page=2&summary=true").json()["items"]
        self.assertNotEqual(
            next(r for r in progress if r["id"] == row["id"])["refreshKey"], active["refreshKey"]
        )
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, row["batches"][0]["id"])
            batch.status = "FAILED"
            batch.attempts = [
                {
                    "request_id": batch.request_id,
                    "started_at": "2026-10-13T11:00:00+08:00",
                    "progress_at": "2026-10-13T12:02:03+08:00",
                }
            ]
            db.commit()
        ended = self.client.get(self.api + "?page=2&summary=true").json()["items"]
        timing = next(r for r in ended if r["id"] == row["id"])["timings"]
        self.assertEqual(timing[0]["finishedAt"], "2026-10-13T12:02:03+08:00")
        self.assertEqual(self.client.get(self.api + f"/{row['id']}").json()["timings"], timing)
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, row["batches"][0]["id"])
            batch.request_id, batch.status = str(uuid4()), "QUEUED"
            db.commit()
        retried = self.client.get(self.api + "?page=2&summary=true").json()["items"]
        self.assertEqual(
            next(r for r in retried if r["id"] == row["id"])["timings"],
            [{"startedAt": None, "finishedAt": None}],
        )

    def test_application_is_atomic_reviewed_and_reuse_preserves_history(self):
        done, _ = self.finish(self.prepare())
        raw = done["reportText"]
        applied = self.apply_all(done)
        self.assertEqual(applied["reportText"], raw)
        self.assertEqual(applied["handling"][done["suggestions"][0]["key"]][-1]["status"], "已应用")
        current = self.client.post(
            self.cases_api + "/search", json={}, headers=test_auth.ORIGIN
        ).json()
        self.assertEqual(current["total"], 1)
        c = current["items"][0]
        self.assertEqual(
            (c["review_status"], c["result"], c["tester"], c["source_kind"]),
            ("已审核", "未测", "", "GENERATION"),
        )
        before = self.client.get(self.cases_api + f"/{c['id']}").json()["versions"]
        # A new matching NEW candidate is explicitly reused against actual current ID/version.
        other, _ = self.finish(self.prepare())
        key = other["suggestions"][0]["key"]
        payload = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "items": [
                {
                    "key": key,
                    "draft_revision": 0,
                    "action": "reuse",
                    "target_id": c["id"],
                    "target_version": c["version"],
                }
            ],
        }
        queued = self.post(f"/{other['id']}/applications", payload)
        self.assertEqual(queued.status_code, 200, queued.text)
        after = self.client.get(self.cases_api + f"/{c['id']}").json()["versions"]
        self.assertEqual(len(after), len(before))
        self.assertEqual(
            [x for x in after[0]["records"] if x["kind"] == "TEST"],
            [x for x in before[0]["records"] if x["kind"] == "TEST"],
        )
        self.assertEqual(len(after[0]["records"]), len(before[0]["records"]) + 1)
        self.assertEqual(self.post(f"/{other['id']}/applications", payload).status_code, 200)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 1)

    def test_direct_submission_keeps_committed_items_and_does_not_block_next_case(self):
        done, _ = self.finish(
            self.prepare(legacy=False),
            lambda *args, **kwargs: json.dumps(
                {
                    "cases": [
                        {
                            "action": "NEW",
                            "sources": ["M1-current"],
                            "design": {
                                "title": f"直接入库{n}",
                                "steps": "提交",
                                "expected": "成功",
                            },
                        }
                        for n in range(3)
                    ],
                    "notes": [],
                    "complete": True,
                }
            ),
        )
        keys = [s["key"] for s in done["suggestions"]]
        payload = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "items": [{"key": k, "draft_revision": 0} for k in keys[:2]],
        }
        actual = apply.apply_item

        def interrupt_second(app, item, actor, db):
            if item["key"] == keys[1]:
                raise RuntimeError("synthetic request interruption")
            return actual(app, item, actor, db)

        with patch.object(apply, "apply_item", side_effect=interrupt_second):
            response = self.post(f"/{done['id']}/applications", payload)
        self.assertEqual(response.status_code, 200, response.text)
        audit = response.json()["applications"][-1]
        self.assertEqual(audit["status"], "FAILED")
        self.assertEqual([i["status"] for i in audit["items"]], ["COMPLETED", "PENDING"])
        self.assertEqual(response.json()["handling"][keys[0]][-1]["status"], "已应用")
        self.assertEqual(self.post(f"/{done['id']}/applications", payload).status_code, 200)
        next_case = self.apply_all(response.json(), [keys[2]])
        self.assertEqual(next_case["handling"][keys[2]][-1]["status"], "已应用")
        with self.factory() as db:
            self.assertIsNone(execution.claim_application(db))
            audit = db.get(CaseGenerationApplication, audit["id"])
            self.assertEqual(audit.items[1]["status"], "PENDING")
        current = self.client.post(self.cases_api + "/search", json={}).json()
        self.assertEqual(current["total"], 2)

    def test_direct_submission_ignores_unrelated_legacy_queue_and_returns_success(self):
        done, _ = self.finish(self.prepare())
        with self.factory() as db:
            db.add(
                CaseGenerationApplication(
                    run_id=int(done["id"]),
                    project_id=self.project,
                    actor_id=self.member_id,
                    request_id=str(uuid4()),
                    fingerprint="f" * 64,
                    items=[],
                    status="QUEUED",
                )
            )
            db.commit()
        result = self.apply_all(done)
        self.assertEqual(result["applications"][-1]["status"], "COMPLETED")
        self.assertEqual(result["applications"][0]["status"], "QUEUED")
        self.assertEqual(result["handling"][done["suggestions"][0]["key"]][-1]["status"], "已应用")

    def test_interrupted_direct_request_resumes_pending_only_with_same_request_id(self):
        done, _ = self.finish(
            self.prepare(legacy=False),
            lambda *args, **kwargs: json.dumps(
                {
                    "cases": [
                        {
                            "action": "NEW",
                            "sources": ["M1-current"],
                            "design": {
                                "title": f"提交中断{n}",
                                "steps": "提交",
                                "expected": "成功",
                            },
                        }
                        for n in range(2)
                    ],
                    "notes": [],
                    "complete": True,
                }
            ),
        )
        payload = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "items": [{"key": s["key"], "draft_revision": 0} for s in done["suggestions"]],
        }
        actual = apply.execute_item

        def stop_after_commit(*args, **kwargs):
            actual(*args, **kwargs)
            return False

        with patch.object(apply, "execute_item", side_effect=stop_after_commit):
            partial = self.post(f"/{done['id']}/applications", payload)
        self.assertEqual(partial.status_code, 200, partial.text)
        audit = partial.json()["applications"][-1]
        self.assertEqual(audit["requestId"], payload["request_id"])
        self.assertEqual([i["status"] for i in audit["items"]], ["COMPLETED", "PENDING"])
        resumed = self.post(f"/{done['id']}/applications", payload)
        self.assertEqual(resumed.status_code, 200, resumed.text)
        self.assertEqual(resumed.json()["applications"][-1]["status"], "COMPLETED")
        self.assertEqual(len(resumed.json()["applications"]), 1)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 2)
        first = done["suggestions"][0]["key"]
        self.assertEqual(len(resumed.json()["handling"][first]), 1)

    def test_legacy_queued_application_still_drains_without_new_work_entering_queue(self):
        done, _ = self.finish(self.prepare())
        with patch.object(
            apply,
            "complete_submission",
            side_effect=lambda a, actor, db: service.projection(
                service.own(a.project_id, a.run_id, actor, db), actor, db
            ),
        ):
            response = self.post(
                f"/{done['id']}/applications",
                {
                    "request_id": str(uuid4()),
                    "confirmed": True,
                    "items": [{"key": done["suggestions"][0]["key"], "draft_revision": 0}],
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        audit_id = response.json()["applications"][-1]["id"]
        with self.factory() as db:
            self.assertIsNone(execution.claim_application(db))
            audit = db.get(CaseGenerationApplication, audit_id)
            self.assertEqual(audit.status, "FAILED")
            audit.status, audit.error_code = "QUEUED", ""
            db.commit()
        with self.factory() as db:
            claimed = execution.claim_application(db)
        self.assertEqual(claimed, audit_id)
        apply.execute(claimed, self.factory)
        result = self.client.get(self.api + f"/{done['id']}").json()
        self.assertEqual(result["applications"][-1]["status"], "COMPLETED")
        self.assertEqual(result["handling"][done["suggestions"][0]["key"]][-1]["status"], "已应用")

    def test_batch_category_settings_are_frozen_and_reuse_cannot_move_existing_case(self):
        def answer(*args, **kwargs):
            return json.dumps(
                {
                    "cases": [
                        {
                            "action": "NEW",
                            "sources": ["M1-current"],
                            "design": {
                                "title": f"分类合成用例{n}",
                                "steps": "提交订单",
                                "expected": "订单已创建",
                            },
                        }
                        for n in range(3)
                    ],
                    "notes": [],
                    "complete": True,
                },
                ensure_ascii=False,
            )

        done, _ = self.finish(self.prepare(legacy=False), answer)
        raw = done["reportText"]
        with self.factory() as db:
            category = CaseCategory(
                project_id=self.project, name="合成目标分类", updated_by=self.member_id
            )
            db.add(category)
            db.flush()
            category_id = category.id
            db.commit()
        payload = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "items": [
                {
                    "key": s["key"],
                    "draft_revision": 0,
                    "category_mode": mode,
                    "category_id": category_id if mode == "SET" else None,
                }
                for s, mode in zip(done["suggestions"], ["SET", "CLEAR", "KEEP"], strict=True)
            ],
        }
        queued = self.post(f"/{done['id']}/applications", payload)
        self.assertEqual(queued.status_code, 200, queued.text)
        with self.factory() as db:
            app = db.get(CaseGenerationApplication, queued.json()["applications"][-1]["id"])
            self.assertEqual([i["category_id"] for i in app.items], [category_id, 0, None])
        result = self.client.get(self.api + f"/{done['id']}").json()
        self.assertFalse(result["failures"])
        self.assertEqual(result["reportText"], raw)
        cases = self.client.post(self.cases_api + "/search", json={}).json()["items"]
        self.assertEqual(
            [c["category_id"] for c in sorted(cases, key=lambda c: c["title"])],
            [category_id, None, None],
        )
        self.assertEqual(self.post(f"/{done['id']}/applications", payload).status_code, 200)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 3)
        other, _ = self.finish(self.prepare(legacy=False), answer)
        target = next(c for c in cases if c["category_id"] == category_id)
        reuse = {
            "request_id": str(uuid4()),
            "confirmed": True,
            "items": [
                {
                    "key": other["suggestions"][0]["key"],
                    "draft_revision": 0,
                    "action": "reuse",
                    "target_id": target["id"],
                    "target_version": target["version"],
                    "category_mode": "CLEAR",
                }
            ],
        }
        invalid = self.post(f"/{other['id']}/applications", reuse)
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(invalid.json()["detail"], "generation_category_not_applicable")
        reuse["items"][0]["category_mode"] = "KEEP"
        before = self.client.get(self.cases_api + f"/{target['id']}").json()["versions"]
        self.assertEqual(self.post(f"/{other['id']}/applications", reuse).status_code, 200)
        after = self.client.get(self.cases_api + f"/{target['id']}").json()["versions"]
        self.assertEqual(len(before), len(after))
        current = self.client.post(self.cases_api + "/search", json={}).json()["items"]
        self.assertEqual(
            next(c for c in current if c["id"] == target["id"])["category_id"], category_id
        )

    def test_batch_category_wrong_project_rejected_and_deleted_category_fails_one_item_only(self):
        done, _ = self.finish(
            self.prepare(legacy=False),
            lambda *args, **kwargs: json.dumps(
                {
                    "cases": [
                        {
                            "action": "NEW",
                            "sources": ["M1-current"],
                            "design": {
                                "title": f"分类删除合成{n}",
                                "steps": "提交订单",
                                "expected": "订单已创建",
                            },
                        }
                        for n in range(2)
                    ],
                    "notes": [],
                    "complete": True,
                },
                ensure_ascii=False,
            ),
        )
        with self.factory() as db:
            project = Project(
                name="其他合成项目",
                identifier=str(uuid4()),
                owner_id=self.member_id,
                created_by=self.member_id,
            )
            db.add(project)
            db.flush()
            wrong = CaseCategory(
                project_id=project.id, name="其他项目分类", updated_by=self.member_id
            )
            category = CaseCategory(
                project_id=self.project, name="待删除分类", updated_by=self.member_id
            )
            db.add_all([wrong, category])
            db.flush()
            wrong_id, category_id = wrong.id, category.id
            db.commit()
        items = [{"key": s["key"], "draft_revision": 0} for s in done["suggestions"]]
        items[0].update(category_mode="SET", category_id=wrong_id)
        invalid = self.post(
            f"/{done['id']}/applications",
            {"request_id": str(uuid4()), "confirmed": True, "items": items},
        )
        self.assertEqual(invalid.status_code, 404)
        items[0]["category_id"] = category_id
        actual = apply.apply_item

        def category_removed(app, item, actor, db):
            if item["key"] == items[0]["key"]:
                db.delete(db.get(CaseCategory, category_id))
                db.flush()
            return actual(app, item, actor, db)

        with patch.object(apply, "apply_item", side_effect=category_removed):
            response = self.post(
                f"/{done['id']}/applications",
                {"request_id": str(uuid4()), "confirmed": True, "items": items},
            )
        self.assertEqual(response.status_code, 200, response.text)
        result = self.client.get(self.api + f"/{done['id']}").json()
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(result["failures"][0]["categoryId"], category_id)
        self.assertEqual(result["failures"][0]["categoryMode"], "SET")
        self.assertEqual(result["handling"][items[1]["key"]][-1]["status"], "已应用")
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 1)

    def test_update_category_keep_set_and_clear_preserve_case_identity_and_test_history(self):
        with self.factory() as db:
            categories = [
                CaseCategory(
                    project_id=self.project, name=f"修改分类{n}", updated_by=self.member_id
                )
                for n in range(2)
            ]
            db.add_all(categories)
            db.flush()
            first, second = [c.id for c in categories]
            db.commit()
        done, _ = self.finish(self.prepare())
        key = done["suggestions"][0]["key"]
        self.apply_all(
            done, category_settings={key: {"category_mode": "SET", "category_id": first}}
        )
        current = self.client.post(self.cases_api + "/search", json={}).json()["items"][0]
        for mode, category_id in [("KEEP", first), ("SET", second), ("CLEAR", None)]:
            response = self.post(
                "/prepare",
                {
                    "request_id": str(uuid4()),
                    "title": f"修改分类{mode}",
                    "mode": "UPDATE",
                    "scope": "固定资料",
                    "materials": [
                        {"document_id": self.document_id, "version": str(self.version_id)}
                    ],
                    "case_ids": [current["id"]],
                    "case_versions": {str(current["id"]): current["version"]},
                    "case_scope": "当前用例",
                },
            )
            self.assertEqual(response.status_code, 201, response.text)
            updated, _ = self.finish(
                response.json(),
                lambda *args, **kwargs: json.dumps(
                    {
                        "cases": [
                            {
                                "action": "UPDATE",
                                "target": f"case-{current['id']}",
                                "sources": ["M1-current"],
                                "design": {"title": current["title"] + "建议修订"},
                            }
                        ],
                        "notes": [],
                        "complete": True,
                    },
                    ensure_ascii=False,
                ),
            )
            suggestion = updated["suggestions"][0]
            # Keeping the design while changing its category must not add a test version.
            saved = self.post(
                f"/{updated['id']}/handling",
                {
                    "revision": updated["serverRevision"],
                    "key": suggestion["key"],
                    "draft": {f: current[f] for f in DESIGN_FIELDS},
                    "note": "保留现有设计，只审核分类",
                    "evidence_checked": True,
                    "resolved": True,
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            before = self.client.get(self.cases_api + f"/{current['id']}").json()["versions"]
            settings = {"category_mode": mode, **({"category_id": second} if mode == "SET" else {})}
            result = self.apply_all(saved.json(), category_settings={suggestion["key"]: settings})
            self.assertFalse(result["failures"])
            after = self.client.get(self.cases_api + f"/{current['id']}").json()["versions"]
            self.assertEqual(len(after), len(before))
            self.assertEqual(
                [r for r in after[0]["records"] if r["kind"] == "TEST"],
                [r for r in before[0]["records"] if r["kind"] == "TEST"],
            )
            actual = self.client.post(self.cases_api + "/search", json={}).json()["items"][0]
            self.assertEqual(actual["id"], current["id"])
            self.assertEqual(actual["category_id"], category_id)
            current = actual

    def test_partial_application_skips_bad_item_keeps_later_success_and_manual_retry(self):
        done, _ = self.finish(self.prepare())
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, done["batches"][0]["id"])
            report = copy.deepcopy(batch.report)
            base = report["suggestions"][0]
            for n in range(1, 8):
                s = copy.deepcopy(base)
                s["key"] = f"b1:A{n + 1}"
                s["design"]["title"] += f" 合成独立场景{n}"
                report["suggestions"].append(s)
                # Test fixture injects valid distinct scene identity to avoid semantic duplicates.
                sc = copy.deepcopy(report["scenarios"][0])
                sc["key"] = f"b1:S{n + 1}"
                sc["semantic_key"] += str(n)
                report["scenarios"].append(sc)
                s["scenario_refs"] = [sc["key"]]
            batch.report = report
            db.commit()
        done = self.client.get(self.api + f"/{done['id']}").json()
        actual = apply.apply_item

        def fail_one(app, item, actor, db):
            if item["key"] == "b1:A4":
                # Simulate a failure after a write to prove the whole item's transaction rolls back.
                actual(app, item, actor, db)
                raise AppError(422, "generation_item_write_invalid")
            return actual(app, item, actor, db)

        with patch.object(apply, "apply_item", side_effect=fail_one):
            result = self.apply_all(done)
        self.assertEqual(len(result["failures"]), 1)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 7)
        self.assertEqual(result["handling"]["b1:A8"][-1]["status"], "已应用")
        failed = result["suggestions"][3]
        saved = self.post(
            f"/{result['id']}/handling",
            {
                "revision": result["serverRevision"],
                "key": failed["key"],
                "draft": failed["design"],
                "note": "人工修复并核对",
                "evidence_checked": True,
                "resolved": True,
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        retried = self.apply_all(saved.json(), [failed["key"]])
        self.assertFalse(retried["failures"])
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 8)

    def test_pending_setup_suggestion_is_saved_reviewed_and_applied_as_untested(self):
        def answer(*args, **kwargs):
            data = json.loads(args[5][0]["text"])
            report = json.loads(self.answer(*args, **kwargs))
            scenario = report["scenarios"][0]
            scenario["state"] = "DESIGN_READY_SETUP_PENDING"
            scenario["entry"] = ""
            scenario["note"] = "测试账号和观察入口待准备，业务金额规则已明确。"
            suggestion = report["suggestions"][0]
            suggestion["basis_status"] = "NEEDS_REVIEW"
            suggestion["design"]["data_requirements"] = "执行前准备符合业务角色的账号和观察权限。"
            suggestion["design"]["remark"] = "执行准备待补，执行前核对观察入口。"
            gap = {
                "key": data["batch"]["namespace"] + ":SETUP",
                "kind": "EXECUTION_SETUP",
                "function_ref": scenario["function_ref"],
                "scenario_refs": [scenario["key"]],
                "case_refs": [],
                "material_refs": [data["materials"][0]["snapshot_ref"]],
                "reason": "缺测试账号和观察入口",
                "next_step": "执行前准备账号、核对观察权限",
            }
            report["discovery_gaps"].append(gap)
            report["coverage"]["functions"][0]["issue_refs"].append(gap["key"])
            report["coverage"]["functions"][0]["state"] = "PARTIAL"
            report["outcome"] = "PARTIAL"
            return json.dumps(report, ensure_ascii=False)

        result, remote = self.finish(self.prepare(), answer)
        self.assertEqual(remote.call_count, 1)
        self.assertEqual(result["outcome"], "PARTIAL")
        suggestion = result["suggestions"][0]
        self.assertTrue(suggestion["blocked"])
        saved = self.post(
            f"/{result['id']}/handling",
            {
                "revision": result["serverRevision"],
                "key": suggestion["key"],
                "draft": suggestion["design"],
                "note": "人工确认业务预期明确；执行前补账号与观察权限",
                "evidence_checked": True,
                "resolved": True,
            },
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        applied = self.apply_all(saved.json(), [suggestion["key"]])
        self.assertFalse(applied["failures"])
        rows = self.client.post(self.cases_api + "/search", json={}).json()["items"]
        self.assertEqual(rows[0]["result"], "未测")
        self.assertIn("执行准备待补", rows[0]["remark"])
        self.assertTrue(rows[0]["data_requirements"])

    def test_quote_mismatch_revalidation_retains_all_candidates_without_calling_ai_or_applying(
        self,
    ):
        row = self.prepare(legacy=False)
        self.post(f"/{row['id']}/start", {"revision": row["serverRevision"], "confirmed": True})
        with self.factory() as db:
            bid = execution.claim(db)
        raw_output = {
            "cases": [
                {
                    "action": "NEW",
                    "target": None,
                    "sources": ["M1-current"],
                    "design": {
                        "title": "保留原始建议",
                        "steps": "执行提交。",
                        "expected": "显示提交结果。",
                    },
                    "evidence_quotes": [{"source": "M1-current", "quote": "AI少抄一个字的摘录"}],
                }
            ],
            "notes": [],
            "complete": True,
        }
        raw = json.dumps(raw_output, ensure_ascii=False)
        with (
            patch.object(execution.responses, "analyze", return_value=raw),
            patch.object(
                contract,
                "validate_report",
                side_effect=AppError(422, "generation_evidence_quote_mismatch"),
            ),
        ):
            execution.execute(bid, self.factory)
        with patch.object(
            execution.responses,
            "analyze",
            side_effect=AssertionError("free validation must not call AI"),
        ) as paid:
            response = self.post(f"/{row['id']}/batches/{bid}/revalidate")
        self.assertEqual(response.status_code, 200, response.text)
        paid.assert_not_called()
        saved = response.json()
        self.assertEqual(saved["status"], "COMPLETED")
        self.assertEqual(len(saved["suggestions"]), 1)
        self.assertEqual(saved["suggestions"][0]["evidence"][0]["quote"], "AI少抄一个字的摘录")
        self.assertFalse(saved["suggestions"][0]["evidence"][0]["verifiedQuote"])
        self.assertIn("未逐字匹配", saved["suggestions"][0]["evidence"][0]["quoteWarning"])
        self.assertEqual(saved["rawReports"][0]["model_output"], raw_output)
        contract.validate_report(json.loads(saved["inputText"]), json.loads(saved["reportText"]))
        imported = self.post(
            "/import",
            {
                "title": "带未核对摘录的配对导入",
                "input_json": saved["inputText"],
                "report_json": saved["reportText"],
                "bindings": [
                    {
                        "snapshot_ref": "M1-current",
                        "document_id": self.document_id,
                        "version_id": self.version_id,
                    }
                ],
            },
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertFalse(imported.json()["suggestions"][0]["evidence"][0]["verifiedQuote"])
        with self.factory() as db:
            b = db.get(CaseGenerationBatch, bid)
            self.assertEqual(execution.candidate_path(b).read_text(encoding="utf-8"), raw)
            self.assertEqual(len(b.attempts), 1)
            self.assertFalse(
                list(
                    db.scalars(
                        select(CaseGenerationApplication.id).where(
                            CaseGenerationApplication.run_id == int(row["id"])
                        )
                    )
                )
            )

    def test_compact_case_evidence_quotes_survive_worker_projection_export_and_application(self):
        row = self.prepare(legacy=False)
        fixed = json.loads(row["inputText"])
        source = fixed["materials"][0]["snapshot_ref"]
        quote = fixed["materials"][0]["segments"][0]["text"][:100]
        output = {
            "cases": [
                {
                    "action": "NEW",
                    "sources": [source],
                    "design": {
                        "title": "需求证据合成用例",
                        "steps": "提交订单",
                        "expected": "订单已创建",
                    },
                    "evidence_quotes": [{"source": source, "quote": quote}],
                }
            ],
            "notes": [],
            "complete": True,
        }
        done, _ = self.finish(row, lambda *args, **kwargs: json.dumps(output, ensure_ascii=False))
        refs = done["suggestions"][0]["evidence"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["quote"], quote)
        self.assertTrue(refs[0]["verifiedQuote"])
        self.assertEqual(done["rawReports"][0]["model_output"], output)
        contract.validate_report(json.loads(done["inputText"]), json.loads(done["reportText"]))
        applied = self.apply_all(done)
        self.assertEqual(applied["reportText"], done["reportText"])
        self.assertEqual(applied["suggestions"][0]["evidence"], refs)

    def test_compact_worker_save_import_review_and_application(self):
        row = self.prepare(legacy=False)
        with self.factory() as db:
            b = db.get(CaseGenerationBatch, row["batches"][0]["id"])
            self.assertEqual(b.input_snapshot["contract_version"], 3)
            self.assertTrue(
                all(
                    " · 本段字符" not in s["location"]
                    for m in b.input_snapshot["materials"]
                    for s in m["segments"]
                )
            )

        def answer(*args, **kwargs):
            self.assertIn("本次固定任务", args[5][0]["text"])
            return json.dumps(
                {
                    "cases": [
                        {
                            "action": "NEW",
                            "sources": ["M1-current"],
                            "design": {
                                "module": "订货",
                                "title": f"真实事务合成场景{i}",
                                "steps": ["选择订单", "提交"],
                                "expected": "订单成功提交",
                            },
                        }
                        for i in range(80)
                    ],
                    "notes": [
                        {
                            "kind": "BUSINESS_QUESTION",
                            "text": "精度待确认",
                            "sources": ["M1-current"],
                        }
                    ],
                    "complete": False,
                },
                ensure_ascii=False,
            )

        result, remote = self.finish(row, answer)
        self.assertEqual(remote.call_count, 1)
        self.assertEqual(len(result["suggestions"]), 80)
        self.assertEqual(len(result["questions"]), 1)
        self.assertEqual(result["outcome"], "PARTIAL")
        self.assertNotIn("coverage", result["rawReports"][0])
        imported = self.post(
            "/import",
            {
                "title": "简化结果导入",
                "input_json": result["inputText"],
                "report_json": result["reportText"],
                "bindings": [
                    {
                        "snapshot_ref": "M1-current",
                        "document_id": self.document_id,
                        "version_id": self.version_id,
                    }
                ],
            },
        )
        self.assertEqual(imported.status_code, 201, imported.text)
        self.assertEqual(len(imported.json()["suggestions"]), 80)
        applied = self.apply_all(result, [result["suggestions"][0]["key"]])
        self.assertFalse(applied["failures"])
        self.assertEqual(
            self.client.post(self.cases_api + "/search", json={}).json()["items"][0]["result"],
            "未测",
        )
        parent = imported.json()
        decision = self.post(
            f"/{parent['id']}/decisions",
            {
                "revision": parent["serverRevision"],
                "question_key": result["questions"][0]["key"],
                "conclusion": "人工确认保留两位小数",
                "basis": "固定需求条款",
                "affected": "仅金额精度",
                "confirmed": True,
            },
        )
        self.assertEqual(decision.status_code, 200, decision.text)
        supplement = self.post(
            f"/{parent['id']}/supplement",
            {
                "revision": decision.json()["serverRevision"],
                "decision_key": decision.json()["decisions"][-1]["key"],
                "request_id": str(uuid4()),
            },
        )
        self.assertEqual(supplement.status_code, 201, supplement.text)
        self.assertEqual(supplement.json()["status"], "PREPARED")
        fixed = json.loads(supplement.json()["inputText"])
        self.assertEqual(fixed["contract_version"], 3)
        self.assertEqual(fixed["scope"]["name"], "仅金额精度")
        self.assertTrue(fixed["decisions"])
        with self.factory() as db:
            from app.db.models import CaseGenerationRun

            saved = db.get(CaseGenerationRun, int(supplement.json()["id"]))
            self.assertEqual(saved.metadata_snapshot["origin"], "AI")
            self.assertNotIn("original_report", saved.metadata_snapshot)
            self.assertEqual(saved.metadata_snapshot["skill"]["contract_version"], 3)
        completed, remote = self.finish(supplement.json(), answer)
        self.assertNotIn("# 最小前置与执行准备", remote.call_args.args[4])
        runtime = remote.call_args.kwargs["instruction_messages"]
        self.assertEqual([m["role"] for m in runtime], ["developer"])
        self.assertEqual(len(runtime[0]["content"]), 10)
        self.assertTrue(any("# 最小前置与执行准备" in p["text"] for p in runtime[0]["content"]))
        self.assertIn("# 用例生成简化输出契约 v3", remote.call_args.args[4])
        self.assertIn('"contract_version": 3', completed["reportText"])

    def test_ai_condition_strings_save_valid_suggestions_and_keep_original_candidate(self):
        raw = []

        def answer(*args, **kwargs):
            report = json.loads(self.answer(*args, **kwargs))
            for rule in report["rules"]:
                for branch in rule["branches"]:
                    branch["conditions"] = "；".join(branch["conditions"])
            for scenario in report["scenarios"]:
                scenario["conditions"] = "；".join(scenario["conditions"])
            raw.append(json.dumps(report, ensure_ascii=False))
            return raw[-1]

        result, remote = self.finish(self.prepare(), answer)
        self.assertEqual(remote.call_count, 1)
        self.assertTrue(result["suggestions"])
        self.assertTrue(any("兼容修正" in text for text in result["limitations"]))
        with self.factory() as db:
            b = db.get(CaseGenerationBatch, result["batches"][0]["id"])
            self.assertEqual(execution.candidate_path(b).read_text(encoding="utf-8"), raw[0])
            self.assertTrue(b.attempts[-1]["format_repairs"]["fields"])
            self.assertIsInstance(b.report["scenarios"][0]["conditions"], list)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)

    def test_claim_syncs_parent_and_failure_persists_safe_diagnostics(self):
        row = self.prepare()
        self.post(f"/{row['id']}/start", {"revision": row["serverRevision"], "confirmed": True})
        with self.factory() as db:
            bid = execution.claim(db)
        running = self.client.get(self.api + f"/{row['id']}").json()
        self.assertEqual(running["status"], "RUNNING")
        self.assertTrue(running["batches"][0]["startedAt"])

        def upstream(*args, **kwargs):
            kwargs["diagnostics"].update(
                phase="receiving",
                request_id="req_abcdef123456",
                error_category="timeout",
                upstream_code="upstream_timeout",
                elapsed_seconds=900,
                received_bytes=1024,
                output_characters=10,
                termination="response.failed",
                message="private upstream prose",
            )
            kwargs["on_progress"](True)
            raise AppError(502, "ai_stream_failed")

        with patch.object(execution.responses, "analyze", side_effect=upstream) as remote:
            execution.execute(bid, self.factory)
        self.assertEqual(remote.call_count, 1)
        failed = self.client.get(self.api + f"/{row['id']}").json()
        self.assertEqual(failed["status"], "FAILED")
        diagnostics = failed["batches"][0]["diagnostics"]
        self.assertEqual(diagnostics["error_category"], "timeout")
        self.assertEqual(diagnostics["request_id"], "req_abcdef123456")
        self.assertEqual(diagnostics["received_bytes"], 1024)
        self.assertNotIn("private upstream prose", json.dumps(failed))
        self.assertFalse(failed["batches"][0]["candidateAvailable"])

    def test_cancel_retry_uses_frozen_input_and_retry_operators_ai(self):
        row = self.prepare()
        self.post(f"/{row['id']}/cancel")
        self.login(self.admin_name)
        b = row["batches"][0]
        response = self.post(f"/{row['id']}/batches/{b['id']}/retry", {"request_id": str(uuid4())})
        self.assertEqual(response.status_code, 202, response.text)
        with self.factory() as db:
            fixed = db.get(CaseGenerationBatch, b["id"]).input_snapshot
            bid = execution.claim(db)
        with patch.object(execution.responses, "analyze", side_effect=self.answer) as remote:
            execution.execute(bid, self.factory)
        self.assertEqual(remote.call_args.args[2], f"synthetic-secret-{self.admin_id}")
        sent = json.loads(remote.call_args.args[5][0]["text"])
        self.assertEqual(sent, fixed)

    def test_missing_title_candidate_revalidation_is_free_audited_and_not_applied(self):
        row = self.prepare(legacy=False)
        self.post(f"/{row['id']}/start", {"revision": row["serverRevision"], "confirmed": True})
        with self.factory() as db:
            bid = execution.claim(db)
        output = {
            "cases": [
                {
                    "action": "NEW",
                    "target": None,
                    "sources": ["M1-current"],
                    "design": {
                        "description": "验证合成原型保存后显示结果。",
                        "steps": "提交保存。",
                        "expected": "显示保存结果。",
                    },
                }
            ],
            "notes": [],
            "complete": True,
        }
        raw = json.dumps(output, ensure_ascii=False)
        with (
            patch.object(execution.responses, "analyze", return_value=raw) as initial_call,
            # Simulate an old strict worker failure; recover its saved response without AI.
            patch.object(
                contract, "validate_report", side_effect=AppError(422, "generation_report_invalid")
            ),
        ):
            execution.execute(bid, self.factory)
        initial_call.assert_called_once()
        failed = self.client.get(self.api + f"/{row['id']}").json()
        self.assertEqual(failed["status"], "FAILED")
        self.assertTrue(failed["batches"][0]["candidateAvailable"])
        with patch.object(
            execution.responses, "analyze", side_effect=AssertionError("no paid retry")
        ) as paid:
            response = self.post(f"/{row['id']}/batches/{bid}/revalidate")
        self.assertEqual(response.status_code, 200, response.text)
        paid.assert_not_called()
        saved = response.json()
        self.assertEqual(saved["status"], "COMPLETED")
        self.assertEqual(len(saved["suggestions"]), 1)
        self.assertIn(
            "原样沿用用例描述", saved["rawReports"][0]["model_output"]["cases"][0]["note"]
        )
        with self.factory() as db:
            b = db.get(CaseGenerationBatch, bid)
            self.assertEqual(execution.candidate_path(b).read_text(encoding="utf-8"), raw)
            repair = b.attempts[-1]["format_repairs"]
            self.assertEqual(repair["fields"], ["cases[0].design.title", "cases[0].note"])
            self.assertEqual(repair["original_hash"], contract.digest(output))
            self.assertEqual(repair["normalized_hash"], contract.digest(b.report))
            self.assertEqual(len(b.attempts), 1)
            self.assertEqual(
                list(
                    db.scalars(
                        select(CaseGenerationApplication).where(
                            CaseGenerationApplication.run_id == int(row["id"])
                        )
                    )
                ),
                [],
            )

    def test_invalid_candidate_revalidation_is_free_and_chat_is_isolated(self):
        row = self.prepare()
        self.post(f"/{row['id']}/start", {"revision": row["serverRevision"], "confirmed": True})
        with self.factory() as db:
            bid = execution.claim(db)
        with patch.object(execution.responses, "analyze", return_value='{"wrong":"candidate"}'):
            execution.execute(bid, self.factory)
        failed = self.client.get(self.api + f"/{row['id']}").json()
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(
            self.client.get(self.api + f"/{row['id']}/batches/{bid}/candidate").status_code, 200
        )
        with self.factory() as db:
            b = db.get(CaseGenerationBatch, bid)
            raw = self.answer(
                None, None, None, None, None, [{"text": json.dumps(b.input_snapshot)}]
            )
            execution.candidate_path(b).write_text(raw, encoding="utf-8")
        with patch.object(execution.responses, "analyze") as paid:
            response = self.post(f"/{row['id']}/batches/{bid}/revalidate")
            self.assertEqual(response.status_code, 200, response.text)
            paid.assert_not_called()
        turn = self.post(
            f"/{row['id']}/chat",
            {"request_id": str(uuid4()), "function_key": "F-SCOPE", "question": "解释固定场景"},
        )
        self.assertEqual(turn.status_code, 202, turn.text)
        with self.factory() as db:
            tid = execution.claim_chat(db)
        with patch.object(execution.responses, "converse", return_value="合成解释，不应用用例"):
            execution.execute_chat(tid, self.factory)
        history = self.client.get(self.api + f"/{row['id']}/chat?function_key=F-SCOPE").json()
        self.assertEqual(history["items"][0]["status"], "COMPLETED")
        self.assertEqual(self.client.get(self.api + f"/{row['id']}/chat").json()["items"], [])
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)

    def test_lifecycle_preserves_versions_records_and_blocks_new_tests(self):
        done, _ = self.finish(self.prepare())
        self.apply_all(done)
        current = self.client.post(self.cases_api + "/search", json={}).json()
        c = current["items"][0]
        before = self.client.get(self.cases_api + f"/{c['id']}").json()["versions"]
        retired = self.client.post(
            self.cases_api + f"/{c['id']}/lifecycle",
            json={
                "revision": current["revision"],
                "confirmed": True,
                "lifecycle": "RETIRED",
                "reason": "人工停用验证",
            },
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(retired.status_code, 200, retired.text)
        self.assertEqual(retired.json()["versions"], before)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)
        all_cases = self.client.post(self.cases_api + "/search", json={"lifecycle": "ALL"}).json()
        self.assertEqual(all_cases["total"], 1)
        bad = self.client.patch(
            self.cases_api + f"/{c['id']}",
            json={
                **{
                    f: c[f]
                    for f in __import__(
                        "app.modules.cases.schemas", fromlist=["DESIGN_FIELDS"]
                    ).DESIGN_FIELDS
                },
                "revision": all_cases["revision"],
                "request_id": str(uuid4()),
                "result": "通过",
                "tester": "执行人",
            },
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(bad.status_code, 422, bad.text)
        restored = self.client.post(
            self.cases_api + f"/{c['id']}/lifecycle",
            json={
                "revision": all_cases["revision"],
                "confirmed": True,
                "lifecycle": "ACTIVE",
                "reason": "人工恢复验证",
            },
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(restored.json()["versions"], before)

    def test_late_response_after_cancel_and_retry_cannot_replace_new_attempt(self):
        row = self.prepare()
        self.post(f"/{row['id']}/start", {"revision": row["serverRevision"], "confirmed": True})
        bid = row["batches"][0]["id"]
        old_request = json.loads(row["inputText"])["request_id"]
        with self.factory() as db:
            execution.claim(db)
        new_request = str(uuid4())

        def late(*args, **kwargs):
            self.post(f"/{row['id']}/cancel")
            self.login(self.admin_name)
            retried = self.post(f"/{row['id']}/batches/{bid}/retry", {"request_id": new_request})
            self.assertEqual(retried.status_code, 202, retried.text)
            return self.answer(*args, **kwargs)

        with patch.object(execution.responses, "analyze", side_effect=late):
            execution.execute(bid, self.factory)
        with self.factory() as db:
            b = db.get(CaseGenerationBatch, bid)
            self.assertEqual((b.request_id, b.status, b.report), (new_request, "QUEUED", {}))
            self.assertTrue(execution.candidate_path(b, old_request).is_file())
            self.assertFalse(execution.candidate_path(b).is_file())
            self.assertEqual(b.attempts[0]["request_id"], old_request)
            self.assertTrue(b.attempts[0]["candidate"])

    def test_completed_reply_requires_human_draft_form_and_keeps_original_report(self):
        done, _ = self.finish(self.prepare())
        sent = self.post(
            f"/{done['id']}/chat",
            {"request_id": str(uuid4()), "function_key": "", "question": "补充一个场景"},
        )
        tid = sent.json()["id"]
        with self.factory() as db:
            execution.claim_chat(db)
        with patch.object(
            execution.responses, "converse", return_value="合成测试建议，尚未人工确认"
        ):
            execution.execute_chat(tid, self.factory)
        draft = copy.deepcopy(done["suggestions"][0]["design"])
        draft["title"] = "人工核对的补充场景"
        before = done["reportText"]
        added = self.post(
            f"/{done['id']}/chat/{tid}/draft",
            {
                "request_id": str(uuid4()),
                "design": draft,
                "evidence_refs": ["b1:E1"],
                "note": "已依据固定正文核对可执行路径",
                "confirmed": True,
            },
        )
        self.assertEqual(added.status_code, 201, added.text)
        self.assertEqual(added.json()["reportText"], before)
        self.assertEqual(len(added.json()["suggestions"]), 2)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)
        self.assertNotEqual(
            added.json()["suggestions"][1]["key"], added.json()["suggestions"][0]["key"]
        )
