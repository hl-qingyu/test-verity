"""Untrusted candidates stay visible and corrections never silently choose duplicate values."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import test_case_analysis
import test_case_generation
import test_change_analysis
import test_code_analysis

from app.core.errors import AppError
from app.modules.candidate_results import service as common
from app.modules.candidate_results.schemas import CandidateReviewInput
from app.modules.case_generation import compact, delivery, delivery_files
from app.modules.requirements.risk_service import json_object


class CandidateResultsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(
            os.environ,
            {
                "DOCUMENT_STORAGE_PATH": str(Path(self.temp.name) / "documents"),
                "CASE_GENERATION_RESULT_PATH": str(Path(self.temp.name) / "generation"),
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)

    def payload(self, original, value, reason="人工确认P1"):
        return CandidateReviewInput(
            request_id=uuid4(),
            base_sha256=common.fingerprint(original),
            candidate_json=value,
            reason=reason,
            confirmed=True,
        )

    def test_duplicate_values_and_all_siblings_visible_for_every_analysis_shape(self):
        for group in ("findings", "risks", "changes", "requirements", "notes"):
            raw = (
                '{"'
                + group
                + '": [{"title":"冲突","priority":"P2","priority":"P1"},{"title":"有效候选"}]}'
            )
            value = common.inspect(raw, "risk_json_invalid")
            self.assertEqual(len(value["items"]), 2)
            self.assertEqual(value["conflicts"][0]["path"], f"{group}[0].priority")
            self.assertEqual(value["conflicts"][0]["values"], ['"P2"', '"P1"'])
            self.assertEqual(value["candidateJson"], raw)
            with self.assertRaises(AppError):
                json_object(raw)
        self.assertTrue(common.inspect("{truncated")["parseError"])
        self.assertFalse(common.inspect('{"items":[{"title":"\\ud800"}]}')["parseError"])

    def test_invalid_draft_is_immutable_audited_then_corrected_with_stale_and_replay_guards(self):
        original = '{"items":[{"priority":"P2","priority":"P1"}]}'
        first = self.payload(original, original)
        result, meta, error = common.evaluate(
            "code_analysis", 1, original, {}, first, 30, json_object
        )
        self.assertIsNone(result)
        self.assertEqual(error, "risk_json_invalid")
        self.assertTrue(common.replay(meta, first))
        self.assertEqual(common.current("code_analysis", 1, original, meta), original)
        first_file = (
            Path(self.temp.name)
            / "candidate-reviews"
            / meta["candidate_review_history"][0]["artifact"]
        )
        first_bytes = first_file.read_bytes()
        fixed = '{"items":[{"priority":"P1"}]}'
        second = self.payload(original, fixed)
        result, updated, error = common.evaluate(
            "code_analysis", 1, original, meta, second, 30, json_object
        )
        self.assertEqual(result["items"][0]["priority"], "P1")
        self.assertEqual(error, "")
        self.assertEqual(first_file.read_bytes(), first_bytes)
        self.assertEqual(len(updated["candidate_review_history"]), 2)
        self.assertEqual(common.current("code_analysis", 1, original, updated), fixed)
        with self.assertRaises(AppError):
            common.evaluate(
                "code_analysis",
                1,
                original,
                updated,
                self.payload(original, fixed),
                30,
                json_object,
            )
        first.candidate_json = fixed
        with self.assertRaises(AppError):
            common.replay(updated, first)
        first_file.write_bytes(b"changed")
        with self.assertRaises(AppError):
            common.current("code_analysis", 1, original, meta)

    def test_compact_bad_item_does_not_block_valid_siblings_and_keys_survive_correction(self):
        data, output = test_case_generation.sample("compact")
        output["cases"] = output["cases"][:3]
        output["notes"] = []
        output["complete"] = True
        raw = json.dumps(output, ensure_ascii=False).replace(
            '"priority": "P1"', '"priority": "P2", "priority": "P1"', 1
        )
        delivered = delivery.process(data, raw)
        self.assertEqual(len(delivered.report["suggestions"]), 2)
        self.assertEqual(delivered.report["outcome"], "PARTIAL")
        self.assertEqual(delivered.report["source_indices"]["cases"], [1, 3])
        self.assertEqual(delivered.issues[0]["status"], "PENDING")
        self.assertEqual(delivered.issues[0]["duplicates"][0]["values"], ['"P2"', '"P1"'])
        self.assertEqual(compact.validate(data, delivered.report), delivered.report)
        fixed = delivery.process(
            data,
            raw,
            {"case-2": {"corrected_json": json.dumps(output["cases"][1]), "reason": "保留P1"}},
        )
        self.assertEqual(len(fixed.report["suggestions"]), 3)
        self.assertEqual(fixed.issues[0]["status"], "RESOLVED")
        for old in delivered.report["suggestions"]:
            self.assertEqual(
                next(s for s in fixed.report["suggestions"] if s["key"] == old["key"]), old
            )
        ignored = delivery.process(data, raw, {"case-2": {"ignored": True, "reason": "暂不采纳"}})
        self.assertEqual(ignored.report, delivered.report)
        self.assertEqual(ignored.issues[0]["status"], "IGNORED")

    def test_compact_local_invalid_sources_missing_field_and_nonfinite_are_retained(self):
        data, output = test_case_generation.sample("compact")
        output["cases"] = output["cases"][:3]
        for broken in (
            {"sources": ["other-project"]},
            {"design": {"title": "缺步骤"}},
            {"sources": [float("nan")]},
        ):
            value = copy.deepcopy(output)
            value["cases"][1].update(broken)
            result = delivery.process(data, json.dumps(value))
            self.assertEqual(len(result.report["suggestions"]), 2)
            self.assertEqual(result.issues[0]["ordinal"], 2)
            self.assertTrue(result.issues[0]["raw_json"])
        for raw in ("{truncated", '{"cases":[],"cases":[],"notes":[],"complete":true}'):
            result = delivery.process(data, raw)
            self.assertIsNone(result.report)
            self.assertEqual(result.issues[0]["raw_json"], raw)

    def test_review_storage_keeps_history_and_hides_original_from_other_actor(self):
        data, output = test_case_generation.sample("compact")
        output["cases"][1]["sources"] = ["unknown"]
        result = delivery.process(data, json.dumps(output))
        batch = SimpleNamespace(
            id=1, request_id=str(uuid4()), actor_id=30, attempts=[], status="COMPLETED"
        )
        delivery_files.save(batch, result)
        descriptor = copy.deepcopy(delivery_files.current_attempt(batch)["candidate_delivery"])
        self.assertTrue(delivery_files.views(batch, SimpleNamespace(id=30))[0]["rawJson"])
        self.assertFalse(delivery_files.views(batch, SimpleNamespace(id=31))[0]["rawJson"])
        delivery_files.save(batch, result, audit={"reason": "核对"})
        self.assertEqual(
            len(delivery_files.current_attempt(batch)["candidate_delivery_history"]), 1
        )
        self.assertEqual(delivery_files.read(batch, descriptor)["issues"], result.issues)

    def test_module_adapters_use_real_contracts_and_keep_invalid_drafts_without_ai(self):
        from app.modules.case_analysis import candidate_review as cases
        from app.modules.change_analysis import candidate_review as change
        from app.modules.code_analysis import candidate_review as code

        code_data, code_report = test_code_analysis.sample()
        change_data, change_report = test_change_analysis.sample("requirement")
        case_data = {"cases": [{"id": 1}], "materials": [], "mode": "QUALITY"}
        for module, data, report, kind in (
            (code, code_data, code_report, "code_analysis"),
            (change, change_data, change_report, "change_analysis"),
            (cases, case_data, test_case_analysis.report(), "case_analysis"),
        ):
            with self.subTest(kind=kind):
                original = json.dumps(report).replace('"title":', '"title":"conflict","title":', 1)
                path = Path(self.temp.name) / f"{kind}.txt"
                path.write_text(original, encoding="utf-8")
                row = SimpleNamespace(
                    id=1,
                    actor_id=30,
                    status="FAILED",
                    error_code="risk_json_invalid",
                    metadata_snapshot={"origin": "AI"},
                    ai_config={},
                    input_snapshot=data,
                    report={},
                    revision=1,
                    attempts=[{"raw_response": original}],
                )
                actor = SimpleNamespace(id=30)
                db = Mock()
                with (
                    patch.object(module.service, "own", return_value=row),
                    patch.object(module.sources, "recheck"),
                ):
                    context = (
                        patch.object(module.artifacts, "candidate_path", return_value=path)
                        if module is not cases
                        else unittest.mock.patch.dict({}, {})
                    )
                    with context:
                        view = module.review(3, 1, actor, db)
                        self.assertTrue(view["canEdit"])
                        self.assertTrue(view["items"])
                        pending = module.review(3, 1, actor, db, self.payload(original, original))
                        self.assertFalse(pending["published"])
                        self.assertEqual(row.report, {})
                        saved = module.review(
                            3, 1, actor, db, self.payload(original, json.dumps(report))
                        )
                        self.assertTrue(saved["published"])
                        self.assertTrue(row.report)
                        self.assertEqual(path.read_text(encoding="utf-8"), original)
                        row.actor_id = 31
                        with self.assertRaises(AppError):
                            module.review(3, 1, actor, db)

    def test_requirement_adapter_saves_failed_draft_and_uses_full_validation_before_report_storage(
        self,
    ):
        import test_risk_reports

        from app.modules.requirements import candidate_review as module

        data, report = test_risk_reports.sample()
        original = json.dumps(report).replace('"title":', '"title":"conflict","title":', 1)
        path = Path(self.temp.name) / "requirements.txt"
        path.write_text(original, encoding="utf-8")
        row = SimpleNamespace(
            id=1,
            project_id=1,
            actor_id=30,
            status="FAILED",
            deleted_at=None,
            error_code="risk_json_invalid",
            context={"input": data, "bindings": []},
            title="合成分析",
        )
        db = Mock()
        db.scalar.return_value = row
        with (
            patch.object(module.documents, "access"),
            patch.object(module.service, "frozen_materials"),
            patch.object(module.artifacts, "candidate_path", return_value=path),
            patch.object(module.risk_service, "store_report", return_value={"id": 41}) as store,
        ):
            view = module.review(1, 1, SimpleNamespace(id=30), db)
            self.assertTrue(view["items"])
            pending = module.review(
                1, 1, SimpleNamespace(id=30), db, self.payload(original, original)
            )
            self.assertFalse(pending["published"])
            store.assert_not_called()
            saved = module.review(
                1, 1, SimpleNamespace(id=30), db, self.payload(original, json.dumps(report))
            )
            self.assertTrue(saved["published"])
            store.assert_called_once()
            self.assertEqual(row.report_id, 41)
            self.assertEqual(path.read_text(encoding="utf-8"), original)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class CandidateReviewDatabaseTests(unittest.TestCase):
    """Real API/auth/JSONB transactions; fixed-source IO is mocked for synthetic contracts."""

    setUpClass = classmethod(test_case_generation.GenerationDatabaseTests.setUpClass.__func__)
    login = test_case_generation.GenerationDatabaseTests.login
    factory = test_case_generation.GenerationDatabaseTests.factory

    def setUp(self):
        import test_requirements

        test_requirements.RequirementDatabaseTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {
                name: str(Path(self.temp.name) / name.lower())
                for name in (
                    "DOCUMENT_STORAGE_PATH",
                    "REQUIREMENT_ANALYSIS_RESULT_PATH",
                    "CODE_ANALYSIS_RESULT_PATH",
                    "CHANGE_ANALYSIS_RESULT_PATH",
                )
            },
        )
        self.env.start()

    def tearDown(self):
        import test_requirements

        self.env.stop()
        self.temp.cleanup()
        test_requirements.RequirementDatabaseTests.tearDown(self)

    def test_four_module_candidate_endpoints_preserve_failed_drafts_publish_and_deny_foreign_owner(
        self,
    ):
        from contextlib import ExitStack

        import test_auth
        import test_risk_reports

        from app.db.models import (
            CaseAnalysisRun,
            ChangeAnalysisTask,
            CodeAnalysisTask,
            RequirementRiskAnalysis,
        )
        from app.modules.case_analysis import candidate_review as cases
        from app.modules.change_analysis import candidate_review as change
        from app.modules.code_analysis import candidate_review as code
        from app.modules.requirements import candidate_review as requirements

        code_data, code_report = test_code_analysis.sample()
        change_data, change_report = test_change_analysis.sample("requirement")
        risk_data, risk_report = test_risk_reports.sample()
        case_data = {"cases": [{"id": 1}], "materials": [], "mode": "QUALITY"}
        entries = [
            (code, CodeAnalysisTask, code_data, code_report, "code-analysis"),
            (change, ChangeAnalysisTask, change_data, change_report, "change-analysis"),
            (cases, CaseAnalysisRun, case_data, test_case_analysis.report(), "case-analysis"),
            (
                requirements,
                RequirementRiskAnalysis,
                risk_data,
                risk_report,
                "requirements/risk-analyses",
            ),
        ]
        for module, model, data, report, segment in entries:
            with self.subTest(segment=segment), ExitStack() as stack:
                for value in (data, report):
                    if "project_id" in value:
                        value["project_id"] = self.project
                original = json.dumps(report).replace('"title":', '"title":"conflict","title":', 1)
                fields = dict(
                    project_id=self.project,
                    actor_id=self.member_id,
                    request_id=str(uuid4()),
                    title="合成候选API验证",
                    status="FAILED",
                    error_code="risk_json_invalid",
                    ai_config={},
                )
                if module is requirements:
                    fields.update(selections=[], context={"input": data, "bindings": []})
                    stack.enter_context(patch.object(module.service, "frozen_materials"))
                else:
                    fields.update(input_snapshot=data, metadata_snapshot={"origin": "AI"})
                    stack.enter_context(patch.object(module.sources, "recheck"))
                    if module is cases:
                        fields.update(mode="QUALITY", attempts=[{"raw_response": original}])
                    else:
                        fields.update(targets=data.get("targets", []))
                    if module is change:
                        fields.update(mode=data["mode"])
                with self.factory() as db:
                    row = model(**fields)
                    db.add(row)
                    db.flush()
                    identity = row.id
                    db.commit()
                if module is not cases:
                    file = module.artifacts.candidate_path(identity)
                    file.parent.mkdir(parents=True, exist_ok=True)
                    file.write_text(original, encoding="utf-8")
                endpoint = f"/api/projects/{self.project}/{segment}/{identity}/candidate-review"
                read = self.client.get(endpoint)
                self.assertEqual(read.status_code, 200, read.text)
                self.assertTrue(read.json()["conflicts"])
                payload = {
                    "request_id": str(uuid4()),
                    "base_sha256": read.json()["sha256"],
                    "candidate_json": original,
                    "reason": "保存原始问题草稿",
                    "confirmed": True,
                }
                self.assertEqual(self.client.post(endpoint, json=payload).status_code, 403)
                pending = self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN)
                self.assertEqual(pending.status_code, 200, pending.text)
                self.assertFalse(pending.json()["published"])
                payload.update(
                    request_id=str(uuid4()),
                    candidate_json=json.dumps(report),
                    reason="人工删除冲突值",
                )
                fixed = self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN)
                self.assertEqual(fixed.status_code, 200, fixed.text)
                self.assertTrue(fixed.json()["published"])
                self.assertEqual(len(fixed.json()["history"]), 2)
                self.assertEqual(
                    self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN).status_code,
                    200,
                )
                with self.factory() as db:
                    self.assertEqual(db.get(model, identity).status, "COMPLETED")
                if module is not cases:
                    self.assertEqual(file.read_text(encoding="utf-8"), original)
                self.login(self.admin_name)
                self.assertEqual(self.client.get(endpoint).status_code, 403)
                self.assertEqual(
                    self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN).status_code,
                    403,
                )
                self.login(self.member_name)
                self.assertEqual(
                    self.client.get(
                        endpoint.replace(f"/projects/{self.project}/", f"/projects/{self.other}/")
                    ).status_code,
                    404,
                )
