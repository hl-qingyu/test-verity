import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_requirements
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    AnalysisAcceptance,
    CaseGenerationBatch,
    CaseGenerationRun,
    CodeAnalysisTask,
    Project,
    RequirementRiskReport,
    UserAccount,
)
from app.modules.acceptance import service, sources


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL")
class AcceptanceTests(unittest.TestCase):
    setUpClass = classmethod(test_requirements.RequirementDatabaseTests.setUpClass.__func__)
    login = test_requirements.RequirementDatabaseTests.login
    setUp = test_requirements.RequirementDatabaseTests.setUp
    tearDown = test_requirements.RequirementDatabaseTests.tearDown

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def summary_response(self):
        self.login(self.admin_name)
        response = self.client.get(self.url())
        self.login(self.member_name)
        return response

    def test_summary_is_administrator_only_even_for_project_owner(self):
        identity = self.seed("code", 1)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "admin_required")
        with self.factory() as db:
            db.get(Project, self.project).owner_id = self.member_id
            db.commit()
            with self.assertRaises(AppError) as caught:
                service.project_summary(self.project, db.get(UserAccount, self.member_id), db)
            self.assertEqual(caught.exception.detail, "admin_required")
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.read("code", identity)["record_id"], identity)
        result = self.summary_response()
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(
            next(g for g in result.json()["modules"] if g["module"] == "code")["metrics"]["total"],
            1,
        )
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.url()).status_code, 401)

    def seed(self, module, size=2, project_id=None):
        with self.factory() as db:
            group = sources.GROUPS[module][0]
            items = [
                {
                    "key": f"C{i}",
                    "title": f"人工验收合成{i}",
                    "kind": "NEW" if module == "generate" else "QUALITY",
                    "description": "固定原始结论 PRIVATE_BODY",
                    "suggestion": "修订预期",
                }
                for i in range(size)
            ]
            report = {group: items}
            if module == "changes":
                report["regression_scope"] = [{"key": "G1", "title": "回归建议"}]
            if module == "requirements":
                row = RequirementRiskReport(
                    project_id=project_id or self.project,
                    title="合成需求",
                    input_filename="input.json",
                    report_filename="report.json",
                    sha256=uuid4().hex * 2,
                    input={},
                    report=report,
                    bindings=[],
                    created_by=self.member_id,
                )
            else:
                values = dict(
                    project_id=project_id or self.project,
                    actor_id=self.member_id,
                    request_id=str(uuid4()),
                    title="合成AI结果",
                    status="COMPLETED",
                    input_snapshot={},
                )
                if module in {"generate", "coverage"}:
                    values["mode"] = "INITIAL" if module == "generate" else "QUALITY"
                if module == "code":
                    values.update(targets=[], ai_config={})
                if module == "changes":
                    values.update(mode="CODE_CHANGE", targets=[], ai_config={})
                if module == "coverage":
                    values.update(metadata_snapshot={})
                if module != "generate":
                    values["report"] = report
                row = sources.MODELS[module](**values)
            db.add(row)
            db.flush()
            if module == "generate":
                row.handling = {"suggestions": {"C0": [{"status": "待审阅"}, {"status": "已应用"}]}}
                db.add(
                    CaseGenerationBatch(
                        run_id=row.id,
                        batch_ref="B1",
                        request_id=str(uuid4()),
                        actor_id=self.member_id,
                        status="COMPLETED",
                        report=report,
                    )
                )
            if module == "coverage":
                row.handling = {"C0": {"applied": {"kind": "UPDATE", "case_id": 1, "version": 2}}}
            db.commit()
            return row.id

    def test_all_projects_uses_all_five_sources_and_preserves_project_scopes(self):
        url = "/api/analysis-acceptance"
        self.assertEqual(self.client.get(url).status_code, 403)
        with self.factory() as db:
            with self.assertRaises(AppError) as caught:
                service.project_summary(None, db.get(UserAccount, self.member_id), db)
            self.assertEqual(caught.exception.detail, "admin_required")
        self.login(self.admin_name)
        before = self.client.get(url).json()
        for module in sources.MODELS:
            for project_id, size in [(self.project, 2), (self.other, 8)]:
                identity = self.seed(module, size, project_id)
                if module != "generate":
                    entry = {
                        "requirements": {"status": "NEEDS_INFO"},
                        "coverage": {"state": "已确认待处理"},
                        "code": {"status": "CONFIRMED"},
                        "changes": {"status": "CONFIRMED"},
                    }[module]
                    self.set_handling(module, identity, {"C0": entry})
                if module == "code":
                    path = f"/api/projects/{project_id}/analysis-acceptance/code/{identity}"
                    data = self.client.get(path).json()
                    data["state"]["criteria"] = [
                        {
                            "id": "same-project-local-id",
                            "title": "各项目独立基准",
                            "basis": "原固定范围",
                            "critical": True,
                            "baseline": True,
                            "result": "COVERED" if project_id == self.project else "MISSING",
                            "matched_key": "findings:C0" if project_id == self.project else "",
                            "scope_confirmed": True,
                        }
                    ]
                    saved = self.client.post(
                        path,
                        json={k: data[k] for k in ("revision", "source_token", "state")},
                        headers={"Origin": "http://127.0.0.1:5173"},
                    )
                    self.assertEqual(saved.status_code, 200, saved.text)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(response.json()["project_id"])
        self.assertNotIn("PRIVATE_BODY", response.text)
        for previous, current in zip(before["modules"], response.json()["modules"], strict=True):
            self.assertTrue(current["available"])
            self.assertEqual(current["metrics"]["total"] - previous["metrics"]["total"], 10)
            self.assertEqual(current["metrics"]["valid"] - previous["metrics"]["valid"], 2)
            self.assertEqual(current["metrics"]["records"] - previous["metrics"]["records"], 2)
            if current["module"] == "generate":
                self.assertEqual(current["metrics"]["adopted"] - previous["metrics"]["adopted"], 2)
            if current["module"] == "code":
                for key, increase in [
                    ("baseline_total", 2),
                    ("baseline_covered", 1),
                    ("missing", 1),
                ]:
                    self.assertEqual(current["metrics"][key] - previous["metrics"][key], increase)
        for project_id, size in [(self.project, 2), (self.other, 8)]:
            scoped = self.client.get(f"/api/projects/{project_id}/analysis-acceptance").json()
            self.assertEqual(scoped["project_id"], project_id)
            for group in scoped["modules"]:
                self.assertEqual(group["metrics"]["total"], size)
        self.assertEqual(self.client.get("/api/projects/0/analysis-acceptance").status_code, 404)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AnalysisAcceptance)), 2)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(url).status_code, 401)

    def url(self, module="", identity=""):
        return f"/api/projects/{self.project}/analysis-acceptance" + (
            f"/{module}/{identity}" if module else ""
        )

    def read(self, module, identity):
        response = self.client.get(self.url(module, identity))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def write(self, module, identity, data, status=200):
        response = self.client.post(
            self.url(module, identity),
            json={k: data[k] for k in ("revision", "source_token", "state")},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def set_handling(self, module, identity, entries):
        with self.factory() as db:
            row = db.get(sources.MODELS[module], identity)
            row.handling = {"suggestions": entries} if module == "generate" else entries
            db.commit()

    def test_five_sources_automatically_reuse_detail_decisions_without_second_confirmation(self):
        for module in sources.MODELS:
            identity = self.seed(module)
            if module == "requirements":
                entries = {"C0": {"status": "NEEDS_INFO"}, "C1": {"status": "NOT_APPLICABLE"}}
            elif module in {"code", "changes"}:
                entries = {"C0": {"status": "CONFIRMED"}, "C1": {"status": "FALSE_POSITIVE"}}
            elif module == "coverage":
                entries = {"C0": {"state": "已确认待处理"}, "C1": {"state": "不适用"}}
            else:
                entries = {
                    "C0": [{"status": "需人工确认"}, {"status": "已应用", "evidenceChecked": True}],
                    "C1": [{"status": "已忽略"}],
                }
            if module == "changes":
                entries["G1"] = {"status": "ACCEPTED"}
            self.set_handling(module, identity, entries)
            data = self.read(module, identity)
            self.assertEqual(data["metrics"]["valid"], 1, module)
            self.assertEqual(data["metrics"]["invalid"] + data["metrics"]["dismissed"], 1, module)
            self.assertEqual(data["revision"], 0)
            if module == "changes":
                self.assertEqual(data["metrics"]["regression_usable"], 1)
            if module == "generate":
                self.assertEqual(data["metrics"]["evidence_sufficient"], 1)
        value = self.summary_response()
        self.assertEqual(value.status_code, 200, value.text)
        self.assertNotIn("PRIVATE_BODY", value.text)
        with self.factory() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AnalysisAcceptance)), 0)

    def test_optional_scope_keeps_audit_and_does_not_allow_second_item_judgments(self):
        identity = self.seed("code")
        self.set_handling(
            "code", identity, {"C0": {"status": "CONFIRMED"}, "C1": {"status": "PENDING"}}
        )
        data = self.read("code", identity)
        data["state"]["criteria"] = [
            {
                "id": "b1",
                "title": "关键规则",
                "basis": "原固定资料第1节",
                "baseline": True,
                "result": "COVERED",
                "matched_key": "findings:C0",
                "scope_confirmed": True,
            },
            {
                "id": "m1",
                "title": "失败恢复",
                "basis": "原固定资料第2节",
                "baseline": True,
                "critical": True,
                "result": "MISSING",
                "scope_confirmed": True,
            },
        ]
        data["state"].update(scope_reviewed=True, note="已核对原范围")
        saved = self.write("code", identity, data)
        self.assertEqual(saved["metrics"]["missing"], 1)
        self.assertEqual(saved["metrics"]["baseline_covered"], 1)
        self.assertEqual(len(saved["history"]), 1)
        self.assertEqual(self.write("code", identity, saved)["revision"], 1)
        with self.factory() as db:
            row = db.scalar(
                select(AnalysisAcceptance).where(
                    AnalysisAcceptance.project_id == self.project,
                    AnalysisAcceptance.module == "code",
                    AnalysisAcceptance.record_id == identity,
                )
            )
            row.state = {
                **row.state,
                "items": {
                    "findings:C0": {
                        "verdict": "INVALID",
                        "reason": "UNSUPPORTED",
                        "evidence": "INSUFFICIENT",
                        "note": "旧独立评价",
                        "usable": None,
                    }
                },
            }
            old_history = list(row.history)
            db.commit()
        recognized = self.read("code", identity)
        self.assertEqual(recognized["metrics"]["valid"], 1)
        self.assertEqual(recognized["history"], old_history)
        with self.factory() as db:
            row = db.scalar(
                select(AnalysisAcceptance).where(
                    AnalysisAcceptance.project_id == self.project,
                    AnalysisAcceptance.record_id == identity,
                    AnalysisAcceptance.module == "code",
                )
            )
            self.assertEqual(row.state["items"]["findings:C0"]["note"], "旧独立评价")
        self.write("code", identity, data, 409)
        saved["state"]["items"]["findings:C1"]["verdict"] = "VALID"
        self.assertEqual(
            self.write("code", identity, saved, 409)["detail"], "acceptance_use_detail"
        )
        current = self.read("code", identity)
        self.set_handling("code", identity, {"C0": {"status": "PENDING"}})
        self.write("code", identity, current, 409)
        refreshed = self.read("code", identity)
        self.assertEqual(refreshed["metrics"]["valid"], 0)
        self.assertEqual(refreshed["metrics"]["baseline_covered"], 0)
        self.assertEqual(refreshed["metrics"]["missing"], 1)
        self.assertEqual(len(refreshed["history"]), 1)

    def test_rejects_cross_project_foreign_keys_invalid_coverage_and_missing_origin(self):
        identity = self.seed("code")
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.other}/analysis-acceptance/code/{identity}"
            ).status_code,
            404,
        )
        data = self.read("code", identity)
        data["state"]["items"] = {"forged": {"verdict": "VALID"}}
        self.write("code", identity, data, 409)
        data = self.read("code", identity)
        data["state"]["criteria"] = [
            {
                "id": "x",
                "title": "原范围",
                "basis": "固定第3行",
                "baseline": True,
                "result": "COVERED",
                "matched_key": "findings:C0",
                "scope_confirmed": True,
            }
        ]
        self.write("code", identity, data, 422)
        self.assertEqual(self.client.post(self.url("code", identity), json=data).status_code, 403)
        self.assertEqual(self.client.get(self.url("unknown", identity)).status_code, 422)

    def test_empty_report_stale_scope_and_weighted_detail_counts(self):
        empty = self.seed("requirements", 0)
        data = self.read("requirements", empty)
        self.assertEqual(data["metrics"]["total"], 0)
        self.assertFalse(data["state"]["scope_reviewed"])
        data["state"].update(scope_reviewed=True, note="已核对固定范围，无问题输出")
        self.write("requirements", empty, data)
        for size in [2, 8]:
            identity = self.seed("code", size)
            self.set_handling(
                "code",
                identity,
                {
                    f"C{i}": {"status": "CONFIRMED" if i == 0 else "FALSE_POSITIVE"}
                    for i in range(size)
                },
            )
        group = next(g for g in self.summary_response().json()["modules"] if g["module"] == "code")
        self.assertEqual((group["metrics"]["valid"], group["metrics"]["invalid"]), (2, 8))
        prior = self.read("code", identity)
        prior["state"]["note"] = "范围注释"
        prior = self.write("code", identity, prior)
        with self.factory() as db:
            row = db.get(CodeAnalysisTask, identity)
            row.report = {"findings": [{"key": "NEW", "title": "更新报告"}]}
            db.commit()
        changed = self.read("code", identity)
        self.assertTrue(changed["stale"])
        self.assertEqual(changed["metrics"]["valid"], 0)
        self.assertEqual(len(changed["history"]), 1)
        self.write("code", identity, prior, 409)

    def test_pending_failed_ignored_and_reused_generation_are_not_all_recognized(self):
        identity = self.seed("generate", 5)
        self.set_handling(
            "generate",
            identity,
            {
                "C0": [{"status": "待审阅", "evidenceChecked": True}],
                "C1": [{"status": "需人工确认", "evidenceChecked": False}],
                "C2": [{"status": "已忽略"}],
                "C3": [{"status": "已应用", "evidenceChecked": True}],
                "C4": [{"status": "已复用"}],
            },
        )
        m = self.read("generate", identity)["metrics"]
        self.assertEqual(
            (
                m["valid"],
                m["dismissed"],
                m["invalid"],
                m["needs_review"],
                m["unreviewed"],
                m["adopted"],
            ),
            (2, 1, 0, 1, 1, 1),
        )
        self.assertEqual(m["false_positives"], 0)
        identity = self.seed("changes", 1)
        self.set_handling("changes", identity, {"G1": {"status": "DEFERRED"}})
        self.assertEqual(self.read("changes", identity)["metrics"]["regression_reviewed"], 0)
        self.set_handling("changes", identity, {"G1": {"status": "REJECTED"}})
        m = self.read("changes", identity)["metrics"]
        self.assertEqual((m["regression_reviewed"], m["regression_usable"], m["total"]), (1, 0, 1))

    def test_generation_review_uses_fixed_original_design_and_patch_not_human_draft(self):
        identity = self.seed("generate", 1)
        with self.factory() as db:
            batch = db.scalar(
                select(CaseGenerationBatch).where(CaseGenerationBatch.run_id == identity)
            )
            batch.input_snapshot = {
                "cases": [
                    {
                        "case_ref": "case-1",
                        "design": {
                            "title": "原始标题",
                            "steps": "固定操作步骤",
                            "expected": "旧预期",
                        },
                    }
                ]
            }
            batch.report = {
                "suggestions": [
                    {
                        "key": "C0",
                        "kind": "UPDATE",
                        "case_ref": "case-1",
                        "changes": [
                            {"field": "expected", "before": "旧预期", "after": "AI原始新预期"}
                        ],
                    }
                ]
            }
            run = db.get(CaseGenerationRun, identity)
            run.handling = {
                "suggestions": {"C0": [{"status": "已应用", "draft": {"expected": "后续人工修订"}}]}
            }
            db.commit()
        data = self.read("generate", identity)
        self.assertEqual(data["items"][0]["title"], "原始标题")
        self.assertIn("固定操作步骤", data["items"][0]["description"])
        self.assertIn("AI原始新预期", data["items"][0]["description"])
        self.assertNotIn("后续人工修订", data["items"][0]["description"])
        self.assertEqual(data["metrics"]["adopted"], 1)
        self.assertEqual(data["metrics"]["valid"], 1)

    def test_single_module_failure_does_not_hide_other_metrics(self):
        original = sources.records

        def read(module, *args, **kwargs):
            if module == "code":
                raise ValueError("PRIVATE_BODY")
            return original(module, *args, **kwargs)

        with patch.object(sources, "records", read):
            response = self.summary_response()
            self.assertEqual(response.status_code, 200, response.text)
            groups = response.json()["modules"]
            self.assertFalse(next(g for g in groups if g["module"] == "code")["available"])
            self.assertTrue(next(g for g in groups if g["module"] == "generate")["available"])
            self.assertNotIn("PRIVATE_BODY", response.text)
