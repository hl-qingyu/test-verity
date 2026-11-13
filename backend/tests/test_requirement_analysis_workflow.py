import copy
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_auth
import test_risk_reports
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import (
    AIConnection,
    RequirementChatTurn,
    RequirementManualRisk,
    RequirementRiskAnalysis,
    SourceDocument,
    UserAccount,
)
from app.modules.prototypes import service as prototypes
from app.modules.requirements import (
    artifacts,
    chat_service,
    risk_analysis_execution,
    risk_analysis_service,
)
from app.modules.skills import files as skill_files


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class RequirementAnalysisWorkflowTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    tearDown = test_risk_reports.RiskReportDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login
    upload = test_risk_reports.RiskReportDatabaseTests.upload

    def setUp(self):
        test_risk_reports.RiskReportDatabaseTests.setUp(self)
        self.candidate_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.candidate_directory.cleanup)
        candidate_patch = patch.object(
            artifacts,
            "candidate_path",
            side_effect=lambda task_id: Path(self.candidate_directory.name)
            / f"requirement-analysis-{task_id}-ai-candidate.txt",
        )
        candidate_patch.start()
        self.addCleanup(candidate_patch.stop)

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def configuration(self, actor, db, version=None, **kwargs):
        if isinstance(version, dict):
            version = version.get("version")
        if version is not None:
            self.assertEqual(version, 1)
        return {
            "name": "个人模型",
            "model": "configured-model",
            "version": 1,
            "base_url": "https://api.openai.com/v1",
            "reasoning_effort": "default",
        }, "SECRET"

    def add_ai(self):
        with self.factory() as db:
            db.add(
                AIConnection(
                    id=self.member_id,
                    owner_id=self.member_id,
                    name="个人模型",
                    base_url="https://api.openai.com/v1",
                    model="configured-model",
                    encrypted_key="CIPHER",
                    version=1,
                    updated_by=self.member_id,
                )
            )
            db.commit()

    def model_answer(
        self,
        content,
        *,
        missing_reverse=False,
        invalid_evidence=False,
        comparison_list=False,
        unknown_function=False,
    ):
        context = json.loads(content[0]["text"])
        material = context["materials"][0]
        segment = material["segments"][0]
        report = copy.deepcopy(test_risk_reports.sample()[1])
        report["request_id"] = context["request_id"]
        report["functions"][0]["evidence"][0].update(
            source_id=material["source_id"],
            segment_id=segment["segment_id"],
            location=segment["location"],
            excerpt=segment["text"][:10],
        )
        report["risks"][0]["evidence"][0].update(report["functions"][0]["evidence"][0])
        report["risks"][0]["checked_scope"][0].update(
            source_id=material["source_id"], segment_ids=[segment["segment_id"]]
        )
        report["coverage"][0]["source_id"] = material["source_id"]
        report["coverage"][0]["segments"] = [
            {**report["coverage"][0]["segments"][0], "segment_id": item["segment_id"]}
            for item in material["segments"]
        ]
        if missing_reverse:
            report["functions"][0]["risk_keys"] = []
        if comparison_list:
            report["risks"][0]["type"] = "SOURCE_DIFFERENCE"
            report["risks"][0]["source_comparison"] = {
                "relation": "EXPRESSION_DIFFERENCE",
                "sides": [
                    {"statement": "需求", "evidence": report["risks"][0]["evidence"]},
                    {"statement": "原型", "evidence": report["risks"][0]["evidence"]},
                ],
                "known_facts": ["已知条件", "已知结果"],
                "unknowns": ["待确认项"],
            }
        if invalid_evidence:
            report["risks"][0]["evidence"][0]["excerpt"] = "fabricated"
        if unknown_function:
            report["risks"][0]["function_keys"] = ["F999"]
        return json.dumps(report, ensure_ascii=False)

    def queue_risk(self):
        self.add_ai()
        payload = {
            "request_id": str(uuid4()),
            "title": "关联校验",
            "focus": "",
            "selections": [
                {"document_id": self.doc["id"], "version_id": self.doc["current"]["id"]}
            ],
        }
        with patch.object(
            risk_analysis_service, "analysis_configuration", side_effect=self.configuration
        ):
            queued = self.client.post(
                self.base + "/risk-analyses", json=payload, headers=test_auth.ORIGIN
            )
        self.assertEqual(queued.status_code, 202, queued.text)
        with self.factory() as db:
            self.assertEqual(risk_analysis_execution.claim(db), queued.json()["id"])
        return queued.json()["id"]

    def test_worker_keeps_raw_candidate_and_normalizes_reverse_index(self):
        task_id = self.queue_risk()
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch(
                "app.integrations.responses.analyze",
                side_effect=lambda *args, **kwargs: self.model_answer(
                    args[5], missing_reverse=True, comparison_list=True
                ),
            ) as upstream,
        ):
            risk_analysis_execution.execute(task_id, self.factory)
            upstream.assert_called_once()
        task = self.client.get(self.base + "/risk-analyses").json()["items"][0]
        self.assertEqual(task["status"], "COMPLETED")
        self.assertTrue(task["candidate_available"])
        self.assertEqual(task["function_risk_corrections"][0]["after"], ["R1"])
        with self.factory() as db:
            stored = db.get(RequirementRiskAnalysis, task_id)
            self.assertEqual(len(stored.context["comparison_text_corrections"]), 2)
        raw = json.loads(artifacts.candidate_path(task_id).read_text(encoding="utf-8"))
        self.assertEqual(raw["functions"][0]["risk_keys"], [])
        self.assertEqual(
            raw["risks"][0]["source_comparison"]["known_facts"], ["已知条件", "已知结果"]
        )
        report = self.client.get(self.api + f"/{task['report_id']}").json()["report"]
        self.assertEqual(report["functions"][0]["risk_keys"], ["R1"])
        self.assertEqual(
            report["risks"][0]["source_comparison"]["known_facts"], "已知条件\n已知结果"
        )
        candidate = self.client.get(self.base + f"/risk-analyses/{task_id}/candidate")
        self.assertEqual(candidate.status_code, 200)
        self.assertEqual(json.loads(candidate.text), raw)
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.other}/requirements/risk-analyses/{task_id}/candidate"
            ).status_code,
            404,
        )

    def test_unmatched_evidence_is_saved_for_human_review(self):
        task_id = self.queue_risk()
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch(
                "app.integrations.responses.analyze",
                side_effect=lambda *args, **kwargs: self.model_answer(
                    args[5], missing_reverse=True, invalid_evidence=True, comparison_list=True
                ),
            ),
        ):
            risk_analysis_execution.execute(task_id, self.factory)
        task = self.client.get(self.base + "/risk-analyses").json()["items"][0]
        self.assertEqual(task["status"], "COMPLETED")
        self.assertIsNotNone(task["report_id"])
        report = self.client.get(self.api + f"/{task['report_id']}").json()
        self.assertTrue(
            any(w["code"] == "evidence_excerpt_mismatch" for w in report["review_warnings"])
        )
        self.assertEqual(report["handling"], [])
        catalog = self.client.get(self.base + "/risk-reports-catalog").json()
        self.assertGreater(catalog["reports"][0]["review_warning_count"], 0)
        self.assertEqual(catalog["items"][0]["status"], "PENDING")
        self.assertTrue(catalog["items"][0]["review_warnings"])
        self.assertIn("待人工核对", self.client.get(self.base + "/risk-reports-export").text)
        self.assertEqual(
            self.client.get(self.base + f"/risk-analyses/{task_id}/candidate").status_code, 200
        )
        with patch.object(chat_service, "analysis_configuration", side_effect=self.configuration):
            message = self.client.post(
                self.api + f"/{task['report_id']}/chat",
                json={
                    "request_id": str(uuid4()),
                    "question": "需要核对哪些证据？",
                    "last_turn_id": 0,
                },
                headers=test_auth.ORIGIN,
            )
        self.assertEqual(message.status_code, 202, message.text)
        with self.factory() as db:
            turn = db.get(RequirementChatTurn, message.json()["id"])
            self.assertTrue(turn.context["review_warnings"])

    def test_unknown_function_stays_failed_with_candidate_and_no_paid_recheck(self):
        task_id = self.queue_risk()
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch(
                "app.integrations.responses.analyze",
                side_effect=lambda *args, **kwargs: self.model_answer(
                    args[5], unknown_function=True
                ),
            ),
        ):
            risk_analysis_execution.execute(task_id, self.factory)
        task = self.client.get(self.base + "/risk-analyses").json()["items"][0]
        self.assertEqual(task["status"], "FAILED")
        self.assertIn("unknown_reference", task["error_code"])
        self.assertIsNone(task["report_id"])
        self.assertTrue(task["can_revalidate"])
        self.login()
        self.assertEqual(
            self.client.post(
                self.base + f"/risk-analyses/{task_id}/revalidate", headers=test_auth.ORIGIN
            ).status_code,
            403,
        )
        self.login(self.member_name)
        with patch("app.integrations.responses.analyze") as upstream:
            response = self.client.post(
                self.base + f"/risk-analyses/{task_id}/revalidate", headers=test_auth.ORIGIN
            )
            upstream.assert_not_called()
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            self.client.get(self.base + "/risk-analyses").json()["items"][0]["status"], "FAILED"
        )

    def test_saved_candidate_can_be_revalidated_without_ai(self):
        task_id = self.queue_risk()
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch.object(
                risk_analysis_execution.risk_schemas,
                "normalize_function_risks",
                side_effect=lambda output: (output, []),
            ),
            patch(
                "app.integrations.responses.analyze",
                side_effect=lambda *args, **kwargs: self.model_answer(
                    args[5], missing_reverse=True
                ),
            ),
        ):
            risk_analysis_execution.execute(task_id, self.factory)
        self.assertEqual(
            self.client.get(self.base + "/risk-analyses").json()["items"][0]["status"], "FAILED"
        )
        with patch("app.integrations.responses.analyze") as upstream:
            response = self.client.post(
                self.base + f"/risk-analyses/{task_id}/revalidate", headers=test_auth.ORIGIN
            )
            upstream.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "COMPLETED")
        self.assertEqual(len(response.json()["function_risk_corrections"]), 1)
        self.assertEqual(
            json.loads(artifacts.candidate_path(task_id).read_text(encoding="utf-8"))["functions"][
                0
            ]["risk_keys"],
            [],
        )
        again = self.client.post(
            self.base + f"/risk-analyses/{task_id}/revalidate", headers=test_auth.ORIGIN
        )
        self.assertEqual(again.json()["report_id"], response.json()["report_id"])

    def test_upstream_failure_has_no_candidate_or_report(self):
        task_id = self.queue_risk()
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch(
                "app.integrations.responses.analyze", side_effect=RuntimeError("upstream failed")
            ),
        ):
            risk_analysis_execution.execute(task_id, self.factory)
        task = self.client.get(self.base + "/risk-analyses").json()["items"][0]
        self.assertEqual(task["status"], "FAILED")
        self.assertFalse(task["candidate_available"])
        self.assertIsNone(task["report_id"])
        self.assertEqual(
            self.client.get(self.base + f"/risk-analyses/{task_id}/candidate").status_code, 404
        )

    def test_retry_uses_only_original_selection_contract(self):
        task_id = self.queue_risk()
        with self.factory() as db:
            original = db.get(RequirementRiskAnalysis, task_id)
            selections = original.selections
            original.status = "FAILED"
            db.commit()
        payload = {
            "request_id": str(uuid4()),
            "title": "再次分析",
            "focus": "",
            "selections": [{**selections[0], "source_id": ""}],
            "retry_of": task_id,
        }
        endpoint = self.base + "/risk-analyses"
        self.assertEqual(
            self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN).status_code, 422
        )
        payload["selections"] = selections
        with patch.object(
            risk_analysis_service, "analysis_configuration", side_effect=self.configuration
        ):
            result = self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN)
        self.assertEqual(result.status_code, 202, result.text)
        self.assertEqual(result.json()["retry_of"], task_id)
        self.assertEqual(result.json()["selections"], selections)

    def test_link_selection_reads_only_selected_page_into_risk_input(self):
        self.add_ai()
        url = "https://prototype.geekuat.com/p/Test123/"
        with self.factory() as db:
            source = SourceDocument(
                project_id=self.project,
                purpose="PROTOTYPE",
                kind="LINK",
                name="原型",
                url=url,
                current_version=1,
            )
            db.add(source)
            db.commit()
            source_id = source.id
        payload = {
            "request_id": str(uuid4()),
            "title": "原型风险",
            "selections": [
                {
                    "document_id": source_id,
                    "version_id": None,
                    "paths": ["page-2.html"],
                    "snapshot": "a" * 64,
                    "url": url,
                }
            ],
        }
        with patch.object(
            risk_analysis_service, "analysis_configuration", side_effect=self.configuration
        ):
            queued = self.client.post(
                self.base + "/risk-analyses", json=payload, headers=test_auth.ORIGIN
            )
        self.assertEqual(queued.status_code, 202, queued.text)
        with (
            self.factory() as db,
            patch.object(
                prototypes,
                "link_pages",
                return_value={
                    "snapshot_ref": "b" * 64,
                    "segments": [{"location": "首页 · 原型说明", "text": "订单规则"}],
                },
            ) as reader,
        ):
            task = db.get(RequirementRiskAnalysis, queued.json()["id"])
            actor = db.get(UserAccount, self.member_id)
            input_data, _, _ = risk_analysis_execution.prepare(task, actor, db)
            self.assertEqual(input_data["materials"][0]["segments"][0]["text"], "订单规则")
            self.assertEqual(input_data["materials"][0]["read_state"], "PARTIAL")
            reader.assert_called_once()
        with self.factory() as db:
            task = db.get(RequirementRiskAnalysis, queued.json()["id"])
            task.status = "FAILED"
            db.commit()
        with patch.object(
            risk_analysis_service, "analysis_configuration", side_effect=self.configuration
        ):
            retried = self.client.post(
                self.base + "/risk-analyses",
                json={**payload, "request_id": str(uuid4()), "retry_of": queued.json()["id"]},
                headers=test_auth.ORIGIN,
            )
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(retried.json()["selections"][0]["paths"], ["page-2.html"])

    def test_retry_chain_reuses_frozen_link_input_without_external_fetch(self):
        self.add_ai()
        url = "https://prototype.geekuat.com/p/Test123/"
        with self.factory() as db:
            source = SourceDocument(
                project_id=self.project,
                purpose="PROTOTYPE",
                kind="LINK",
                name="原型",
                url=url,
                current_version=1,
            )
            db.add(source)
            db.commit()
            source_id = source.id
        selection = {
            "document_id": source_id,
            "version_id": None,
            "paths": ["page-2.html"],
            "snapshot": "a" * 64,
            "url": url,
        }
        endpoint = self.base + "/risk-analyses"

        def queue(retry_of=None):
            with patch.object(
                risk_analysis_service, "analysis_configuration", side_effect=self.configuration
            ):
                result = self.client.post(
                    endpoint,
                    json={
                        "request_id": str(uuid4()),
                        "title": "原型重试",
                        "selections": [selection],
                        "retry_of": retry_of,
                    },
                    headers=test_auth.ORIGIN,
                )
            self.assertEqual(result.status_code, 202, result.text)
            return result.json()["id"]

        first = queue()
        with self.factory() as db:
            self.assertEqual(risk_analysis_execution.claim(db), first)
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch.object(
                prototypes,
                "link_pages",
                return_value={
                    "snapshot_ref": "b" * 64,
                    "segments": [{"location": "门店 / 订单 · HTML原文", "text": "<h1>订单</h1>"}],
                },
            ) as fetched,
            patch(
                "app.integrations.responses.analyze", side_effect=RuntimeError("synthetic failure")
            ),
        ):
            risk_analysis_execution.execute(first, self.factory)
            fetched.assert_called_once()
        with self.factory() as db:
            original = db.get(RequirementRiskAnalysis, first)
            self.assertEqual(original.status, "FAILED")
            self.assertEqual(
                original.context["input"]["materials"][0]["segments"][0]["text"], "<h1>订单</h1>"
            )

        # Simulate an older retry that failed while re-fetching and has no prepared input.
        second = queue(first)
        with self.factory() as db:
            row = db.get(RequirementRiskAnalysis, second)
            row.context, row.status = {}, "FAILED"
            db.commit()
        third = queue(second)
        with self.factory() as db:
            task = db.get(RequirementRiskAnalysis, third)
            self.assertEqual(
                task.context["input"]["materials"], original.context["input"]["materials"]
            )
            self.assertEqual(risk_analysis_execution.claim(db), third)

        sent = []

        def model(*args, **kwargs):
            sent.append(json.loads(args[5][0]["text"]))
            raise RuntimeError("synthetic failure")

        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch.object(
                prototypes, "link_pages", side_effect=AssertionError("unexpected link GET")
            ) as fetched,
            patch("app.integrations.responses.analyze", side_effect=model),
        ):
            risk_analysis_execution.execute(third, self.factory)
            fetched.assert_not_called()
        self.assertEqual(
            sent[0]["request_id"], self.client.get(endpoint).json()["items"][0]["request_id"]
        )
        self.assertEqual(sent[0]["revision"], third)
        self.assertEqual(sent[0]["materials"][0]["segments"][0]["text"], "<h1>订单</h1>")

        fourth = queue(third)
        with self.factory() as db:
            db.get(SourceDocument, source_id).deleted_at = datetime.now(UTC)
            db.commit()
            self.assertEqual(risk_analysis_execution.claim(db), fourth)
        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch("app.integrations.responses.analyze") as upstream,
        ):
            risk_analysis_execution.execute(fourth, self.factory)
            upstream.assert_not_called()
        self.assertEqual(
            self.client.get(endpoint).json()["items"][0]["error_code"], "risk_source_unavailable"
        )

    def test_first_analysis_runs_once_and_creates_catalog_report(self):
        self.add_ai()
        request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "title": "订单取消风险分析",
            "focus": "取消规则",
            "selections": [
                {"document_id": self.doc["id"], "version_id": self.doc["current"]["id"]}
            ],
            "retry_of": None,
        }
        endpoint = self.base + "/risk-analyses"
        with patch.object(
            risk_analysis_service, "analysis_configuration", side_effect=self.configuration
        ):
            queued = self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN)
            self.assertEqual(queued.status_code, 202, queued.text)
            self.assertEqual(
                self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN).json()["id"],
                queued.json()["id"],
            )
        task_id = queued.json()["id"]
        with self.factory() as db:
            fixed_skill = copy.deepcopy(db.get(RequirementRiskAnalysis, task_id).context["skill"])
            self.assertEqual(risk_analysis_execution.claim(db), task_id)

        def answer(base, model, key, effort, instructions, content, **kwargs):
            self.assertEqual(instructions, fixed_skill["instructions"])
            context = json.loads(content[0]["text"])
            material = context["materials"][0]
            segment = material["segments"][0]
            evidence = {
                "source_id": material["source_id"],
                "segment_id": segment["segment_id"],
                "location": segment["location"],
                "excerpt": segment["text"][:10],
                "observation": "该片段包含订单取消规则。",
            }
            return json.dumps(
                {
                    "contract_version": 3,
                    "request_id": context["request_id"],
                    "outcome": "COMPLETE",
                    "summary": {
                        "assessment": "NEEDS_CLARIFICATION",
                        "conclusion": "取消条件仍需确认。",
                        "priority_risk_keys": ["R1"],
                    },
                    "functions": [
                        {
                            "key": "F1",
                            "module": "订单",
                            "name": "取消订单",
                            "scope": "检查取消规则",
                            "evidence": [evidence],
                            "risk_keys": ["R1"],
                        }
                    ],
                    "risks": [
                        {
                            "key": "R1",
                            "function_keys": ["F1"],
                            "title": "取消条件不明确",
                            "type": "RULE_GAP",
                            "severity": "MEDIUM",
                            "severity_reason": "影响状态判断。",
                            "basis": "EXPLICIT",
                            "description": "取消条件仍需补充。",
                            "evidence": [evidence],
                            "checked_scope": [],
                            "impact": "可能造成实现与验收不一致。",
                            "questions": ["哪些状态允许取消？"],
                            "improvement": {
                                "proposal": "补充状态清单。",
                                "rationale": "便于实现和验收。",
                                "tradeoffs": "需产品确认。",
                                "requires_confirmation": True,
                            },
                            "source_comparison": None,
                        }
                    ],
                    "optional_suggestions": [],
                    "coverage": [
                        {
                            "source_id": material["source_id"],
                            "segments": [
                                {
                                    "segment_id": item["segment_id"],
                                    "disposition": "REVIEWED",
                                    "function_keys": ["F1"],
                                    "risk_keys": ["R1"],
                                    "reason": "已检查取消规则。",
                                }
                                for item in material["segments"]
                            ],
                            "limitation": "",
                        }
                    ],
                    "limitations": [],
                },
                ensure_ascii=False,
            )

        with (
            patch.object(
                risk_analysis_execution, "analysis_configuration", side_effect=self.configuration
            ),
            patch("app.integrations.responses.analyze", side_effect=answer) as upstream,
            patch.object(
                skill_files, "bundle", side_effect=AssertionError("must use queued Skill snapshot")
            ),
        ):
            risk_analysis_execution.execute(task_id, self.factory)
            upstream.assert_called_once()
        task = self.client.get(endpoint).json()["items"][0]
        self.assertEqual(task["status"], "COMPLETED")
        self.assertIsNotNone(task["report_id"])
        catalog = self.client.get(self.base + "/risk-reports-catalog").json()
        self.assertEqual((catalog["overview"]["reports"], catalog["total"]), (1, 1))

    def test_function_chat_manual_risk_and_handling_are_isolated_and_idempotent(self):
        self.add_ai()
        report = self.upload().json()
        function_key = report["report"]["functions"][0]["key"]
        risk = report["report"]["risks"][0]
        chat = self.api + f"/{report['id']}/chat"
        with patch.object(chat_service, "analysis_configuration", side_effect=self.configuration):
            queued = self.client.post(
                chat + f"?function_key={function_key}",
                json={
                    "request_id": str(uuid4()),
                    "question": "这个问题如何补充？",
                    "last_turn_id": 0,
                    "risk_key": risk["key"],
                },
                headers=test_auth.ORIGIN,
            )
        self.assertEqual(queued.status_code, 202, queued.text)
        self.assertEqual(self.client.get(chat).json()["items"], [])
        self.assertEqual(
            self.client.get(chat + f"?function_key={function_key}").json()["items"][0]["risk_key"],
            risk["key"],
        )
        with self.factory() as db:
            turn = db.get(RequirementChatTurn, queued.json()["id"])
            turn.answer, turn.status = "请补充明确规则。", "COMPLETED"
            db.commit()
            turn_id = turn.id
        request_id = str(uuid4())
        payload = {
            "request_id": request_id,
            "message_turn_id": turn_id,
            "function_key": function_key,
            "title": "人工确认的新风险",
            "severity": "LOW",
            "risk_type": "AMBIGUITY",
            "description": "原文表达仍存在歧义。",
            "evidence": [risk["evidence"][0]],
            "impact": "不同成员可能采用不同理解。",
            "questions": ["最终采用哪种表述？"],
            "improvement": {
                "proposal": "补充唯一解释。",
                "rationale": "消除歧义。",
                "tradeoffs": "需要产品确认。",
                "requires_confirmation": True,
            },
        }
        endpoint = self.api + f"/{report['id']}/manual-risks"
        created = self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(
            self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN).json()["id"],
            created.json()["id"],
        )
        catalog = self.client.get(self.base + "/risk-reports-catalog").json()
        self.assertEqual(catalog["overview"]["risks"], len(report["report"]["risks"]) + 1)
        saved = self.client.post(
            endpoint + f"/{created.json()['id']}/handling",
            json={"status": "NEEDS_INFO", "note": "等待产品补充。", "revision": 1},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["status"], "NEEDS_INFO")
        with self.factory() as db:
            self.assertEqual(
                db.query(RequirementManualRisk)
                .filter(RequirementManualRisk.report_id == report["id"])
                .count(),
                1,
            )

    def test_new_tables_have_real_database_comments(self):
        with self.factory() as db:
            for model in (RequirementRiskAnalysis, RequirementManualRisk):
                table = model.__table__
                self.assertEqual(
                    db.scalar(text(f"SELECT obj_description('{table.name}'::regclass)")),
                    table.comment,
                )
                comments = dict(
                    db.execute(
                        text(
                            "SELECT attname, col_description(attrelid, attnum) "
                            "FROM pg_attribute WHERE attrelid=to_regclass(:table) "
                            "AND attnum>0 AND NOT attisdropped"
                        ),
                        {"table": table.name},
                    ).all()
                )
                self.assertEqual(
                    comments, {column.name: column.comment for column in table.columns}
                )
