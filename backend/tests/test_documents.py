import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import openpyxl
import test_auth

from app.core.errors import AppError
from app.modules.documents.files import preview, validate_file


class DocumentPreviewTests(unittest.TestCase):
    def test_text_office_and_unsafe_xml(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            path.write_bytes(("中文正文\n" * 100000).encode())
            validate_file(path, "txt")
            result = preview(path, "txt")
            self.assertTrue(result["truncated"])
            self.assertTrue(result["text"].startswith("中文正文"))
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(
                    "word/document.xml",
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>需求内容</w:t></w:r></w:p></w:body></w:document>',
                )
            validate_file(path, "docx")
            self.assertEqual(preview(path, "docx")["text"], "需求内容")
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "需求清单"
            sheet["A1"] = "需求名称"
            sheet["B1"] = "=1+1"
            workbook.save(path)
            workbook.close()
            self.assertIn("A1: 需求名称", preview(path, "xlsx")["text"])
            self.assertIn("未重新计算", preview(path, "xlsx")["text"])
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY y "bad">]><x>&y;</x>')
            with self.assertRaises(AppError):
                validate_file(path, "docx")
            with zipfile.ZipFile(path, "w") as z:
                z.writestr(
                    "word/document.xml",
                    '<!DOCTYPE x [<!ENTITY y "bad">]><x>&y;</x>'.encode("utf-16"),
                )
            with self.assertRaises(AppError):
                validate_file(path, "docx")
            self.assertEqual(preview(path, "doc")["kind"], "unsupported")


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class DocumentDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login

    def setUp(self):
        test_auth.AuthDatabaseTests.setUp(self)
        self.storage = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"DOCUMENT_STORAGE_PATH": self.storage.name})
        self.environment.start()

    def tearDown(self):
        test_auth.AuthDatabaseTests.tearDown(self)
        self.environment.stop()
        self.storage.cleanup()

    def test_upload_versions_grouping_access_and_large_file(self):
        self.assertEqual(self.login().status_code, 200)
        project = self.client.post(
            "/api/projects",
            json={
                "name": "资料检查",
                "identifier": self.prefix + "_docs",
                "owner_id": self.admin_id,
            },
            headers=test_auth.ORIGIN,
        ).json()
        membership = self.client.post(
            f"/api/projects/{project['id']}/members",
            json={"user_id": self.member_id, "version": project["version"]},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(membership.status_code, 200, membership.text)
        other = self.client.post(
            "/api/projects",
            json={
                "name": "隔离检查",
                "identifier": self.prefix + "_other",
                "owner_id": self.admin_id,
            },
            headers=test_auth.ORIGIN,
        ).json()
        base = f"/api/projects/{project['id']}/documents"
        other_base = f"/api/projects/{other['id']}/documents"
        self.assertEqual(self.client.get(base).json()["revision"], 0)
        response = self.client.post(
            base + "/groups", json={"name": "截图", "revision": 0}, headers=test_auth.ORIGIN
        )
        self.assertEqual(response.status_code, 201, response.text)
        group = response.json()["groups"][0]["id"]
        revision = response.json()["revision"]
        self.assertEqual(
            self.client.post(
                base + "/groups",
                json={"name": "截图", "revision": revision},
                headers=test_auth.ORIGIN,
            ).status_code,
            409,
        )
        other_group = self.client.post(
            other_base + "/groups", json={"name": "私有组", "revision": 0}, headers=test_auth.ORIGIN
        ).json()["groups"][0]["id"]
        self.assertEqual(self.login(self.member_name).status_code, 200)
        self.assertEqual(self.client.get(other_base).status_code, 404)
        params = {
            "filename": "原文.txt",
            "revision": revision,
            "upload_id": str(uuid4()),
            "group_id": group,
        }
        response = self.client.post(
            base + "/upload", params=params, content="原文内容".encode(), headers=test_auth.ORIGIN
        )
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        doc = data["documents"][0]
        old = doc["current"]
        rename_path = base + f"/groups/{group}"
        for name in (" ", "未分组"):
            self.assertEqual(
                self.client.patch(
                    rename_path,
                    json={"name": name, "revision": data["revision"]},
                    headers=test_auth.ORIGIN,
                ).status_code,
                422,
            )
        self.assertEqual(
            self.client.patch(
                rename_path, json={"name": "改名", "revision": 0}, headers=test_auth.ORIGIN
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.patch(
                base + f"/groups/{other_group}",
                json={"name": "改名", "revision": data["revision"]},
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                rename_path, json={"name": "改名", "revision": data["revision"]}
            ).status_code,
            403,
        )
        renamed = self.client.patch(
            rename_path,
            json={"name": "产品截图", "revision": data["revision"]},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        data = renamed.json()
        self.assertEqual(data["groups"][0], {"id": group, "name": "产品截图"})
        self.assertEqual(data["documents"][0]["current"], old)
        self.assertEqual(data["documents"][0]["group_id"], group)
        created = self.client.post(
            base + "/groups",
            json={"name": "另一个组", "revision": data["revision"]},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(created.status_code, 201, created.text)
        data = created.json()
        self.assertEqual(
            self.client.patch(
                rename_path,
                json={"name": "另一个组", "revision": data["revision"]},
                headers=test_auth.ORIGIN,
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                base + "/upload",
                params=params,
                content="原文内容".encode(),
                headers=test_auth.ORIGIN,
            ).json()["revision"],
            data["revision"],
        )
        self.assertEqual(
            self.client.post(
                base + "/move",
                json={
                    "revision": data["revision"],
                    "document_ids": [doc["id"]],
                    "group_id": other_group,
                },
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                base + "/move",
                json={"revision": 0, "document_ids": [doc["id"]], "group_id": None},
                headers=test_auth.ORIGIN,
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                base + "/move",
                json={"revision": data["revision"], "document_ids": [doc["id"]], "group_id": None},
            ).status_code,
            403,
        )
        data = self.client.post(
            base + "/move",
            json={"revision": data["revision"], "document_ids": [doc["id"]], "group_id": None},
            headers=test_auth.ORIGIN,
        ).json()
        self.assertIsNone(data["documents"][0]["group_id"])
        params = {
            "filename": "新版.txt",
            "revision": data["revision"],
            "upload_id": str(uuid4()),
            "document_id": doc["id"],
        }
        # More than 20 MB must be accepted; preview remains bounded.
        response = self.client.post(
            base + "/upload",
            params=params,
            content=b"a" * (21 * 1024 * 1024),
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        newest = data["documents"][0]["current"]
        self.assertEqual(newest["number"], 2)
        self.assertEqual(newest["size"], 21 * 1024 * 1024)
        self.assertEqual(
            self.client.get(base + f"/versions/{old['id']}/file").content, "原文内容".encode()
        )
        self.assertTrue(
            self.client.get(base + f"/versions/{newest['id']}/preview").json()["truncated"]
        )
        self.assertEqual(len(self.client.get(base + f"/{doc['id']}/versions").json()), 2)
        self.assertEqual(
            self.client.get(other_base + f"/versions/{old['id']}/file").status_code, 404
        )
        for filename in ("../escape.txt", "evil.html", "bad.png"):
            response = self.client.post(
                base + "/upload",
                params={
                    **params,
                    "filename": filename,
                    "revision": data["revision"],
                    "upload_id": str(uuid4()),
                },
                content=b"not an image",
                headers=test_auth.ORIGIN,
            )
            self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(len(list(Path(self.storage.name).iterdir())), 2)
