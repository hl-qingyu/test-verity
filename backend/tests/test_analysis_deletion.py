"""Real migrated PostgreSQL, synthetic records, rollback-only business changes."""

import os
import unittest
from uuid import uuid4

import test_acceptance
import test_auth
from sqlalchemy import select

from app.db.models import (
    CaseGenerationBatch,
    CodeAnalysisTask,
    Project,
    RequirementRiskAnalysis,
    RequirementRiskReport,
    UserAccount,
)
from app.modules.acceptance import sources
from app.modules.code_analysis import service as code_service
from app.modules.projects import record_deletion as deletion


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL")
class AnalysisDeletionTests(unittest.TestCase):
    setUpClass = classmethod(test_acceptance.AcceptanceTests.setUpClass.__func__)
    setUp = test_acceptance.AcceptanceTests.setUp
    tearDown = test_acceptance.AcceptanceTests.tearDown
    login = test_acceptance.AcceptanceTests.login
    factory = test_acceptance.AcceptanceTests.factory
    seed = test_acceptance.AcceptanceTests.seed

    def test_sidebar_metadata_contains_creator_without_reading_record_details(self):
        for module in ("code", "changes", "generate"):
            identity = self.seed(module)
            url = self.url(module, identity).rsplit("/", 1)[0]
            if module == "generate":
                url += "?summary=true"
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, response.text)
            row = next(r for r in response.json()["items"] if str(r["id"]) == str(identity))
            self.assertEqual(row["ownerId" if module == "generate" else "actor_id"], self.member_id)
            self.assertNotIn("input", row)
            self.assertNotIn("report", row)

    def url(self, module, identity):
        path = {
            "requirements": "requirements/risk-reports",
            "requirement-task": "requirements/risk-analyses",
            "code": "code-analysis",
            "changes": "change-analysis",
            "generate": "case-generation",
            "coverage": "case-analysis",
        }[module]
        return f"/api/projects/{self.project}/{path}/{identity}"

    def delete(self, module, identity, expected=200):
        url = self.url(module, identity)
        info = self.client.get(url + "/deletion")
        self.assertEqual(info.status_code, 200, info.text)
        response = self.client.post(
            url + "/delete",
            headers=test_auth.ORIGIN,
            json={"confirmed": True, "revision": info.json()["revision"]},
        )
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def test_all_five_hide_results_and_statistics_but_preserve_fixed_report_and_application(self):
        for module in sources.MODELS:
            identity = self.seed(module)
            with self.subTest(module=module), self.factory() as db:
                model = sources.MODELS[module]
                before = db.get(model, identity)
                original = dict(before.report) if module != "generate" else dict(before.handling)
                self.assertTrue(sources.records(module, self.project, db, identity))
                self.delete(module, identity)
                db.expire_all()
                row = db.get(model, identity)
                self.assertIsNotNone(row.deleted_at)
                self.assertEqual(row.deleted_by, self.member_id)
                self.assertEqual(row.report if module != "generate" else row.handling, original)
                self.assertEqual(sources.records(module, self.project, db, identity), {})
                listing = self.client.get(self.url(module, identity).rsplit("/", 1)[0])
                self.assertEqual(listing.status_code, 200, listing.text)
                self.assertNotIn(str(identity), [str(v["id"]) for v in listing.json()["items"]])
                from app.modules.overview import service as overview

                result = overview.read_module(
                    module, self.project, db.get(UserAccount, self.member_id), db
                )
                self.assertFalse(
                    any(r["module"] == module and r["record_id"] == identity for r in result)
                )
                self.assertEqual(self.client.get(self.url(module, identity)).status_code, 404)
                # Deletes stay idempotent even when their original revision is stale.
                response = self.client.post(
                    self.url(module, identity) + "/delete",
                    headers=test_auth.ORIGIN,
                    json={"confirmed": True, "revision": 1},
                )
                self.assertEqual(response.status_code, 200, response.text)
                if module == "generate":
                    self.assertIsNotNone(
                        db.scalar(
                            select(CaseGenerationBatch).where(
                                CaseGenerationBatch.run_id == identity
                            )
                        )
                    )

    def test_owner_manager_cross_project_origin_and_revision_boundaries(self):
        identity = self.seed("code")
        with self.factory() as db:
            db.get(CodeAnalysisTask, identity).actor_id = self.admin_id
            db.commit()
        self.assertFalse(
            self.client.get(self.url("code", identity) + "/deletion").json()["can_delete"]
        )
        self.delete("code", identity, 403)
        self.assertEqual(
            self.client.post(
                self.url("code", identity) + "/delete", json={"confirmed": True}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.url("code", identity) + "/delete",
                headers=test_auth.ORIGIN,
                json={"confirmed": False},
            ).status_code,
            422,
        )
        foreign = self.url("code", identity).replace(
            f"/projects/{self.project}/", f"/projects/{self.other}/"
        )
        self.assertEqual(self.client.get(foreign + "/deletion").status_code, 404)
        with self.factory() as db:
            db.get(Project, self.project).owner_id = self.member_id
            db.commit()
        self.assertTrue(
            self.client.get(self.url("code", identity) + "/deletion").json()["can_delete"]
        )
        changed = self.client.post(
            self.url("code", identity) + "/delete",
            headers=test_auth.ORIGIN,
            json={"confirmed": True, "revision": 99},
        )
        self.assertEqual(changed.status_code, 409)
        self.delete("code", identity)
        self.client.cookies.clear()
        self.assertEqual(self.client.get(self.url("code", identity) + "/deletion").status_code, 401)

    def test_active_children_block_even_completed_parent_and_prepared_can_be_deleted(self):
        for module in ["requirements", "code", "changes", "generate", "coverage"]:
            identity = self.seed(module)
            for model, key in deletion.CHILDREN[module]:
                with self.subTest(module=module, child=model.__name__), self.factory() as db:
                    values = {key: identity, "actor_id": self.member_id, "status": "QUEUED"}
                    if "request_id" in model.__table__.c:
                        values["request_id"] = str(uuid4())
                    if "project_id" in model.__table__.c:
                        values["project_id"] = self.project
                    for column in model.__table__.c:
                        if (
                            column.name in values
                            or column.nullable
                            or column.default is not None
                            or column.server_default is not None
                            or column.primary_key
                        ):
                            continue
                        if column.foreign_keys:
                            continue
                        if column.name in {
                            "ai_config",
                            "input_snapshot",
                            "report",
                            "metadata_snapshot",
                            "payload",
                            "context",
                        }:
                            values[column.name] = {}
                        elif column.name in {"items", "attempts"}:
                            values[column.name] = []
                        else:
                            values[column.name] = "synthetic"
                    child = model(**values)
                    db.add(child)
                    db.commit()
                    self.delete(module, identity, 409)
                    child.status = "COMPLETED"
                    db.commit()
            with self.factory() as db:
                row = db.get(sources.MODELS[module], identity)
                if module != "requirements":
                    row.status = "PREPARED" if module in {"generate", "coverage"} else "FAILED"
                db.commit()
            self.delete(module, identity)

    def test_requirement_report_and_tasks_are_atomic_and_retry_descendants_remain(self):
        identity = self.seed("requirements")
        with self.factory() as db:
            task = RequirementRiskAnalysis(
                project_id=self.project,
                actor_id=self.member_id,
                request_id=str(uuid4()),
                title="合成需求任务",
                selections=[],
                context={},
                ai_config={},
                status="COMPLETED",
                report_id=identity,
            )
            db.add(task)
            db.flush()
            descendant = RequirementRiskAnalysis(
                project_id=self.project,
                actor_id=self.member_id,
                request_id=str(uuid4()),
                title="独立重试后代",
                selections=[],
                context={},
                ai_config={},
                status="FAILED",
                retry_of=task.id,
            )
            db.add(descendant)
            db.commit()
            task_id = task.id
            retry_id = descendant.id
        self.delete("requirement-task", task_id)
        with self.factory() as db:
            self.assertIsNotNone(db.get(RequirementRiskReport, identity).deleted_at)
            self.assertIsNotNone(db.get(RequirementRiskAnalysis, task_id).deleted_at)
            self.assertIsNone(db.get(RequirementRiskAnalysis, retry_id).deleted_at)
        self.assertEqual(
            self.client.get(self.url("requirement-task", task_id) + "/candidate").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                self.url("requirements", identity) + "/chat",
                headers=test_auth.ORIGIN,
                json={"request_id": str(uuid4()), "question": "合成问题"},
            ).status_code,
            404,
        )

    def test_active_parent_administrator_delete_and_revoked_membership(self):
        identity = self.seed("code")
        with self.factory() as db:
            db.get(CodeAnalysisTask, identity).status = "QUEUED"
            db.commit()
        self.delete("code", identity, 409)
        with self.factory() as db:
            row = db.get(CodeAnalysisTask, identity)
            self.assertIsNone(row.deleted_at)
            row.status = "FAILED"
            row.actor_id = self.admin_id
            db.commit()
        self.login(self.admin_name)
        self.delete("code", identity)
        self.login(self.member_name)
        another = self.seed("code")
        from app.db.models import ProjectMember

        with self.factory() as db:
            db.delete(db.get(ProjectMember, (self.project, self.member_id)))
            db.commit()
        self.assertEqual(
            self.client.post(
                self.url("code", another) + "/delete",
                headers=test_auth.ORIGIN,
                json={"confirmed": True, "revision": 1},
            ).status_code,
            404,
        )

    def test_deleted_request_id_is_retained_and_cannot_become_a_new_paid_task(self):
        identity = self.seed("code")
        self.delete("code", identity)
        with self.factory() as db:
            row = db.get(CodeAnalysisTask, identity)
            self.assertIsNotNone(row.request_id)
            with self.assertRaises(Exception) as caught:
                code_service.view(row, db.get(UserAccount, self.member_id))
            self.assertEqual(caught.exception.detail, "analysis_record_deleted")
            self.assertEqual(
                db.scalar(
                    select(CodeAnalysisTask.id).where(CodeAnalysisTask.request_id == row.request_id)
                ),
                identity,
            )
