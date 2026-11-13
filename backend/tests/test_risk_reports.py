import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_auth
import test_requirements
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import RequirementRiskReport
from app.modules.requirements.risk_schemas import (
    AnalysisInput,
    Report,
    normalize_comparison_text,
    normalize_function_risks,
    validate_report,
)
from app.modules.requirements.risk_service import json_object, parse

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/requirement-analysis/examples"


def sample():
    return (
        json.loads((EXAMPLES / "input.json").read_text(encoding="utf-8")),
        json.loads((EXAMPLES / "output.json").read_text(encoding="utf-8")),
    )


class RiskValidationTests(unittest.TestCase):
    def test_ai_semantic_warnings_do_not_weaken_structural_references(self):
        context, report = sample()
        candidate = copy.deepcopy(report)
        candidate["risks"][0]["evidence"][0]["excerpt"] = "invented"
        candidate["coverage"][0]["segments"][0]["function_keys"] = []
        with self.assertRaises(AppError):
            validate_report(
                Report.model_validate(candidate), AnalysisInput.model_validate(context), 1
            )
        warnings = []
        validate_report(
            Report.model_validate(candidate), AnalysisInput.model_validate(context), 1, warnings
        )
        self.assertIn("evidence_excerpt_mismatch", {w["code"] for w in warnings})
        self.assertIn("invalid_coverage", {w["code"] for w in warnings})
        unknown = copy.deepcopy(candidate)
        unknown["risks"][0]["evidence"][0]["segment_id"] = "missing"
        with self.assertRaises(AppError):
            validate_report(
                Report.model_validate(unknown), AnalysisInput.model_validate(context), 1, []
            )
        self.assertEqual(report["risks"][0]["evidence"][0]["excerpt"], "订单列表支持按订单号搜索。")

    def test_ai_comparison_lists_join_without_changing_import_contract(self):
        _, report = sample()
        candidate = copy.deepcopy(report)
        candidate["risks"][0]["source_comparison"] = {
            "relation": "EXPRESSION_DIFFERENCE",
            "sides": [
                {"statement": "需求", "evidence": candidate["risks"][0]["evidence"]},
                {"statement": "原型", "evidence": candidate["risks"][0]["evidence"]},
            ],
            "known_facts": ["已知条件", "已知结果"],
            "unknowns": ["待确认规则"],
        }
        with self.assertRaises(ValueError):
            Report.model_validate(candidate)
        normalized, corrections = normalize_comparison_text(candidate)
        self.assertEqual(
            normalized["risks"][0]["source_comparison"]["known_facts"], "已知条件\n已知结果"
        )
        self.assertEqual(normalized["risks"][0]["source_comparison"]["unknowns"], "待确认规则")
        self.assertEqual(len(corrections), 2)
        self.assertIsInstance(candidate["risks"][0]["source_comparison"]["known_facts"], list)
        Report.model_validate(normalized)
        for invalid in ([], [""], [{"invented": "fact"}]):
            changed = copy.deepcopy(candidate)
            changed["risks"][0]["source_comparison"]["known_facts"] = invalid
            repaired, _ = normalize_comparison_text(changed)
            with self.assertRaises(ValueError):
                Report.model_validate(repaired)

    def test_ai_function_index_is_derived_only_from_valid_risk_owners(self):
        context, report = sample()
        original = copy.deepcopy(report)
        valid, corrections = normalize_function_risks(Report.model_validate(report))
        self.assertEqual(corrections, [])
        validate_report(valid, AnalysisInput.model_validate(context), 1)
        missing_reverse = copy.deepcopy(report)
        missing_reverse["functions"][0]["risk_keys"] = []
        normalized, fixes = normalize_function_risks(Report.model_validate(missing_reverse))
        self.assertEqual(normalized.functions[0].risk_keys, ["R1"])
        self.assertEqual(len(fixes), 1)
        validate_report(normalized, AnalysisInput.model_validate(context), 1)
        extra_reverse = copy.deepcopy(report)
        extra_reverse["functions"].append(
            {**copy.deepcopy(report["functions"][0]), "key": "F2", "risk_keys": ["R1"]}
        )
        normalized, fixes = normalize_function_risks(Report.model_validate(extra_reverse))
        self.assertEqual(normalized.functions[1].risk_keys, [])
        self.assertEqual(fixes[0]["function_key"], "F2")
        changed = copy.deepcopy(report)
        changed["functions"][0]["risk_keys"] = ["missing"]
        with self.assertRaises(AppError):
            normalize_function_risks(Report.model_validate(changed))
        changed["functions"][0]["risk_keys"] = ["R1", "R1"]
        with self.assertRaises(AppError):
            normalize_function_risks(Report.model_validate(changed))
        changed = copy.deepcopy(report)
        changed["functions"][0]["risk_keys"] = []
        changed["risks"][0]["evidence"][0]["excerpt"] = "fabricated"
        normalized, _ = normalize_function_risks(Report.model_validate(changed))
        with self.assertRaises(AppError):
            validate_report(normalized, AnalysisInput.model_validate(context), 1)
        self.assertEqual(report, original)

    def test_input_evidence_coverage_and_version_validation(self):
        context, report = sample()
        validate_report(Report.model_validate(report), AnalysisInput.model_validate(context), 1)
        changes = [
            lambda v: v.update(contract_version=2),
            lambda v: v.update(request_id="different"),
            lambda v: v["risks"][0]["evidence"][0].update(excerpt="invented"),
            lambda v: v["risks"][0]["evidence"][0].update(location="invented"),
            lambda v: v["risks"][0]["evidence"][0].update(segment_id="unknown"),
            lambda v: v["functions"][0].update(risk_keys=[]),
            lambda v: v["coverage"][0]["segments"].clear(),
            lambda v: v["risks"].append(copy.deepcopy(v["risks"][0])),
            lambda v: v["risks"][0].update(status="RESOLVED"),
            lambda v: v["risks"][0].update(checked_scope=[]),
        ]
        for change in changes:
            value = copy.deepcopy(report)
            change(value)
            with self.assertRaises((AppError, ValueError)):
                validate_report(
                    Report.model_validate(value), AnalysisInput.model_validate(context), 1
                )
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"):
            with self.assertRaises(AppError):
                json_object(raw)
        bad = {**report, "PRIVATE_UNKNOWN_FIELD": "PRIVATE_VALUE"}
        with self.assertRaises(AppError) as error:
            parse(Report, bad, "report")
        self.assertNotIn("PRIVATE", error.exception.detail)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class RiskReportDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    tearDown = test_requirements.RequirementDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login

    def setUp(self):
        test_requirements.RequirementDatabaseTests.setUp(self)
        self.api = self.base + "/risk-reports"
        self.context, self.report = sample()
        response = self.client.post(
            self.docs + "/upload",
            headers=test_auth.ORIGIN,
            params={"filename": "需求.txt", "upload_id": str(uuid4()), "revision": 0},
            content=self.context["materials"][0]["segments"][0]["text"].encode(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.doc = response.json()["documents"][0]
        self.payload = {
            "title": "查询风险报告",
            "input_filename": "input.json",
            "report_filename": "risk-report.json",
            "input_json": json.dumps(self.context),
            "report_json": json.dumps(self.report),
            "bindings": [
                {
                    "source_id": "D1",
                    "document_id": self.doc["id"],
                    "version_id": self.doc["current"]["id"],
                }
            ],
        }

    def upload(self, payload=None):
        return self.client.post(
            self.api + "/import", json=payload or self.payload, headers=test_auth.ORIGIN
        )

    def test_import_and_handling_are_atomic_shared_idempotent_and_no_ai(self):
        with (
            patch("app.integrations.responses.analyze") as model,
            patch("app.integrations.github.github_get") as github,
        ):
            response = self.upload()
            self.assertEqual(response.status_code, 201, response.text)
            result = response.json()
            model.assert_not_called()
            github.assert_not_called()
        self.assertEqual(result["report"], self.report)
        self.assertEqual(result["input"], self.context)
        self.assertEqual(result["handling"], [])
        self.assertEqual(result["bindings"][0]["version"]["id"], self.doc["current"]["id"])
        url = self.api + f"/{result['id']}"
        self.assertEqual(self.client.get(self.api).json()["items"][0]["risks"], 1)
        self.assertEqual(self.client.get(url + "/export?kind=input").json(), self.context)
        self.assertIn(
            "attachment",
            self.client.get(url + "/export?kind=report").headers["content-disposition"],
        )
        edit = {"risk_key": "R1", "revision": result["revision"], "status": "RESOLVED", "note": ""}
        self.assertEqual(
            self.client.post(url + "/handling", json=edit, headers=test_auth.ORIGIN).status_code,
            422,
        )
        edit["note"] = "人工已核对补充规则，确定精确匹配。"
        saved = self.client.post(url + "/handling", json=edit, headers=test_auth.ORIGIN)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["report"], self.report)
        self.assertEqual(saved.json()["handling"][0]["history"][0]["actor_id"], self.member_id)
        self.assertEqual(
            self.client.post(url + "/handling", json=edit, headers=test_auth.ORIGIN).status_code,
            409,
        )
        edit["revision"] = saved.json()["revision"]
        self.assertEqual(
            self.client.post(url + "/handling", json=edit, headers=test_auth.ORIGIN).json()[
                "revision"
            ],
            edit["revision"],
        )
        duplicate = self.upload().json()
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["id"], result["id"])
        self.assertEqual(duplicate["handling"][0]["status"], "RESOLVED")
        self.login(self.admin_name)
        self.assertEqual(self.client.get(url).json()["handling"][0]["status"], "RESOLVED")
        info = self.client.get(self.docs + f"/{self.doc['id']}/deletion").json()
        self.assertEqual(info["risk_report_references"], 1)
        self.client.post(
            self.docs + f"/{self.doc['id']}/delete",
            json={"revision": info["revision"], "confirmed": True},
            headers=test_auth.ORIGIN,
        )
        self.assertTrue(self.client.get(url).json()["bindings"][0]["deleted"])
        self.assertEqual(
            self.client.get(self.docs + f"/versions/{self.doc['current']['id']}/file").status_code,
            200,
        )

    def test_invalid_files_and_foreign_or_missing_bindings_never_create_reports(self):
        for mutate in [
            lambda p: p.update(report_json=p["input_json"]),
            lambda p: p.update(bindings=[]),
            lambda p: p["bindings"][0].update(version_id=None),
            lambda p: p["bindings"][0].update(document_id=987654321),
            lambda p: p.update(input_filename="../input.json"),
        ]:
            payload = copy.deepcopy(self.payload)
            mutate(payload)
            response = self.upload(payload)
            self.assertEqual(response.status_code, 422, response.text)
        wrong = copy.deepcopy(self.context)
        wrong["project_id"] = self.other
        self.assertEqual(
            self.upload({**self.payload, "input_json": json.dumps(wrong)}).status_code, 422
        )
        self.assertEqual(self.client.get(self.api).json()["items"], [])
        result = self.upload().json()
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.other}/requirements/risk-reports/{result['id']}"
            ).status_code,
            404,
        )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            db.execute(
                text("DELETE FROM project_member WHERE project_id=:p AND user_id=:u"),
                {"p": self.project, "u": self.member_id},
            )
            db.commit()
        self.assertEqual(self.client.get(self.api).status_code, 404)
        self.assertEqual(self.client.get(self.api + f"/{result['id']}").status_code, 404)

    def test_same_input_result_cannot_silently_rebind_and_new_result_preserves_old(self):
        original = self.upload().json()
        other_file = self.client.post(
            self.docs + "/upload",
            headers=test_auth.ORIGIN,
            params={
                "filename": "另一份需求.txt",
                "upload_id": str(uuid4()),
                "revision": self.client.get(self.docs).json()["revision"],
            },
            content=b"Other requirement content",
        )
        self.assertEqual(other_file.status_code, 201, other_file.text)
        other = next(d for d in other_file.json()["documents"] if d["id"] != self.doc["id"])
        payload = {
            **self.payload,
            "bindings": [
                {
                    "source_id": "D1",
                    "document_id": other["id"],
                    "version_id": other["current"]["id"],
                }
            ],
        }
        self.assertEqual(self.upload(payload).status_code, 409)
        revised = copy.deepcopy(self.report)
        revised["summary"]["conclusion"] += "补充后的独立报告。"
        second = self.upload({**self.payload, "report_json": json.dumps(revised)})
        self.assertEqual(second.status_code, 201, second.text)
        self.assertNotEqual(second.json()["id"], original["id"])
        self.assertEqual(
            self.client.get(self.api + f"/{original['id']}").json()["report"], self.report
        )
        with Session(self.connection) as db:
            self.assertEqual(
                len(
                    list(
                        db.scalars(
                            select(RequirementRiskReport).where(
                                RequirementRiskReport.project_id == self.project
                            )
                        )
                    )
                ),
                2,
            )
        self.assertEqual(self.client.get(self.base + "/analyses").status_code, 404)
