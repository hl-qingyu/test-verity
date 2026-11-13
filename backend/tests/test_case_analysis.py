import copy
import hashlib
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import test_case_generation

from app.core.errors import AppError
from app.db.models import CaseAnalysisRun, UserAccount
from app.modules.case_analysis import apply, contract, execution, schemas, service
from app.modules.cases import service as cases
from app.modules.cases.schemas import CaseValues


def report(case_id=1):
    f = {
        "key": "F1",
        "kind": "QUALITY",
        "title": "预期不明确",
        "severity": "中",
        "reason": "无法判断实际结果",
        "description": "仅写操作正常",
        "impact": "容易误判",
        "suggestion": "补充可观察状态",
        "case_ids": [case_id],
        "fields": ["expected"],
        "evidence": [],
    }
    return {"findings": [f], "notes": [], "checked_case_ids": [case_id], "complete": True}


class ReviewContractTests(unittest.TestCase):
    def test_scope_quote_and_quality_boundaries(self):
        data = {
            "cases": [{"id": 1}],
            "materials": [{"source_id": "M1", "segments": [{"text": "拒绝操作"}]}],
            "mode": "QUALITY",
        }
        self.assertTrue(contract.validate(data, report())["complete"])
        for change in (
            {"case_ids": [2]},
            {"fields": ["result"]},
            {"kind": "MISMATCH"},
            {"evidence": [{"source": "M1", "quote": "允许"}]},
        ):
            bad = report()
            bad["findings"][0].update(change)
            with self.assertRaises(AppError):
                contract.validate(data, bad)
        bad = report()
        bad["checked_case_ids"] = [1, 1]
        with self.assertRaises(AppError):
            contract.validate(data, bad)

    def test_attachment_observation_does_not_forge_a_text_quote(self):
        data = {
            "cases": [{"id": 1}],
            "mode": "COMPARE",
            "materials": [{"source_id": "M1", "segments": [{"text": "", "image_ref": "M1"}]}],
        }
        value = report()
        value["findings"][0].update(
            kind="MISMATCH",
            evidence=[{"source": "M1", "observation": "页面展示不可核销状态，待人工核对"}],
        )
        self.assertTrue(contract.validate(data, value)["findings"][0]["evidence"][0]["observation"])
        data["materials"][0]["segments"][0]["image_ref"] = ""
        with self.assertRaises(AppError):
            contract.validate(data, value)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL")
class ReviewDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_case_generation.GenerationDatabaseTests.setUpClass.__func__)
    factory = test_case_generation.GenerationDatabaseTests.factory
    login = test_case_generation.GenerationDatabaseTests.login
    configuration = test_case_generation.GenerationDatabaseTests.configuration

    def setUp(self):
        test_case_generation.GenerationDatabaseTests.setUp(self)
        self.review_patches = [
            patch.object(m, "analysis_configuration", side_effect=self.configuration)
            for m in (service, execution)
        ]
        for p in self.review_patches:
            p.start()
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            library = cases.lock(self.project, actor, db)
            c = cases.insert_case(
                self.project,
                library,
                CaseValues(title="合成用例", steps="提交订单", expected="操作正常"),
                actor,
                db,
                category_id=None,
                request_id=str(uuid4()),
                result="通过",
                tester="旧人员",
            )
            self.case_id = c.id
            db.commit()

    def tearDown(self):
        for p in self.review_patches:
            p.stop()
        test_case_generation.GenerationDatabaseTests.tearDown(self)

    def test_prepare_preserves_large_text_and_attachment_size_without_starting_ai(self):
        content = "rule\n" * (contract.LIMIT // 5 + 1)
        original = service.sources.read_material

        def read_large(*args, **kwargs):
            material, binding = original(*args, **kwargs)
            material["segments"] = [
                {"segment_id": "large", "location": "全文", "text": content, "image_ref": ""}
            ]
            material["content_sha256"] = hashlib.sha256(content.encode()).hexdigest()
            return material, binding

        attachment = SimpleNamespace(stat=lambda: SimpleNamespace(st_size=contract.LIMIT + 1))
        with (
            self.factory() as db,
            patch.object(service.sources, "read_material", side_effect=read_large),
            patch.object(
                service.sources, "binaries", return_value=[(attachment, "pdf", "M1", "large.pdf")]
            ),
            patch.object(execution.responses, "analyze") as upstream,
        ):
            actor = db.get(UserAccount, self.member_id)
            payload = schemas.Prepare(
                request_id=uuid4(),
                title="合成大输入检查",
                mode="COMPARE",
                case_ids=[self.case_id],
                materials=[{"document_id": self.document_id, "version": str(self.version_id)}],
            )
            result = service.prepare(self.project, payload, actor, db)
            row = db.get(CaseAnalysisRun, result["id"])
            self.assertEqual(row.status, "PREPARED")
            self.assertEqual(row.input_snapshot["materials"][0]["segments"][0]["text"], content)
            self.assertEqual(row.metadata_snapshot["attachment_bytes"], contract.LIMIT + 1)
        upstream.assert_not_called()

    def test_prepare_worker_handling_and_application_history(self):
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            payload = schemas.Prepare(
                request_id=uuid4(), title="合成质量检查", mode="QUALITY", case_ids=[self.case_id]
            )
            row = service.prepare(self.project, payload, actor, db)
            self.assertEqual(row["status"], "PREPARED")
            fixed_skill = db.get(CaseAnalysisRun, row["id"]).metadata_snapshot["skill"]
            self.assertEqual(fixed_skill["version"], "1.0.1")
            self.assertIn("前置条件", fixed_skill["instructions"])
            self.assertIn("通常每项1–2句", fixed_skill["instructions"])
            self.assertEqual(
                fixed_skill["sha256"],
                hashlib.sha256(fixed_skill["instructions"].encode()).hexdigest(),
            )
            self.assertEqual(service.prepare(self.project, payload, actor, db)["id"], row["id"])
            started = service.start(
                self.project, row["id"], schemas.Confirm(revision=1, confirmed=True), actor, db
            )
            self.assertEqual(started["status"], "QUEUED")
            key = execution.claim(db)
        with patch.object(
            execution.responses, "analyze", return_value=json.dumps(report(self.case_id))
        ):
            execution.execute(key, self.factory)
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            done = service.detail(self.project, key, actor, db)
            self.assertEqual(done["status"], "COMPLETED", done["error_code"])
            self.assertEqual(done["outcome"], "COMPLETE")
            self.assertTrue(done["attempts"][0]["raw_response"])
            original = copy.deepcopy(done["report"])
            design = {f: done["input"]["cases"][0][f] for f in cases.DESIGN_FIELDS}
            design["expected"] = "订单状态变为已提交"
            handled = service.handling(
                self.project,
                key,
                schemas.Handling(
                    revision=done["revision"],
                    key="F1",
                    state="已确认待处理",
                    comment="核对合成依据",
                    draft=design,
                    evidence_checked=True,
                    target_version=1,
                ),
                actor,
                db,
            )
            self.assertEqual(handled["report"], original)
            app = schemas.Application(
                request_id=uuid4(), confirmed=True, items=[{"key": "F1", "draft_revision": 1}]
            )
            submitted = apply.submit(self.project, key, app, actor, db)
            aid = submitted["applications"][0]["id"]
            self.assertEqual(
                apply.submit(self.project, key, app, actor, db)["applications"][0]["id"], aid
            )
            execution.claim_application(db)
        apply.execute(aid, self.factory)
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            updated = cases.detail(self.project, self.case_id, actor, db)
            self.assertEqual(len(updated["versions"]), 2)
            current = db.execute(cases.case_query(self.project)).mappings().first()
            self.assertEqual(current["result"], "未测")
            self.assertEqual(current["tester"], "")
            self.assertEqual(current["review_status"], "已审核")
            final = service.detail(self.project, key, actor, db)
            self.assertEqual(final["report"], original)
            self.assertEqual(final["handling"]["F1"]["state"], "已确认待处理")
            self.assertEqual(final["applications"][0]["items"][0]["status"], "SUCCESS")
            closed = service.handling(
                self.project,
                key,
                schemas.Handling(
                    revision=final["revision"], key="F1", state="已解决", comment="人工复核后关闭"
                ),
                actor,
                db,
            )
            self.assertEqual(closed["handling"]["F1"]["state"], "已解决")
            self.assertEqual(closed["report"], original)
            self.assertEqual(service.listing(self.project, actor, db, 1)["items"][0]["id"], key)
            self.assertNotIn("input", service.summary(self.project, key, actor, db))

    def test_failed_candidate_preserved_and_retry_fixed_input(self):
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            row = service.prepare(
                self.project,
                schemas.Prepare(
                    request_id=uuid4(), title="失败合成", mode="QUALITY", case_ids=[self.case_id]
                ),
                actor,
                db,
            )
            service.start(
                self.project, row["id"], schemas.Confirm(revision=1, confirmed=True), actor, db
            )
            key = execution.claim(db)
        with patch.object(execution.responses, "analyze", return_value=json.dumps(report(999999))):
            execution.execute(key, self.factory)
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            failed = service.detail(self.project, key, actor, db)
            self.assertEqual(failed["status"], "FAILED")
            self.assertTrue(failed["attempts"][0]["raw_response"])
            retry = service.retry(self.project, key, uuid4(), actor, db)
            self.assertEqual(retry["input"]["cases"], failed["input"]["cases"])
            self.assertEqual(retry["status"], "PREPARED")
            self.assertFalse(retry["report"])
            self.assertIsNotNone(db.get(CaseAnalysisRun, key))

    def test_zero_scope_materials_import_and_chat_are_separate(self):
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            payload = schemas.Prepare(
                request_id=uuid4(),
                title="零用例对照",
                mode="COMPARE",
                case_ids=[],
                zero_confirmed=True,
                materials=[{"document_id": self.document_id, "version": str(self.version_id)}],
            )
            row = service.prepare(self.project, payload, actor, db)
            self.assertEqual(row["input"]["cases"], [])
            self.assertTrue(row["input"]["materials"][0]["segments"])
            self.assertTrue(row["input"]["materials"][0]["version"])
            empty = {"findings": [], "notes": [], "checked_case_ids": [], "complete": True}
            imported = service.import_report(
                self.project, schemas.Import(input=row["input"], report=empty), actor, db
            )
            self.assertEqual(imported["status"], "COMPLETED")
            forged = copy.deepcopy(row["input"])
            forged["cases"] = [{"id": self.case_id}]
            with self.assertRaises(AppError):
                service.import_report(
                    self.project, schemas.Import(input=forged, report=empty), actor, db
                )
            queued = service.chat(
                self.project,
                row["id"],
                schemas.Chat(request_id=uuid4(), question="哪些业务待明确？"),
                actor,
                db,
            )
            turn = execution.claim_chat(db)
            self.assertEqual(queued["chat"][0]["status"], "QUEUED")
        with patch.object(
            execution.responses, "converse", return_value="合成回复：需要业务确认有效期"
        ):
            execution.execute_chat(turn, self.factory)
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            current = service.detail(self.project, row["id"], actor, db)
            self.assertEqual(current["chat"][0]["status"], "COMPLETED")
            manual = schemas.FromChat(
                revision=current["revision"],
                turn_id=turn,
                finding={
                    **report(self.case_id)["findings"][0],
                    "key": "M1",
                    "kind": "QUESTION",
                    "case_ids": [],
                },
            )
            added = service.from_chat(self.project, row["id"], manual, actor, db)
            self.assertEqual(len(added["manual"]), 1)
            self.assertEqual(added["report"], empty)
            self.assertEqual(
                service.import_report(
                    self.project, schemas.Import(input=row["input"], report=empty), actor, db
                )["manual"],
                added["manual"],
            )

    def test_stale_target_fails_and_next_new_case_succeeds(self):
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            row = service.prepare(
                self.project,
                schemas.Prepare(
                    request_id=uuid4(),
                    title="逐条应用合成",
                    mode="QUALITY",
                    case_ids=[self.case_id],
                ),
                actor,
                db,
            )
            value = report(self.case_id)
            value["findings"].append({**value["findings"][0], "key": "F2"})
            service.import_report(
                self.project, schemas.Import(input=row["input"], report=value), actor, db
            )
            row = service.detail(self.project, row["id"], actor, db)
            d = {f: row["input"]["cases"][0][f] for f in cases.DESIGN_FIELDS}
            d["expected"] = "已提交"
            row = service.handling(
                self.project,
                row["id"],
                schemas.Handling(
                    revision=row["revision"],
                    key="F1",
                    draft=d,
                    evidence_checked=True,
                    target_version=1,
                ),
                actor,
                db,
            )
            # A manually supplemented quality item can produce a new case when it has no target.
            stored = db.get(CaseAnalysisRun, row["id"])
            h = copy.deepcopy(stored.handling)
            h["F2"] = {
                "draft": {**d, "title": "独立新增合成"},
                "draft_revision": 1,
                "target": None,
                "category_id": None,
                "history": [],
            }
            stored.handling = h
            db.commit()
            submitted = apply.submit(
                self.project,
                row["id"],
                schemas.Application(
                    request_id=uuid4(),
                    confirmed=True,
                    items=[{"key": "F1", "draft_revision": 1}, {"key": "F2", "draft_revision": 1}],
                ),
                actor,
                db,
            )
            aid = submitted["applications"][0]["id"]
            execution.claim_application(db)
            c = cases.own_case(self.project, self.case_id, db)
            cases.apply_case_update(
                self.project,
                c,
                CaseValues(title="人工变更", steps="提交", expected="另一个结果"),
                actor,
                db,
            )
            db.commit()
        apply.execute(aid, self.factory)
        apply.execute(aid, self.factory)
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            final = service.detail(self.project, row["id"], actor, db)
            self.assertEqual(
                [i["status"] for i in final["applications"][0]["items"]], ["FAILED", "SUCCESS"]
            )
            self.assertEqual(len(list(db.execute(cases.case_query(self.project)).mappings())), 2)
