import os
import unittest
from urllib.parse import quote
from uuid import uuid4

import test_auth
import test_documents
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocumentLinkBinding
from app.modules.documents.markdown_links import extract_links, link_key


class MarkdownLinkTests(unittest.TestCase):
    def test_reference_links_unicode_and_code_are_not_confused(self):
        source = (
            "[中文](doc/%E4%BD%BF.md) [另一个名称](doc/使.md)\n\n"
            "[参考][id]\n\n[id]: <file:///C:/中文 文档.md>\n\n"
            "`[代码](fake.md)`\n\n```md\n[代码块](fake2.md)\n```\n\n"
            "![图片](image.png) [锚点](#标题)"
        )
        links = extract_links(source)
        self.assertEqual(len(links), 2)
        self.assertEqual(link_key(links[0]["href"]), "doc/使.md")
        self.assertEqual(link_key(links[1]["href"]), "file:///C:/中文 文档.md")
        self.assertEqual(link_key("bad%XX%E4%BD%BF"), "bad%XX%E4%BD%BF")


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class LinkDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_documents.DocumentDatabaseTests.setUpClass.__func__)
    setUp = test_documents.DocumentDatabaseTests.setUp
    tearDown = test_documents.DocumentDatabaseTests.tearDown
    login = test_documents.DocumentDatabaseTests.login

    def test_binding_inheritance_and_target_versions_are_frozen(self):
        self.login()
        project = self.client.post(
            "/api/projects",
            json={
                "name": "链接验证",
                "identifier": self.prefix + "_links",
                "owner_id": self.admin_id,
            },
            headers=test_auth.ORIGIN,
        ).json()
        self.client.post(
            f"/api/projects/{project['id']}/members",
            json={"user_id": self.member_id, "version": project["version"]},
            headers=test_auth.ORIGIN,
        )
        other = self.client.post(
            "/api/projects",
            json={
                "name": "隔离项目",
                "identifier": self.prefix + "_other",
                "owner_id": self.admin_id,
            },
            headers=test_auth.ORIGIN,
        ).json()
        base = f"/api/projects/{project['id']}/documents"
        other_base = f"/api/projects/{other['id']}/documents"

        def upload(base, name, body, doc=None):
            params = {
                "filename": name,
                "upload_id": str(uuid4()),
                "revision": self.client.get(base).json()["revision"],
            }
            if doc:
                params["document_id"] = doc
            response = self.client.post(
                base + "/upload", params=params, content=body.encode(), headers=test_auth.ORIGIN
            )
            self.assertEqual(response.status_code, 201, response.text)
            return (
                next(d for d in response.json()["documents"] if d["id"] == doc)
                if doc
                else response.json()["documents"][-1]
            )

        target = upload(base, "使用说明.md", "# 目标 v1")
        other_target = upload(other_base, "使用说明.md", "# 不可访问")
        href = "doc/" + quote("使用说明.md")
        source = upload(
            base,
            "README.md",
            f"[使用说明]({href})\n\n[已删除](removed.md)\n\n`[不是链接](fake.md)`",
        )
        source_id = source["current"]["id"]
        endpoint = base + f"/versions/{source_id}/links"
        self.login(self.member_name)
        data = self.client.get(endpoint).json()
        self.assertEqual(len(data["links"]), 2)
        payload = {
            "href": href,
            "target_version_id": target["current"]["id"],
            "revision": data["revision"],
        }
        self.assertEqual(
            self.client.post(
                endpoint,
                json={**payload, "target_version_id": other_target["current"]["id"]},
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                endpoint, json={**payload, "href": "fake.md"}, headers=test_auth.ORIGIN
            ).status_code,
            422,
        )
        self.assertEqual(self.client.post(endpoint, json=payload).status_code, 403)
        self.assertEqual(
            self.client.post(
                endpoint, json={**payload, "target_version_id": source_id}, headers=test_auth.ORIGIN
            ).status_code,
            422,
        )
        response = self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN)
        self.assertEqual(response.status_code, 200, response.text)
        original = response.json()["links"][0]["binding"]
        self.assertEqual(
            self.client.post(endpoint, json=payload, headers=test_auth.ORIGIN).status_code, 409
        )
        # Also bind the soon-to-be-removed link, ensuring it is not copied into the next version.
        data = response.json()
        self.client.post(
            endpoint,
            json={**payload, "href": "removed.md", "revision": data["revision"]},
            headers=test_auth.ORIGIN,
        )
        target2 = upload(base, "使用说明.md", "# 目标 v2", target["id"])
        data = self.client.get(endpoint).json()
        self.assertEqual(data["links"][0]["binding"]["target"]["id"], target["current"]["id"])
        self.assertEqual(data["links"][0]["binding"]["latest_number"], 2)
        newer = upload(base, "README.md", f"[新显示名称]({href})\n\n[新增](new.md)", source["id"])
        new_endpoint = base + f"/versions/{newer['current']['id']}/links"
        new_links = self.client.get(new_endpoint).json()
        self.assertTrue(new_links["links"][0]["binding"]["inherited"])
        self.assertEqual(new_links["links"][0]["binding"]["target"]["id"], target["current"]["id"])
        self.assertIsNone(new_links["links"][1]["binding"])
        self.assertFalse(self.client.get(endpoint).json()["editable"])
        self.assertEqual(
            self.client.post(
                endpoint,
                json={**payload, "revision": new_links["revision"]},
                headers=test_auth.ORIGIN,
            ).status_code,
            409,
        )
        response = self.client.post(
            new_endpoint,
            json={
                **payload,
                "revision": new_links["revision"],
                "target_version_id": target2["current"]["id"],
            },
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["links"][0]["binding"]["target"]["id"], target2["current"]["id"]
        )
        self.assertEqual(
            self.client.get(endpoint).json()["links"][0]["binding"]["id"], original["id"]
        )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            history = list(
                db.scalars(
                    select(DocumentLinkBinding)
                    .where(DocumentLinkBinding.source_version_id == newer["current"]["id"])
                    .order_by(DocumentLinkBinding.revision)
                )
            )
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0].target_version_id, target["current"]["id"])
            self.assertEqual(history[1].target_version_id, target2["current"]["id"])
        changed = upload(base, "README.md", "[使用说明](changed.md)", source["id"])
        self.assertIsNone(
            self.client.get(base + f"/versions/{changed['current']['id']}/links").json()["links"][
                0
            ]["binding"]
        )
