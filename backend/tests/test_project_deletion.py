"""Migrated PostgreSQL with synthetic data and outer rollback only."""

import os
import unittest
from uuid import uuid4

import test_acceptance
import test_auth

from app.core.errors import AppError
from app.db.models import Project, RequirementRiskAnalysis, UserAccount
from app.modules.acceptance import sources
from app.modules.projects import record_deletion, service


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL")
class ProjectDeletionTests(unittest.TestCase):
    setUpClass = classmethod(test_acceptance.AcceptanceTests.setUpClass.__func__)
    setUp = test_acceptance.AcceptanceTests.setUp
    tearDown = test_acceptance.AcceptanceTests.tearDown
    login = test_acceptance.AcceptanceTests.login
    factory = test_acceptance.AcceptanceTests.factory
    seed = test_acceptance.AcceptanceTests.seed

    def delete(self, **overrides):
        with self.factory() as db:
            version = db.get(Project, self.project).version
        return self.client.request(
            "DELETE",
            f"/api/projects/{self.project}",
            headers=test_auth.ORIGIN,
            json={"confirmed": True, "version": version, **overrides},
        )

    def test_roles_origin_confirmation_and_revision(self):
        self.assertEqual(self.delete().status_code, 403)
        self.login(self.admin_name)
        self.assertEqual(self.delete(confirmed=False).status_code, 422)
        self.assertEqual(self.delete(version=99999).status_code, 409)
        self.assertEqual(
            self.client.request(
                "DELETE", f"/api/projects/{self.project}", json={"confirmed": True, "version": 1}
            ).status_code,
            403,
        )
        self.client.cookies.clear()
        self.assertEqual(self.delete().status_code, 401)

    def test_owner_can_delete_and_all_sources_hidden_but_preserved(self):
        ids = {module: self.seed(module) for module in sources.MODELS}
        with self.factory() as db:
            p = db.get(Project, self.project)
            p.owner_id = self.member_id
            db.commit()
        response = self.delete()
        self.assertEqual(response.status_code, 200, response.text)
        for login in [self.member_name, self.admin_name]:
            self.login(login)
            self.assertNotIn(
                self.project, [p["id"] for p in self.client.get("/api/projects").json()]
            )
            for path in [
                "members",
                "repositories",
                "overview",
                "cases/metadata",
                "code-analysis",
                "prototypes",
            ]:
                self.assertEqual(
                    self.client.get(f"/api/projects/{self.project}/{path}").status_code, 404, path
                )
        with self.factory() as db:
            p = db.get(Project, self.project)
            self.assertIsNotNone(p.deleted_at)
            self.assertEqual(p.deleted_by, self.member_id)
            for module, identity in ids.items():
                row = db.get(sources.MODELS[module], identity)
                self.assertIsNone(row.deleted_at)
                self.assertNotEqual(row.handling if module == "generate" else row.report, {})
                self.assertEqual(sources.records(module, None, db, identity), {})
            self.assertIsNotNone(db.get(Project, self.other))

    def test_active_roots_and_every_child_block_deletion(self):
        self.login(self.admin_name)
        for module in sources.MODELS:
            identity = self.seed(module)
            parent = sources.MODELS[module]
            if module != "requirements":
                with self.factory() as db:
                    row = db.get(parent, identity)
                    row.status = "RUNNING"
                    db.commit()
                response = self.delete()
                self.assertEqual(response.status_code, 409, response.text)
                with self.factory() as db:
                    db.get(parent, identity).status = "COMPLETED"
                    db.commit()
            for model, key in record_deletion.CHILDREN[module]:
                with self.subTest(child=model.__name__), self.factory() as db:
                    values = {key: identity, "actor_id": self.member_id, "status": "QUEUED"}
                    for column in model.__table__.c:
                        if (
                            column.name in values
                            or column.nullable
                            or column.server_default is not None
                            or column.default is not None
                            or column.primary_key
                        ):
                            continue
                        if column.name == "project_id":
                            values[column.name] = self.project
                        elif column.foreign_keys:
                            values[column.name] = self.member_id
                        elif column.type.python_type is dict:
                            values[column.name] = {}
                        elif column.type.python_type is list:
                            values[column.name] = []
                        elif column.type.python_type is int:
                            values[column.name] = 1
                        else:
                            values[column.name] = str(uuid4())
                    child = model(**values)
                    db.add(child)
                    db.commit()
                    response = self.delete()
                    self.assertEqual(response.status_code, 409, response.text)
                    self.assertEqual(response.json()["detail"], "project_delete_active")
                    child.status = "COMPLETED"
                    db.commit()
        with self.factory() as db:
            task = RequirementRiskAnalysis(
                project_id=self.project,
                actor_id=self.member_id,
                request_id=str(uuid4()),
                title="合成需求任务",
                focus="",
                selections=[],
                ai_config={},
            )
            db.add(task)
            db.commit()
            self.assertEqual(self.delete().status_code, 409)
            task.status = "FAILED"
            db.commit()
        self.assertEqual(self.delete().status_code, 200)

    def test_deleted_project_access_is_rechecked_and_name_can_be_reused(self):
        self.login(self.admin_name)
        with self.factory() as db:
            actor = db.get(UserAccount, self.admin_id)
            stale = service.access_project(self.project, actor, db)
            identifier, name = stale.identifier, stale.name
            self.assertEqual(self.delete().status_code, 200)
            with self.assertRaises(AppError) as caught:
                service.access_project(self.project, actor, db, lock=True)
            self.assertEqual(caught.exception.detail, "project_not_found")
            response = self.client.post(
                "/api/projects",
                json={"name": name, "identifier": identifier, "owner_id": self.admin_id},
                headers=test_auth.ORIGIN,
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["name"], name)
            self.assertNotEqual(response.json()["identifier"], identifier)
