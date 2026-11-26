import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_auth
import test_documents
from sqlalchemy.orm import Session
from test_prototypes import PNG

from app.db.models import DocumentVersion, RequirementRule, RequirementSource, SourceDocument


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class MaterialDeletionTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login
    tearDown = test_documents.DocumentDatabaseTests.tearDown

    def setUp(self):
        test_documents.DocumentDatabaseTests.setUp(self)
        self.login()
        p = self.client.post(
            "/api/projects",
            json={"name": "资料删除测试", "identifier": self.prefix, "owner_id": self.admin_id},
            headers=test_auth.ORIGIN,
        ).json()
        self.project_id = p["id"]
        self.client.post(
            f"/api/projects/{p['id']}/members",
            json={"user_id": self.member_id, "version": p["version"]},
            headers=test_auth.ORIGIN,
        )
        self.base = f"/api/projects/{p['id']}/documents"
        self.proto = f"/api/projects/{p['id']}/prototypes"
        self.login(self.member_name)

    def revision(self):
        return self.client.get(self.base).json()["revision"]

    def upload(self, name, content, document_id=None, prototype=False):
        params = {"filename": name, "revision": self.revision(), "upload_id": str(uuid4())}
        if document_id:
            params["document_id"] = document_id
        if prototype:
            params["name"] = name
        r = self.client.post(
            (self.proto if prototype else self.base) + "/upload",
            params=params,
            content=content,
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["sources" if prototype else "documents"][-1]

    def delete(self, base, id):
        info = self.client.get(f"{base}/{id}/deletion")
        self.assertEqual(info.status_code, 200, info.text)
        r = self.client.post(
            f"{base}/{id}/delete",
            json={"revision": info.json()["revision"], "confirmed": True},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(r.status_code, 200, r.text)
        return info.json()

    def test_requirement_deletion_preserves_versions_links_and_existing_evidence(self):
        target = self.upload("需求.txt", "固定依据".encode())
        version = target["current"]["id"]
        source = self.upload("索引.md", b"[requirement](requirement.txt)")
        link_path = f"{self.base}/versions/{source['current']['id']}/links"
        r = self.client.post(
            link_path,
            json={
                "revision": self.revision(),
                "href": "requirement.txt",
                "target_version_id": version,
            },
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(r.status_code, 200, r.text)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            rule = RequirementRule(
                project_id=self.project_id,
                number=1,
                request_id=str(uuid4()),
                title="引用依据",
                action="查看",
                expected="正确",
                status="REVIEW",
                version=1,
                updated_by=self.member_id,
                role="",
                preconditions="",
                question="",
                resolution="",
            )
            db.add(rule)
            db.flush()
            evidence = RequirementSource(
                project_id=self.project_id,
                rule_id=rule.id,
                document_version_id=version,
                role="DOCUMENT",
                location="",
                excerpt="",
            )
            db.add(evidence)
            db.flush()
            evidence_id = evidence.id
            db.commit()
        info = self.delete(self.base, target["id"])
        self.assertEqual(info["requirement_references"], 1)
        self.assertEqual(info["link_references"], 1)
        self.assertNotIn(
            target["id"], [d["id"] for d in self.client.get(self.base).json()["documents"]]
        )
        preview = self.client.get(f"{self.base}/versions/{version}/preview").json()
        self.assertEqual(preview["text"], "固定依据")
        self.assertTrue(preview["deleted"])
        self.assertEqual(
            self.client.get(f"{self.base}/versions/{version}/file").content, "固定依据".encode()
        )
        self.assertTrue(
            self.client.get(link_path).json()["links"][0]["binding"]["target"]["deleted"]
        )
        params = {
            "filename": "新版.txt",
            "document_id": target["id"],
            "revision": self.revision(),
            "upload_id": str(uuid4()),
        }
        self.assertEqual(
            self.client.post(
                self.base + "/upload", params=params, content=b"new", headers=test_auth.ORIGIN
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                self.base + "/move",
                json={"revision": self.revision(), "document_ids": [target["id"]]},
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )
        self.delete(self.base, source["id"])
        self.assertFalse(self.client.get(link_path).json()["editable"])
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            self.assertIsNotNone(db.get(SourceDocument, target["id"]).deleted_at)
            self.assertEqual(db.get(SourceDocument, target["id"]).deleted_by, self.member_id)
            self.assertIsNotNone(db.get(DocumentVersion, version))
            self.assertEqual(db.get(RequirementSource, evidence_id).document_version_id, version)

    def test_prototype_deletion_rejects_wrong_purpose_and_stops_live_checks(self):
        image = self.upload("原型.png", PNG, prototype=True)
        link = self.client.post(
            self.proto,
            json={
                "kind": "LINK",
                "name": "实时页面",
                "url": "https://example.com/prototype",
                "revision": self.revision(),
            },
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(link.status_code, 201, link.text)
        link_id = next(s["id"] for s in link.json()["sources"] if s["kind"] == "LINK")
        self.assertEqual(self.client.get(f"{self.base}/{image['id']}/deletion").status_code, 404)
        self.delete(self.proto, image["id"])
        self.delete(self.proto, link_id)
        self.assertEqual(self.client.get(self.proto).json()["sources"], [])
        self.assertEqual(
            self.client.get(self.base + "?include_prototypes=true").json()["documents"], []
        )
        self.assertEqual(
            self.client.get(f"{self.base}/versions/{image['current']['id']}/file").content, PNG
        )
        with patch("app.modules.prototypes.service.read_scope") as remote:
            self.assertEqual(
                self.client.post(
                    f"{self.proto}/{link_id}/check",
                    json={"connection_id": 1},
                    headers=test_auth.ORIGIN,
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.patch(
                    f"{self.proto}/{link_id}",
                    json={
                        "kind": "LINK",
                        "name": "复活",
                        "url": "https://example.com/",
                        "revision": self.revision(),
                    },
                    headers=test_auth.ORIGIN,
                ).status_code,
                404,
            )
            remote.assert_not_called()

    def test_confirmation_revision_and_project_boundary(self):
        doc = self.upload("待删除.txt", b"keep")
        id = doc["id"]
        rev = self.revision()
        self.assertEqual(
            self.client.post(
                f"{self.base}/{id}/delete",
                json={"revision": rev, "confirmed": False},
                headers=test_auth.ORIGIN,
            ).status_code,
            422,
        )
        self.assertEqual(
            self.client.post(
                f"{self.base}/{id}/delete",
                json={"revision": rev - 1, "confirmed": True},
                headers=test_auth.ORIGIN,
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.get(f"/api/projects/999999/documents/{id}/deletion").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                f"{self.base}/{id}/delete", json={"revision": rev, "confirmed": True}
            ).status_code,
            403,
        )
        self.assertEqual(len(self.client.get(self.base).json()["documents"]), 1)
        self.delete(self.base, id)
        self.assertEqual(
            self.client.post(
                f"{self.base}/{id}/delete",
                json={"revision": self.revision(), "confirmed": True},
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )
