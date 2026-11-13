import os
import unittest
from uuid import uuid4

import test_auth
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LocalCodeSource, Project, ProjectMember
from app.modules.local_code.schemas import SourceInput

ORIGIN = test_auth.ORIGIN


class LocalCodeValidationTests(unittest.TestCase):
    def test_metadata_only_no_paths_contents_or_invalid_types(self):
        valid = dict(
            client_id=str(uuid4()), name="本地原型", directory_name="web", kind="PROTOTYPE"
        )
        self.assertEqual(SourceInput(**valid).kind, "PROTOTYPE")
        for extra in [
            {"directory_name": "D:\\private"},
            {"directory_name": "../code"},
            {"name": " "},
            {"kind": "SCRIPT"},
            {"contents": "secret"},
            {"owner_id": 10},
        ]:
            with self.assertRaises(ValidationError):
                SourceInput(**(valid | extra))


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class LocalCodeDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    setUp = test_auth.AuthDatabaseTests.setUp
    tearDown = test_auth.AuthDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login

    def test_owner_metadata_only_project_permissions_and_versions(self):
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            project = Project(
                name="目录验证",
                identifier=self.prefix,
                description="",
                owner_id=self.admin_id,
                created_by=self.admin_id,
            )
            db.add(project)
            db.flush()
            project_id = project.id
            db.add(ProjectMember(project_id=project_id, user_id=self.member_id))
            db.commit()
        path = f"/api/projects/{project_id}/local-code"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.login()
        payload = dict(
            client_id=str(uuid4()),
            name="用户本机",
            directory_name="code",
            kind="PROTOTYPE",
            version=0,
        )
        self.assertEqual(self.client.post(path, json=payload).status_code, 403)
        created = self.client.post(path, json=payload, headers=ORIGIN)
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["owner_id"], self.admin_id)
        self.assertEqual(
            self.client.post(path, json=payload, headers=ORIGIN).json()["id"], created.json()["id"]
        )
        edited = self.client.post(
            path, json=payload | {"version": 1, "name": "改名"}, headers=ORIGIN
        )
        self.assertEqual(edited.json()["version"], 2)
        self.assertEqual(
            self.client.post(path, json=payload | {"version": 1}, headers=ORIGIN).status_code, 409
        )
        self.assertEqual(
            self.client.post(
                path, json=payload | {"version": 2, "directory_name": "other"}, headers=ORIGIN
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                path, json=payload | {"code": "not allowed"}, headers=ORIGIN
            ).status_code,
            422,
        )
        self.login(self.member_name)
        self.assertEqual(len(self.client.get(path).json()), 1)
        self.assertEqual(self.client.post(path, json=payload, headers=ORIGIN).status_code, 403)
        self.assertEqual(
            self.client.get(f"/api/projects/{project_id + 999999}/local-code").status_code, 404
        )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            row = db.scalar(select(LocalCodeSource).where(LocalCodeSource.project_id == project_id))
            self.assertEqual(row.directory_name, "code")
            self.assertEqual(row.name, "改名")
            self.assertEqual(row.owner_id, self.admin_id)


if __name__ == "__main__":
    unittest.main()
