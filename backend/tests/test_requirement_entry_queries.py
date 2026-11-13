"""Entry queries keep large snapshots unloaded and avoid per-author queries."""

import copy
import os
import unittest
from datetime import UTC, datetime
from uuid import uuid4

import test_auth
import test_risk_reports
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.db.models import RequirementRiskAnalysis, RequirementRiskReport, UserAccount
from app.modules.requirements import risk_analysis_service, risk_service


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class RequirementEntryQueryTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    setUp = test_risk_reports.RiskReportDatabaseTests.setUp
    tearDown = test_risk_reports.RiskReportDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login
    upload = test_risk_reports.RiskReportDatabaseTests.upload

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def read(self, service, model, unloaded):
        statements, loaded = [], []

        def capture_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        def capture_row(session, instance):
            if isinstance(instance, model):
                loaded.append(instance)

        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            event.listen(self.connection, "before_cursor_execute", capture_sql)
            event.listen(db, "loaded_as_persistent", capture_row)
            try:
                value = service(self.project, actor, db)
            finally:
                event.remove(self.connection, "before_cursor_execute", capture_sql)
                event.remove(db, "loaded_as_persistent", capture_row)
            self.assertTrue(loaded)
            for row in loaded:
                self.assertIn(unloaded, inspect(row).unloaded)
            self.assertFalse(db.dirty)
        return value, len(statements)

    def add_author(self, db, index):
        author = UserAccount(
            login_name=f"{self.prefix}_author_{index}",
            display_name=f"报告作者{index}",
            password_hash=self.encoded,
            platform_role="USER",
        )
        db.add(author)
        db.flush()
        return author.id

    def test_task_listing_preserves_full_view_without_loading_context_or_author_n_plus_one(self):
        corrections = [{"function_key": "F1", "before": [], "after": ["R1"]}]
        context = {"input": {"fixed_text": "原始资料" * 300_000}}

        def add_task(db, actor_id, **values):
            row = RequirementRiskAnalysis(
                project_id=self.project,
                actor_id=actor_id,
                request_id=str(uuid4()),
                title="需求分析查询验证",
                focus="完整保留关注点",
                selections=[{"document_id": self.doc["id"], "paths": ["长路径/资料.html"]}],
                context=context,
                ai_config={},
                **values,
            )
            db.add(row)
            return row

        with self.factory() as db:
            first = add_task(db, self.member_id, status="FAILED")
            db.commit()
            first_id = first.id
        _, initial_count = self.read(
            risk_analysis_service.listing, RequirementRiskAnalysis, "context"
        )
        with self.factory() as db:
            for index, status in enumerate(("QUEUED", "RUNNING", "COMPLETED", "CANCELLED")):
                task = add_task(db, self.add_author(db, index), status=status, retry_of=first_id)
                task.context = {**context, "function_risk_corrections": corrections}
            add_task(db, self.member_id, status="FAILED", deleted_at=datetime.now(UTC))
            db.commit()
        actual, expanded_count = self.read(
            risk_analysis_service.listing, RequirementRiskAnalysis, "context"
        )
        self.assertEqual(initial_count, expanded_count)
        self.assertEqual(len(actual["items"]), 5)
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            rows = db.scalars(
                select(RequirementRiskAnalysis)
                .where(
                    RequirementRiskAnalysis.project_id == self.project,
                    RequirementRiskAnalysis.deleted_at.is_(None),
                )
                .order_by(RequirementRiskAnalysis.id.desc())
            ).all()
            expected = [risk_analysis_service.view(row, db, actor) for row in rows]
        self.assertEqual(actual["items"], expected)
        self.assertEqual(actual["items"][0]["function_risk_corrections"], corrections)
        self.assertEqual(actual["items"][-1]["function_risk_corrections"], [])

    def test_catalog_keeps_input_unloaded_and_authors_batched_with_full_detail_still_available(
        self,
    ):
        imported = self.upload().json()
        report_id = imported["id"]
        _, initial_count = self.read(risk_service.catalog, RequirementRiskReport, "input")
        snapshot = copy.deepcopy(self.context)
        snapshot["materials"][0]["segments"][0]["text"] += "固定正文" * 300_000
        with self.factory() as db:
            original = db.get(RequirementRiskReport, report_id)
            original.input = snapshot
            for index in range(4):
                db.add(
                    RequirementRiskReport(
                        project_id=self.project,
                        title=f"固定报告{index}",
                        input_filename="input.json",
                        report_filename="report.json",
                        sha256=uuid4().hex + uuid4().hex,
                        input=snapshot,
                        report=original.report,
                        bindings=original.bindings,
                        handling={},
                        created_by=self.add_author(db, index),
                    )
                )
            db.commit()
        actual, expanded_count = self.read(risk_service.catalog, RequirementRiskReport, "input")
        self.assertEqual(initial_count, expanded_count)
        self.assertEqual(len(actual["reports"]), 5)
        self.assertEqual(actual["total"], 5)
        self.assertEqual(actual["reports"][0]["created_by"], "报告作者3")
        self.assertFalse(actual["reports"][0]["can_delete"])
        self.assertTrue(actual["reports"][-1]["can_delete"])
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            scoped = risk_service.catalog(self.project, actor, db, source=report_id)
            self.assertEqual(scoped["total"], 1)
            self.assertEqual(scoped["items"][0]["risk"], self.report["risks"][0])
            detail = risk_service.detail(self.project, report_id, actor, db)
            self.assertEqual(detail["input"], snapshot)
            self.assertEqual(detail["report"], imported["report"])
            self.assertEqual(detail["bindings"], imported["bindings"])
            self.assertFalse(db.dirty)
