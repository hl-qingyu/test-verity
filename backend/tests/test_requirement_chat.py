import copy
import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_auth
import test_risk_reports
from sqlalchemy import text
from sqlalchemy.orm import Session
from worker_fixtures import claim as claim_for_execution

from app.core.errors import AppError
from app.db import models as worker_models
from app.db.models import AIConnection, RequirementChatTurn, RequirementRiskReport, UserAccount
from app.modules.requirements import chat_execution, chat_service
from app.modules.requirements.chat_schemas import ChatInput


class ChatValidationTests(unittest.TestCase):
    def test_blank_and_invalid_messages_rejected(self):
        for question in (" ", "bad\x00text", "x" * 8001):
            with self.assertRaises(ValueError):
                ChatInput(request_id=uuid4(), question=question)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class ChatDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    setUp = test_risk_reports.RiskReportDatabaseTests.setUp
    tearDown = test_risk_reports.RiskReportDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login
    upload = test_risk_reports.RiskReportDatabaseTests.upload

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def setup_chat(self):
        self.report_id = self.upload().json()["id"]
        self.chat = self.api + f"/{self.report_id}/chat"
        with self.factory() as db:
            db.add(
                AIConnection(
                    id=self.member_id,
                    owner_id=self.member_id,
                    name="个人模型",
                    base_url="https://api.openai.com/v1",
                    model="configured-model",
                    encrypted_key="TEST-CIPHER",
                    version=1,
                    updated_by=self.member_id,
                )
            )
            db.commit()

    def configuration(self, actor, db, version=None):
        if isinstance(version, dict):
            version = version.get("version")
        self.assertEqual(actor.id, self.member_id)
        if version is not None:
            self.assertEqual(version, 1)
        return {
            "name": "个人模型",
            "model": "configured-model",
            "version": 1,
            "base_url": "https://api.openai.com/v1",
            "reasoning_effort": "default",
        }, "TEST-SECRET"

    def post(self, question="哪些风险优先确认？", last=0, request_id=None):
        return self.client.post(
            self.chat,
            json={
                "request_id": request_id or str(uuid4()),
                "question": question,
                "last_turn_id": last,
            },
            headers=test_auth.ORIGIN,
        )

    def test_queue_idempotency_context_resume_and_business_immutable(self):
        self.setup_chat()
        with (
            patch.object(chat_service, "analysis_configuration", side_effect=self.configuration),
            patch.object(chat_execution, "analysis_configuration", side_effect=self.configuration),
        ):
            request_id = str(uuid4())
            response = self.post(request_id=request_id)
            self.assertEqual(response.status_code, 202, response.text)
            first = response.json()
            self.assertEqual(self.post(request_id=request_id).json()["id"], first["id"])
            self.assertEqual(self.post().status_code, 409)
            self.assertEqual(self.post("different", request_id=request_id).status_code, 409)
            with self.factory() as db:
                original = db.get(RequirementRiskReport, self.report_id)
                fixed = copy.deepcopy((original.input, original.report, original.handling))
                self.assertEqual(
                    claim_for_execution(db, worker_models.RequirementChatTurn), first["id"]
                )

            def answer(base, model, key, effort, instructions, messages, **kwargs):
                self.assertEqual(key, "TEST-SECRET")
                self.assertEqual(model, "configured-model")
                self.assertIn("D1", messages[0]["content"])
                self.assertIn("不能修改", instructions)
                kwargs["on_progress"]()
                return "先确认需求歧义，代号青竹42。"

            with patch("app.integrations.responses.converse", side_effect=answer) as upstream:
                chat_execution.execute(first["id"], self.factory)
                upstream.assert_called_once()
            history = self.client.get(self.chat).json()
            self.assertEqual(history["items"][0]["status"], "COMPLETED")
            self.assertEqual(history["items"][0]["answer"], "先确认需求歧义，代号青竹42。")
            self.assertNotIn("TEST-SECRET", json.dumps(history))
            self.assertEqual(self.post(last=0).status_code, 409)
            second = self.post("记得代号吗？", first["id"]).json()
            with self.factory() as db:
                row = db.get(RequirementChatTurn, second["id"])
                self.assertIn("青竹42", row.context["messages"][1]["content"])
                self.assertEqual(
                    claim_for_execution(db, worker_models.RequirementChatTurn), second["id"]
                )
            with patch("app.integrations.responses.converse", return_value="青竹42"):
                chat_execution.execute(second["id"], self.factory)
            with self.factory() as db:
                current = db.get(RequirementRiskReport, self.report_id)
                self.assertEqual((current.input, current.report, current.handling), fixed)
            self.assertEqual(len(self.client.get(self.chat).json()["items"]), 2)

    def test_permissions_cancel_failure_recovery_and_large_context(self):
        self.setup_chat()
        with (
            patch.object(chat_service, "analysis_configuration", side_effect=self.configuration),
            patch.object(chat_execution, "analysis_configuration", side_effect=self.configuration),
        ):
            first = self.post().json()
            self.assertEqual(
                self.client.get(
                    self.chat.replace(f"/{self.project}/", f"/{self.other}/")
                ).status_code,
                404,
            )
            self.login()
            self.assertEqual(
                self.client.post(
                    self.chat + f"/{first['id']}/cancel", headers=test_auth.ORIGIN
                ).status_code,
                403,
            )
            self.login(self.member_name)
            self.assertEqual(
                self.client.post(
                    self.chat + f"/{first['id']}/cancel", headers=test_auth.ORIGIN
                ).json()["status"],
                "CANCELLED",
            )
            with self.factory() as db:
                self.assertIsNone(claim_for_execution(db, worker_models.RequirementChatTurn))
            second = self.post(last=first["id"]).json()
            with self.factory() as db:
                claim_for_execution(db, worker_models.RequirementChatTurn)
            with patch(
                "app.integrations.responses.converse", side_effect=AppError(502, "ai_stream_failed")
            ):
                chat_execution.execute(second["id"], self.factory)
            self.assertEqual(
                self.client.get(self.chat).json()["items"][-1]["error_code"], "ai_stream_failed"
            )
            third = self.post(last=second["id"]).json()
            with self.factory() as db:
                claim_for_execution(db, worker_models.RequirementChatTurn)
                chat_execution.recover(db)
                self.assertEqual(
                    db.get(RequirementChatTurn, third["id"]).error_code, "chat_worker_interrupted"
                )
                report = db.get(RequirementRiskReport, self.report_id)
                report.input = {"large": "需求正文" * 80_000}
                db.commit()
            result = self.post(last=third["id"])
            self.assertEqual(result.status_code, 202, result.text)
            with self.factory() as db:
                queued = db.get(RequirementChatTurn, result.json()["id"])
                self.assertEqual(queued.context["input"]["large"], "需求正文" * 80_000)

    def test_worker_rechecks_permission_before_call_and_cancel_discards_response(self):
        self.setup_chat()
        with (
            patch.object(chat_service, "analysis_configuration", side_effect=self.configuration),
            patch.object(chat_execution, "analysis_configuration", side_effect=self.configuration),
        ):
            row = self.post().json()
            with self.factory() as db:
                claim_for_execution(db, worker_models.RequirementChatTurn)
                actor = db.get(UserAccount, self.member_id)
                actor.status = "DISABLED"
                db.commit()
            with patch("app.integrations.responses.converse") as upstream:
                chat_execution.execute(row["id"], self.factory)
                upstream.assert_not_called()
            with self.factory() as db:
                actor = db.get(UserAccount, self.member_id)
                actor.status = "ACTIVE"
                db.commit()
            next_row = self.post(last=row["id"]).json()
            with self.factory() as db:
                claim_for_execution(db, worker_models.RequirementChatTurn)

            def cancelled(*args, **kwargs):
                with self.factory() as db:
                    actor = db.get(UserAccount, self.member_id)
                    chat_service.cancel(self.project, self.report_id, next_row["id"], actor, db)
                return "must not save"

            with patch("app.integrations.responses.converse", side_effect=cancelled):
                chat_execution.execute(next_row["id"], self.factory)
            result = self.client.get(self.chat).json()["items"][-1]
            self.assertEqual(result["status"], "CANCELLED")
            self.assertEqual(result["answer"], "")

    def test_real_database_comments_match_model(self):
        with self.factory() as db:
            table = RequirementChatTurn.__table__
            self.assertEqual(
                db.scalar(text("SELECT obj_description('requirement_chat_turn'::regclass)")),
                table.comment,
            )
            comments = dict(
                db.execute(
                    text(
                        "SELECT attname, col_description(attrelid, attnum) FROM pg_attribute "
                        "WHERE attrelid='requirement_chat_turn'::regclass "
                        "AND attnum>0 AND NOT attisdropped"
                    )
                ).all()
            )
            self.assertEqual(comments, {column.name: column.comment for column in table.columns})
