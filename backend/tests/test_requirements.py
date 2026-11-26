import os
import tempfile
import unittest
from unittest.mock import patch

import test_auth
from sqlalchemy import text

from app.db.models import (
    RequirementCategory,
    RequirementClassification,
    RequirementHistory,
    RequirementLibrary,
    RequirementRule,
    RequirementSource,
)
from app.main import app


class RequirementRoutesTests(unittest.TestCase):
    def test_retired_acceptance_points_are_absent_and_risk_routes_remain(self):
        paths = app.openapi()["paths"]
        prefix = "/api/projects/{project_id}/requirements"
        for suffix in (
            "",
            "/classification-history",
            "/categories",
            "/categories/{category_id}",
            "/move",
            "/categories/{category_id}/delete",
            "/assign",
            "/undo/{event_id}",
            "/rules",
            "/rules/{rule_id}",
        ):
            self.assertNotIn(prefix + suffix, paths)
        self.assertIn("get", paths[prefix + "/risk-reports/{report_id}/deletion"])
        self.assertIn("post", paths[prefix + "/risk-analyses"])


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class RequirementDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login

    def setUp(self):
        test_auth.AuthDatabaseTests.setUp(self)
        self.storage = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DOCUMENT_STORAGE_PATH": self.storage.name})
        self.env.start()
        self.login()
        project = self.client.post(
            "/api/projects",
            json={"name": "需求页面验证", "identifier": self.prefix, "owner_id": self.admin_id},
            headers=test_auth.ORIGIN,
        ).json()
        self.project = project["id"]
        self.client.post(
            f"/api/projects/{self.project}/members",
            json={"user_id": self.member_id, "version": project["version"]},
            headers=test_auth.ORIGIN,
        )
        self.other = self.client.post(
            "/api/projects",
            json={"name": "隔离", "identifier": self.prefix + "_other", "owner_id": self.admin_id},
            headers=test_auth.ORIGIN,
        ).json()["id"]
        self.base = f"/api/projects/{self.project}/requirements"
        self.docs = f"/api/projects/{self.project}/documents"
        self.login(self.member_name)

    def tearDown(self):
        test_auth.AuthDatabaseTests.tearDown(self)
        self.env.stop()
        self.storage.cleanup()

    def test_legacy_database_comments_match_models(self):
        for model in (
            RequirementCategory,
            RequirementRule,
            RequirementLibrary,
            RequirementSource,
            RequirementHistory,
            RequirementClassification,
        ):
            table = model.__table__
            comment = self.connection.scalar(
                text("SELECT obj_description(CAST(:name AS regclass))"), {"name": table.name}
            )
            self.assertEqual(comment, table.comment)
            for column in table.columns:
                actual = self.connection.scalar(
                    text(
                        "SELECT col_description(CAST(:name AS regclass), attnum) FROM pg_attribute "
                        "WHERE attrelid=CAST(:name AS regclass) AND attname=:column"
                    ),
                    {"name": table.name, "column": column.name},
                )
                self.assertEqual(actual, column.comment)
