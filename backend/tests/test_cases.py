import base64
import io
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import openpyxl
import test_auth

from app.modules.cases.files import read_import
from app.modules.cases.schemas import COLUMNS


class CaseParserTests(unittest.TestCase):
    def test_case_types_are_free_text_but_priority_and_results_remain_validated(self):
        from pydantic import ValidationError

        from app.modules.cases.schemas import CaseInput

        for value in ("业务流程", "自定义端到端回归", ""):
            self.assertEqual(
                CaseInput(case_type=value, revision=0, request_id=uuid4()).case_type, value
            )
        with self.assertRaises(ValidationError):
            CaseInput(case_type="自由类型", priority="P5", revision=0, request_id=uuid4())
        with self.assertRaises(ValidationError):
            CaseInput(case_type="自由类型", result="任意状态", revision=0, request_id=uuid4())

    def test_bad_worksheet_dimensions_do_not_hide_rows_or_validation_errors(self):
        from app.modules.documents.files import preview

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.append(["验证用例子项", "操作步骤", "预期结果"])
            sheet.append(["=1+1", "完整步骤", "结果"])
            sheet.merge_cells("B2:C2")
            stream = io.BytesIO()
            book.save(stream)
            book.close()
            for dimension in ('<dimension ref="A1"/>', "", '<dimension ref="A1:XFD1048576"/>'):
                with (
                    zipfile.ZipFile(io.BytesIO(stream.getvalue())) as original,
                    zipfile.ZipFile(path, "w") as changed,
                ):
                    for item in original.infolist():
                        content = original.read(item.filename)
                        if item.filename == "xl/worksheets/sheet1.xml":
                            content = re.sub(rb"<dimension[^>]*/>", dimension.encode(), content)
                        changed.writestr(item, content)
                data = read_import(path, "xlsx")["sheets"][0]
                self.assertEqual(len(data["rows"]), 2)
                self.assertEqual(data["rows"][0], ["验证用例子项", "操作步骤", "预期结果"])
                self.assertEqual(data["formulas"], [[1, 0]])
                self.assertEqual(data["merges"], [[1, 1, 2, 3]])
                rendered = preview(path, "xlsx")
                self.assertEqual(rendered["kind"], "workbook")
                self.assertEqual(rendered["sheets"][0]["total_rows"], 2)
                self.assertEqual(rendered["sheets"][0]["rows"][1][1], "完整步骤")

    def test_csv_quoted_lines_and_xlsx_formula_and_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture"
            path.write_bytes(
                '用例编号,操作步骤,预期结果\r\nOLD-999,"1.输入,a\n2.提交",成功\r\n'.encode(
                    "gb18030"
                )
            )
            data = read_import(path, "csv")
            self.assertEqual(data["sheets"][0]["rows"][1][1], "1.输入,a\n2.提交")
            book = openpyxl.Workbook()
            sheet = book.active
            sheet.append(["验证用例子项", "操作步骤"])
            sheet.append(["=1+1", "步骤"])
            sheet.merge_cells("B2:C2")
            book.save(path)
            book.close()
            parsed = read_import(path, "xlsx")["sheets"][0]
            self.assertEqual(parsed["formulas"], [[1, 0]])
            self.assertEqual(parsed["merges"], [[1, 1, 2, 3]])
            path.write_bytes(
                base64.b64decode(
                    (Path(__file__).parent / "fixtures/case-import-formula-xls.b64").read_text()
                )
            )
            self.assertEqual(read_import(path, "xls")["sheets"][0]["formulas"], [[1, 1]])


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class CaseDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login

    def setUp(self):
        test_auth.AuthDatabaseTests.setUp(self)
        self.storage = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {"DOCUMENT_STORAGE_PATH": self.storage.name})
        self.environment.start()
        self.login()
        project = self.client.post(
            "/api/projects",
            json={
                "name": "用例验证",
                "identifier": self.prefix + "_cases",
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
        self.base = f"/api/projects/{project['id']}/cases"
        self.other = f"/api/projects/{other['id']}/cases"
        self.login(self.member_name)

    def tearDown(self):
        test_auth.AuthDatabaseTests.tearDown(self)
        self.environment.stop()
        self.storage.cleanup()

    def meta(self):
        return self.client.get(self.base + "/metadata").json()

    def post(self, path, payload):
        return self.client.post(self.base + path, json=payload, headers=test_auth.ORIGIN)

    def test_number_formulas_and_old_previews_cannot_bypass_recheck(self):
        from sqlalchemy.orm import Session

        from app.db.models import CaseImport

        book = openpyxl.Workbook()
        book.active.append(["用例编号", "验证用例子项"])
        book.active.append(["=1+1", "公式编号"])
        content = io.BytesIO()
        book.save(content)
        book.close()
        response = self.client.post(
            self.base + "/imports",
            params={"filename": "numbers.xlsx", "request_id": str(uuid4())},
            content=content.getvalue(),
            headers={**test_auth.ORIGIN, "Content-Type": "application/octet-stream"},
        )
        self.assertEqual(response.status_code, 201, response.text)
        batch = response.json()
        preview = self.post(f"/imports/{batch['id']}/review", {"preview_revision": 0}).json()
        self.assertTrue(any(e["field"] == "number" for e in preview["errors"]))
        info = self.upload_csv("用例编号,验证用例子项\nLogin_001,正常编号\n")
        preview = self.post(f"/imports/{info['id']}/review", {"preview_revision": 0}).json()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            old = db.get(CaseImport, info["id"])
            old.preview = {**old.preview, "mode": "automatic-v2"}
            db.commit()
        response = self.post(
            f"/imports/{info['id']}/confirm",
            {"revision": preview["revision"], "preview_revision": preview["preview_revision"]},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"], "case_preview_changed")
        self.assertEqual(self.post("/search", {}).json()["total"], 0)

    def test_imported_numbers_preserve_text_search_export_and_survive_design_edits(self):
        from app.modules.cases.schemas import DESIGN_FIELDS

        info = self.upload_csv(
            "序号,用例编号,验证用例子项\n90,Login_001,登录\n91,00007,前导零\n92,,空编号\n"
        )
        preview = self.post(f"/imports/{info['id']}/review", {"preview_revision": 0}).json()
        response = self.post(
            f"/imports/{info['id']}/confirm",
            {"revision": preview["revision"], "preview_revision": preview["preview_revision"]},
        )
        self.assertEqual(response.status_code, 200, response.text)
        rows = self.post("/search", {}).json()["items"]
        self.assertEqual([r["number"] for r in rows], ["Login_001", "00007", "3"])
        self.assertEqual([r["serial"] for r in rows], [1, 2, 3])
        found = self.post(
            "/search",
            {"conditions": [{"field": "number", "operator": "equals", "value": "Login_001"}]},
        ).json()
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["items"][0]["id"], rows[0]["id"])
        updated = self.post(
            "/batch-edit",
            {
                "revision": self.meta()["revision"],
                "confirmed": True,
                "mode": "rows",
                "search": {},
                "rows": [{"id": rows[0]["id"], "changes": {"title": "新版登录"}}],
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        detail = self.client.get(self.base + f"/{rows[0]['id']}").json()
        self.assertEqual(detail["number"], "Login_001")
        self.assertEqual(len(detail["versions"]), 2)
        self.assertEqual(detail["versions"][1]["source"]["original_serial"], "90")
        payload = {f: detail["versions"][0][f] for f in DESIGN_FIELDS}
        payload.update(revision=self.meta()["revision"], request_id=str(uuid4()), title="再次编辑")
        self.assertEqual(
            self.client.patch(
                self.base + f"/{rows[0]['id']}", json=payload, headers=test_auth.ORIGIN
            ).json()["number"],
            "Login_001",
        )
        book = openpyxl.load_workbook(io.BytesIO(self.post("/export", {}).content))
        self.assertEqual(
            [book.active.cell(i, 2).value for i in range(2, 5)], ["Login_001", "00007", "3"]
        )
        self.assertEqual(book.active.cell(3, 2).data_type, "s")
        book.close()

    def test_selected_scope_only_changes_selected_ids_and_rejects_invalid_selection(self):
        ids = []
        for i in range(12):
            response = self.post(
                "",
                {
                    "revision": self.meta()["revision"],
                    "request_id": str(uuid4()),
                    "title": f"选择{i}",
                    "tester": "保留",
                },
            )
            ids.append(response.json()["id"])
        scope = {"case_ids": [ids[0], ids[11]]}
        snapshot = self.post("/edit-scope", scope)
        self.assertEqual(snapshot.status_code, 200, snapshot.text)
        self.assertEqual([r["id"] for r in snapshot.json()["items"]], [ids[0], ids[11]])
        self.assertEqual(self.post("/edit-scope", {"case_ids": []}).status_code, 422)
        self.assertEqual(self.post("/edit-scope", {"case_ids": [ids[0], ids[0]]}).status_code, 422)
        self.assertEqual(
            self.post("/edit-scope", {"case_ids": [ids[0], 999999999]}).status_code, 409
        )
        payload = {
            "revision": snapshot.json()["revision"],
            "confirmed": True,
            "mode": "uniform",
            "search": scope,
            "changes": {"tester": "已选修改"},
        }
        response = self.post("/batch-edit", payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"], 2)
        rows = self.post("/edit-scope", {}).json()["items"]
        self.assertEqual([r["id"] for r in rows if r["tester"] == "已选修改"], [ids[0], ids[11]])
        revision = self.meta()["revision"]
        response = self.post(
            "/batch-edit",
            {
                "revision": revision,
                "confirmed": True,
                "mode": "rows",
                "search": scope,
                "rows": [{"id": ids[1], "changes": {"tester": "越界"}}],
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.meta()["revision"], revision)
        self.post(f"/{ids[11]}/delete", {"revision": revision, "confirmed": True})
        payload["revision"] = self.meta()["revision"]
        self.assertEqual(self.post("/batch-edit", payload).status_code, 409)

    def test_batch_edits_are_scoped_atomic_versioned_and_deleted_cases_keep_history(self):
        from sqlalchemy import select
        from sqlalchemy.orm import Session

        from app.db.models import CaseVersion, ManagedCase

        ids = []
        for i in range(12):
            r = self.post(
                "",
                {
                    "revision": self.meta()["revision"],
                    "request_id": str(uuid4()),
                    "title": f"批量{i}",
                    "module": "目标" if i < 11 else "其他",
                    "priority": "P1",
                    "result": "通过",
                    "tester": "原人员",
                    "data_requirements": "保留隐藏字段",
                },
            )
            self.assertEqual(r.status_code, 201, r.text)
            ids.append(r.json()["id"])
        query = {"conditions": [{"field": "module", "operator": "equals", "value": "目标"}]}
        snapshot = self.post("/edit-scope", query).json()
        self.assertEqual(snapshot["total"], 11)
        revision = snapshot["revision"]
        payload = {
            "confirmed": True,
            "revision": revision,
            "mode": "rows",
            "search": query,
            "rows": [
                {"id": ids[0], "changes": {"title": "新标题"}},
                {"id": ids[10], "changes": {"tester": "新人员"}},
            ],
        }
        invalid = {
            **payload,
            "rows": [payload["rows"][0], {"id": ids[11], "changes": {"title": "越界"}}],
        }
        self.assertEqual(self.post("/batch-edit", invalid).status_code, 404)
        self.assertEqual(self.meta()["revision"], revision)
        self.assertEqual(
            self.client.get(self.base + f"/{ids[0]}").json()["versions"][0]["title"], "批量0"
        )
        invalid = {
            **payload,
            "rows": [payload["rows"][0], {"id": ids[10], "changes": {"priority": "P5"}}],
        }
        self.assertEqual(self.post("/batch-edit", invalid).status_code, 422)
        self.assertEqual(self.post("/batch-edit", {**payload, "confirmed": False}).status_code, 422)
        self.assertEqual(
            self.post("/batch-edit", {**payload, "rows": [payload["rows"][0]] * 2}).status_code, 422
        )
        response = self.post("/batch-edit", payload)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"], 2)
        self.assertEqual(self.post("/batch-edit", payload).status_code, 409)
        detail = self.client.get(self.base + f"/{ids[0]}").json()
        self.assertEqual(len(detail["versions"]), 2)
        self.assertEqual(detail["versions"][0]["data_requirements"], "保留隐藏字段")
        self.assertEqual(
            next(r["result"] for r in detail["versions"][0]["records"] if r["kind"] == "TEST"),
            "未测",
        )
        self.assertEqual(
            next(r["result"] for r in detail["versions"][1]["records"] if r["kind"] == "TEST"),
            "通过",
        )
        self.assertEqual(len(self.client.get(self.base + f"/{ids[10]}").json()["versions"]), 1)
        response = self.post(
            "/batch-edit",
            {
                "confirmed": True,
                "revision": self.meta()["revision"],
                "mode": "uniform",
                "search": query,
                "changes": {"tester": ""},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["updated"], 10)
        rows = self.post("/edit-scope", {}).json()["items"]
        self.assertEqual(rows[-1]["tester"], "原人员")
        self.assertTrue(all(r["tester"] == "" for r in rows[:-1]))
        response = self.post(
            "/batch-edit",
            {
                "confirmed": True,
                "revision": self.meta()["revision"],
                "mode": "uniform",
                "search": {},
                "changes": {"priority": "P4"},
            },
        )
        self.assertEqual(response.json()["updated"], 12)
        self.assertEqual(
            self.client.post(
                self.other + "/batch-edit", json=payload, headers=test_auth.ORIGIN
            ).status_code,
            404,
        )
        revision = self.meta()["revision"]
        self.assertEqual(
            self.post(f"/{ids[0]}/delete", {"revision": revision, "confirmed": False}).status_code,
            422,
        )
        self.assertEqual(
            self.post(
                f"/{ids[0]}/delete", {"revision": revision - 1, "confirmed": True}
            ).status_code,
            409,
        )
        response = self.post(f"/{ids[0]}/delete", {"revision": revision, "confirmed": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(self.base + f"/{ids[0]}").status_code, 404)
        self.assertEqual(self.post("/search", {}).json()["total"], 11)
        book = openpyxl.load_workbook(io.BytesIO(self.post("/export", {}).content))
        self.assertEqual(book.active.max_row, 12)
        book.close()
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            deleted = db.get(ManagedCase, ids[0])
            self.assertIsNotNone(deleted.deleted_at)
            self.assertEqual(deleted.deleted_by, self.member_id)
            self.assertEqual(
                len(list(db.scalars(select(CaseVersion).where(CaseVersion.case_id == ids[0])))), 3
            )
        new = self.post(
            "",
            {"revision": self.meta()["revision"], "request_id": str(uuid4()), "title": "后续用例"},
        )
        self.assertEqual(new.json()["number"], "13")

    def test_deleted_case_does_not_block_category_delete_or_import_duplicate_check(self):
        cat = self.post(
            "/categories", {"name": "删除验证", "revision": self.meta()["revision"]}
        ).json()["categories"][0]["id"]
        created = self.post(
            "",
            {
                "revision": self.meta()["revision"],
                "request_id": str(uuid4()),
                "category_id": cat,
                "title": "删除前标题",
            },
        ).json()
        self.post(
            f"/{created['id']}/delete", {"revision": self.meta()["revision"], "confirmed": True}
        )
        self.assertEqual(self.meta()["categories"][0]["count"], 0)
        self.assertEqual(
            self.post(
                f"/categories/{cat}/delete",
                {"revision": self.meta()["revision"], "confirmed": True},
            ).status_code,
            200,
        )
        upload = self.client.post(
            self.base + "/imports",
            params={"filename": "deleted.csv", "request_id": str(uuid4())},
            content="验证用例子项\n删除前标题\n".encode(),
            headers={**test_auth.ORIGIN, "Content-Type": "application/octet-stream"},
        )
        self.assertEqual(upload.status_code, 201, upload.text)
        batch = upload.json()
        review = self.post(
            f"/imports/{batch['id']}/review", {"preview_revision": batch["preview_revision"]}
        )
        self.assertEqual(review.status_code, 200, review.text)
        self.assertEqual(review.json()["duplicate_count"], 0)

    def test_shared_permissions_numbering_versions_search_export_and_category_delete(self):
        self.assertEqual(self.client.get(self.other + "/metadata").status_code, 404)
        category = self.post("/categories", {"name": "用户端", "revision": self.meta()["revision"]})
        self.assertEqual(category.status_code, 201, category.text)
        cat = category.json()["categories"][0]["id"]
        target = self.post(
            "/categories", {"name": "Web端", "revision": self.meta()["revision"]}
        ).json()["categories"][1]["id"]
        ids = []
        for i in range(12):
            payload = {
                "revision": self.meta()["revision"],
                "request_id": str(uuid4()),
                "category_id": cat,
                "title": f"场景{i}",
                "module": "用户端" if i % 2 else "Web端",
                "priority": "P4",
                "result": "通过",
                "tester": "原测试人员",
                "review_status": "已审核",
                "steps": "1.准备\n2.操作",
                "expected": "场景级结果",
            }
            response = self.post("", payload)
            self.assertEqual(response.status_code, 201, response.text)
            ids.append(response.json()["id"])
            self.assertEqual(response.json()["number"], str(i + 1))
        repeat = self.post("", payload)
        self.assertEqual(repeat.json()["id"], ids[-1])
        data = self.post("/search", {"page": 2, "page_size": 10}).json()
        self.assertEqual(data["total"], 12)
        self.assertEqual([r["number"] for r in data["items"]], ["11", "12"])
        self.assertEqual(data["items"][0]["serial"], 11)
        filtered = self.post(
            "/search",
            {
                "conditions": [
                    {"field": "module", "operator": "equals", "value": "用户端"},
                    {"field": "priority", "value": "P4"},
                ]
            },
        ).json()
        self.assertEqual(filtered["total"], 6)
        details = self.client.get(self.base + f"/{ids[0]}").json()
        old = details["versions"][0]
        update = {
            k: old[k]
            for k in (
                "module",
                "structure",
                "case_type",
                "priority",
                "description",
                "title",
                "preconditions",
                "steps",
                "expected",
                "remark",
                "data_requirements",
                "cleanup",
            )
        }
        update.update(
            revision=self.meta()["revision"],
            request_id=str(uuid4()),
            category_id=cat,
            title="修改后的用例",
            result="通过",
            tester="旧人员",
            review_status="已审核",
        )
        response = self.client.patch(
            self.base + f"/{ids[0]}", json=update, headers=test_auth.ORIGIN
        )
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()
        self.assertEqual(len(detail["versions"]), 2)
        self.assertEqual(
            next(r for r in detail["versions"][0]["records"] if r["kind"] == "TEST")["result"],
            "未测",
        )
        self.assertEqual(
            next(r for r in detail["versions"][1]["records"] if r["kind"] == "TEST")["result"],
            "通过",
        )
        self.assertEqual(
            self.client.patch(
                self.base + f"/{ids[0]}", json=update, headers=test_auth.ORIGIN
            ).status_code,
            409,
        )
        update.update(
            revision=self.meta()["revision"], result="失败", tester="新人员", review_status="已审核"
        )
        detail = self.client.patch(
            self.base + f"/{ids[0]}", json=update, headers=test_auth.ORIGIN
        ).json()
        self.assertEqual(len(detail["versions"]), 2)
        self.assertEqual(
            len([r for r in detail["versions"][0]["records"] if r["kind"] == "TEST"]), 2
        )
        self.assertEqual(
            self.post(
                f"/categories/{cat}/delete",
                {"revision": self.meta()["revision"], "confirmed": True},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.post(
                f"/categories/{cat}/delete",
                {"revision": self.meta()["revision"], "confirmed": False, "target_id": target},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.post(
                f"/categories/{cat}/delete",
                {"revision": self.meta()["revision"], "confirmed": True, "target_id": target},
            ).status_code,
            200,
        )
        self.assertEqual(self.post("/search", {"category_id": target}).json()["total"], 12)
        exported = self.post(
            "/export",
            {"conditions": [{"field": "module", "operator": "equals", "value": "用户端"}]},
        )
        self.assertEqual(
            exported.status_code, 200, exported.text[:200] if exported.status_code != 200 else ""
        )
        book = openpyxl.load_workbook(io.BytesIO(exported.content))
        self.assertEqual(book.active.max_row, 7)
        self.assertEqual([c.value for c in book.active[1]], [name for _, name in COLUMNS])
        book.close()

    def upload_csv(self, content):
        response = self.client.post(
            self.base + "/imports",
            params={"filename": "cases.csv", "request_id": str(uuid4())},
            content=content.encode(),
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_automatic_import_blocks_bad_data_and_compares_existing_duplicates(self):
        headers = "序号,用例编号,验证用例子项,优先级,测试结果,操作步骤,用例类型\n"
        body = (
            '99,OLD-999,导入场景,p4,通过,"1.输入,a\n2.提交",业务流程\n'
            "99,OLD-999,第二条,,,,自定义类型\n"
        )
        invalid = self.upload_csv(headers + body.replace("通过", "成功"))
        # An old parser snapshot is repaired on recheck without another upload.
        from sqlalchemy.orm import Session

        from app.db.models import CaseImport

        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            batch = db.get(CaseImport, invalid["id"])
            batch.raw_data = {
                "sheets": [{"name": "CSV", "rows": [["序号"]], "formulas": [], "merges": []}],
                "encoding": "old",
            }
            db.commit()
        data = self.post(f"/imports/{invalid['id']}/review", {"preview_revision": 0}).json()
        self.assertTrue(data["errors"])
        self.assertEqual(
            self.post(
                f"/imports/{invalid['id']}/review",
                {
                    "preview_revision": data["preview_revision"],
                    "value_mappings": {"result": {"成功": "通过"}},
                },
            ).status_code,
            422,
        )
        self.assertEqual(
            self.post(
                f"/imports/{invalid['id']}/confirm",
                {"preview_revision": data["preview_revision"], "revision": data["revision"]},
            ).status_code,
            422,
        )
        self.assertEqual(self.meta()["next_number"], 1)
        info = self.upload_csv(headers + body)
        response = self.post(f"/imports/{info['id']}/review", {"preview_revision": 0})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertFalse(data["errors"])
        self.assertEqual(data["duplicate_count"], 0)
        confirm = {"preview_revision": data["preview_revision"], "revision": data["revision"]}
        result = self.post(f"/imports/{info['id']}/confirm", confirm)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["count"], 2)
        self.assertTrue(
            self.post(f"/imports/{info['id']}/confirm", confirm).json()["already_committed"]
        )
        rows = self.post("/search", {}).json()["items"]
        self.assertEqual([r["number"] for r in rows], ["OLD-999", "OLD-999"])
        self.assertEqual(rows[1]["result"], "")
        self.assertEqual(rows[1]["priority"], "")
        self.assertEqual(rows[0]["steps"], "1.输入,a\n2.提交")
        detail = self.client.get(self.base + f"/{rows[0]['id']}").json()
        self.assertEqual(detail["versions"][0]["source"]["original_number"], "OLD-999")
        # Same design, changed test results: compare with actual system rows, never overwrite them.
        duplicate = self.upload_csv(headers + body.replace("通过", "失败"))
        data = self.post(f"/imports/{duplicate['id']}/review", {"preview_revision": 0}).json()
        self.assertEqual(data["duplicate_count"], 2)
        self.assertEqual(data["items"][0]["matches"][0]["number"], "OLD-999")
        self.assertEqual(data["items"][0]["matches"][0]["result"], "通过")
        self.assertEqual(data["items"][0]["values"]["result"], "失败")
        confirm = {"preview_revision": data["preview_revision"], "revision": data["revision"]}
        self.assertEqual(self.post(f"/imports/{duplicate['id']}/confirm", confirm).status_code, 422)
        choices = {
            item["key"]: ("include" if index == 0 else "skip")
            for index, item in enumerate(data["items"])
        }
        result = self.post(
            f"/imports/{duplicate['id']}/confirm", {**confirm, "duplicate_decisions": choices}
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["count"], 1)
        rows = self.post("/search", {}).json()["items"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["result"], "通过")
        self.assertEqual(rows[2]["result"], "失败")

    def test_automatic_import_checks_all_sheets_formulas_headers_and_stale_preview(self):
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "第一表"
        sheet.append(["验证用例子项", "操作步骤", "预期结果"])
        sheet.append(["合法行", "步骤", "结果"])
        other = book.create_sheet("第二表")
        other.append(["验证用例子项", "操作步骤", "预期结果"])
        other.append(["=1+1", "步骤", "结果"])
        other.merge_cells("B2:C2")
        stream = io.BytesIO()
        book.save(stream)
        book.close()
        info = self.client.post(
            self.base + "/imports",
            params={"filename": "cases.xlsx", "request_id": str(uuid4())},
            content=stream.getvalue(),
            headers=test_auth.ORIGIN,
        ).json()
        data = self.post(f"/imports/{info['id']}/review", {"preview_revision": 0}).json()
        self.assertEqual(len(data["sheets"]), 2)
        self.assertTrue(
            any("公式" in e["message"] and e["sheet"] == "第二表" for e in data["errors"])
        )
        self.assertTrue(any("合并" in e["message"] for e in data["errors"]))
        self.assertEqual(
            self.post(
                f"/imports/{info['id']}/confirm",
                {"preview_revision": data["preview_revision"], "revision": data["revision"]},
            ).status_code,
            422,
        )
        self.assertEqual(self.meta()["next_number"], 1)
        repeated = self.upload_csv("验证用例子项,验证用例子项\n场景,场景\n")
        data = self.post(f"/imports/{repeated['id']}/review", {"preview_revision": 0}).json()
        self.assertTrue(any("表头重复" in e["message"] for e in data["errors"]))
        info = self.upload_csv("验证用例子项,操作步骤\n场景,=literal-text\n")
        data = self.post(f"/imports/{info['id']}/review", {"preview_revision": 0}).json()
        self.post("/categories", {"name": "并发修改", "revision": self.meta()["revision"]})
        self.assertEqual(
            self.post(
                f"/imports/{info['id']}/confirm",
                {"preview_revision": data["preview_revision"], "revision": data["revision"]},
            ).status_code,
            409,
        )
        data = self.post(
            f"/imports/{info['id']}/review", {"preview_revision": data["preview_revision"]}
        ).json()
        self.assertEqual(
            self.post(
                f"/imports/{info['id']}/confirm",
                {"preview_revision": data["preview_revision"], "revision": data["revision"]},
            ).status_code,
            200,
        )
        exported = self.post("/export", {})
        book = openpyxl.load_workbook(io.BytesIO(exported.content), data_only=False)
        self.assertEqual(book.active.cell(2, 10).data_type, "s")
        self.assertEqual(book.active.cell(2, 10).value, "=literal-text")
        book.close()
