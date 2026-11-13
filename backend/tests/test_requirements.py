import os
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

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

    def state(self):
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def write(self, path, payload, method="POST", expected=200):
        r = self.client.request(
            method,
            self.base + path,
            json={"revision": self.state()["revision"], **payload},
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(r.status_code, expected, r.text)
        return r.json()

    def category(self, name, parent=None):
        self.write("/categories", {"name": name, "parent_id": parent}, expected=201)
        return next(
            c["id"]
            for c in self.state()["categories"]
            if c["name"] == name and c["parent_id"] == parent
        )

    def test_delete_empty_and_migrate_category_without_losing_rules(self):
        m = self.category("待删除模块")
        f = self.category("功能点", m)
        target_module = self.category("目标模块")
        target_feature = self.category("接收功能点", target_module)
        rule = self.rule(category_id=f, status="CONFIRMED")
        version = rule["version"]
        self.write(f"/categories/{f}/delete", {"confirmed": False}, expected=422)
        self.write(f"/categories/{f}/delete", {"confirmed": True}, expected=422)
        self.write(f"/categories/{f}/delete", {"confirmed": True, "target_id": f}, expected=422)
        self.write(
            f"/categories/{f}/delete", {"confirmed": True, "target_id": target_module}, expected=422
        )
        before = self.state()["revision"]
        self.category("后续并发分类")
        self.write(
            f"/categories/{f}/delete",
            {"confirmed": True, "target_id": target_feature, "revision": before},
            expected=409,
        )
        self.write(f"/categories/{f}/delete", {"confirmed": True, "target_id": target_feature})
        state = self.state()
        self.assertFalse(any(c["id"] == f for c in state["categories"]))
        saved = next(r for r in state["rules"] if r["id"] == rule["id"])
        self.assertEqual(saved["category_id"], target_feature)
        self.assertEqual(saved["status"], "CONFIRMED")
        self.assertEqual(saved["version"], version)
        child = self.category("子功能", m)
        collision = self.category("子功能", target_module)
        self.write(
            f"/categories/{m}/delete", {"confirmed": True, "target_id": target_module}, expected=409
        )
        self.assertTrue(any(c["id"] == m for c in self.state()["categories"]))
        self.write(f"/categories/{collision}/delete", {"confirmed": True})
        self.write(f"/categories/{m}/delete", {"confirmed": True, "target_id": target_module})
        self.assertEqual(
            next(c for c in self.state()["categories"] if c["id"] == child)["parent_id"],
            target_module,
        )
        self.assertEqual(
            self.client.post(
                f"/api/projects/{self.other}/requirements/categories/{target_module}/delete",
                json={"revision": 0, "confirmed": True},
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )

    def test_delete_modes_include_nested_rules_and_preserve_history(self):
        for mode in ("UNCLASSIFIED", "DELETE"):
            module = self.category(f"模块{mode}")
            feature = self.category("子功能", module)
            direct = self.rule(category_id=module, status="CONFIRMED")
            nested = self.rule(category_id=feature, status="REVIEW")
            self.write(
                f"/categories/{module}/delete",
                {"confirmed": True, "mode": mode, "target_id": feature},
                expected=422,
            )
            event = self.write("/assign", {"rule_id": nested["id"], "category_id": feature})[
                "event_id"
            ]
            result = self.write(f"/categories/{module}/delete", {"confirmed": True, "mode": mode})
            self.assertIsNone(result["event_id"])
            state = self.state()
            self.assertFalse(any(c["id"] in (module, feature) for c in state["categories"]))
            for original in (direct, nested):
                stored = self.connection.execute(
                    text(
                        "SELECT category_id,deleted_at,status,version "
                        "FROM requirement_rule WHERE id=:id"
                    ),
                    {"id": original["id"]},
                ).one()
                self.assertIsNone(stored.category_id)
                self.assertEqual(stored.status, original["status"])
                self.assertEqual(stored.version, original["version"])
                self.assertEqual(stored.deleted_at is not None, mode == "DELETE")
                self.assertEqual(
                    self.connection.scalar(
                        text("SELECT count(*) FROM requirement_history WHERE rule_id=:id"),
                        {"id": original["id"]},
                    ),
                    1,
                )
                self.assertEqual(
                    any(r["id"] == original["id"] for r in state["rules"]), mode == "UNCLASSIFIED"
                )
                if mode == "DELETE":
                    self.assertEqual(
                        self.client.get(self.base + f"/rules/{original['id']}").status_code, 404
                    )
                    self.write(
                        "/assign", {"rule_id": original["id"], "category_id": None}, expected=404
                    )
            if mode == "DELETE":
                self.write(f"/undo/{event}", {}, expected=404)
            history = self.client.get(self.base + "/classification-history").json()
            self.assertEqual(history[0]["after"]["delete_mode"], mode)
            self.assertEqual(len(history[0]["after"]["rules"]), 2)

    def rule(self, **changes):
        data = {
            "request_id": str(uuid4()),
            "title": "取消订单",
            "action": "点击取消",
            "expected": "变为已取消",
            "status": "REVIEW",
            **changes,
        }
        self.write("/rules", data, expected=201)
        return self.state()["rules"][-1]

    def edit(self, row, **changes):
        keys = (
            "request_id",
            "category_id",
            "title",
            "role",
            "preconditions",
            "action",
            "expected",
            "question",
            "resolution",
            "status",
        )
        data = {k: row[k] for k in keys}
        data["sources"] = [
            {k: s[k] for k in ("document_version_id", "role", "location", "excerpt")}
            for s in row["sources"]
        ]
        data.update(changes)
        self.write(f"/rules/{row['id']}", data, method="PATCH")
        return next(r for r in self.state()["rules"] if r["id"] == row["id"])

    def test_categories_moves_undo_and_shared_access(self):
        self.assertEqual(
            self.client.get(f"/api/projects/{self.other}/requirements").status_code, 404
        )
        m = self.category("订单")
        f = self.category("取消", m)
        m2 = self.category("售后")
        f2 = self.category("查询", m)
        self.write("/categories", {"name": "取消", "parent_id": m}, expected=409)
        self.write("/categories", {"name": "错误层级", "parent_id": f}, expected=422)
        row = self.rule(category_id=f, status="CONFIRMED")
        event = self.write("/assign", {"rule_id": row["id"], "category_id": f2})["event_id"]
        moved = self.state()["rules"][0]
        self.assertEqual(moved["status"], "CONFIRMED")
        self.assertEqual(moved["version"], 1)
        edited = self.edit(moved, status="REVIEW", expected="人工调整后的预期")
        self.write(f"/undo/{event}", {})
        restored = self.state()["rules"][0]
        self.assertEqual(restored["category_id"], f)
        self.assertEqual(restored["expected"], edited["expected"])
        self.assertEqual(restored["version"], edited["version"])
        self.write(f"/undo/{event}", {}, expected=409)
        event = self.write("/move", {"category_id": f, "parent_id": m2})["event_id"]
        self.assertEqual(
            next(c for c in self.state()["categories"] if c["id"] == f)["parent_id"], m2
        )
        self.write(f"/undo/{event}", {})
        self.write("/move", {"category_id": f2, "parent_id": m, "before_id": f})
        self.assertLess(
            next(c for c in self.state()["categories"] if c["id"] == f2)["position"],
            next(c for c in self.state()["categories"] if c["id"] == f)["position"],
        )
        self.write(f"/categories/{m2}", {"name": "空分类改名", "parent_id": None}, method="PATCH")
        self.assertTrue(any(c["name"] == "空分类改名" for c in self.state()["categories"]))

    def test_fixed_sources_versions_and_review_boundaries(self):
        doc_revision = self.client.get(self.docs).json()["revision"]
        upload = self.client.post(
            self.docs + "/upload",
            params={
                "filename": "requirement.txt",
                "upload_id": str(uuid4()),
                "revision": doc_revision,
            },
            content="取消订单说明".encode(),
            headers={**test_auth.ORIGIN, "Content-Type": "application/octet-stream"},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        document = self.client.get(self.docs).json()["documents"][0]
        source = {
            "document_version_id": document["current"]["id"],
            "role": "DOCUMENT",
            "location": "第1段",
            "excerpt": "人工摘录",
        }
        row = self.rule(sources=[source], status="NEEDS_INFO", question="是否二次确认？")
        bad = {
            "request_id": str(uuid4()),
            "title": "规则",
            "action": "操作",
            "expected": "预期",
            "status": "CONFIRMED",
            "question": "未解决",
        }
        self.write("/rules", bad, expected=422)
        row = self.edit(row, status="REVIEW", resolution="需要确认", expected="二次确认后取消")
        row = self.edit(row, status="CONFIRMED")
        self.assertEqual(row["version"], 3)
        same = self.edit(row)
        self.assertEqual(same["version"], 3)
        detail = self.client.get(self.base + f"/rules/{row['id']}").json()
        self.assertEqual(len(detail["history"]), 3)
        self.assertEqual(detail["history"][-1]["snapshot"]["status"], "NEEDS_INFO")
        revision = self.client.get(self.docs).json()["revision"]
        response = self.client.post(
            self.docs + "/upload",
            params={
                "filename": "requirement.txt",
                "document_id": document["id"],
                "upload_id": str(uuid4()),
                "revision": revision,
            },
            content=b"new content",
            headers={**test_auth.ORIGIN, "Content-Type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.state()["rules"][0]["sources"][0]["document"]["number"], 1)
        self.write(
            "/rules",
            {**bad, "question": "", "sources": [{**source, "document_version_id": 999999999}]},
            expected=404,
        )

    def test_stale_origin_duplicate_and_actual_comments(self):
        stale = self.state()["revision"]
        self.category("模块")
        self.write("/categories", {"revision": stale, "name": "过期"}, expected=409)
        self.assertEqual(
            self.client.post(
                self.base + "/categories",
                json={"revision": self.state()["revision"], "name": "无来源"},
            ).status_code,
            403,
        )
        row = self.rule()
        self.write(
            "/rules",
            {
                "request_id": row["request_id"],
                "title": "重复",
                "action": "操作",
                "expected": "预期",
                "status": "REVIEW",
            },
            expected=409,
        )
        self.assertEqual(len(self.state()["rules"]), 1)
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
