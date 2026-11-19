"""Native history selection and rollback-only review/import flow, without paid models."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_case_generation

from app.db.models import CaseGenerationBatch, CaseGenerationChatTurn, CaseGenerationRun
from app.integrations import codex_terminal, native_candidates
from app.modules.case_generation import execution, native_results, native_terminal


def history(path, values):
    records = [{"type": "session_meta", "payload": {"id": "thread-1"}}]
    for i, (text, error) in enumerate(values):
        turn = f"turn-{i}"
        records.extend(
            [
                {"type": "event_msg", "payload": {"type": "task_started", "turn_id": turn}},
                {
                    "timestamp": f"2026-11-17T06:{i:02d}:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "assistant",
                        "phase": "final_answer",
                        "content": [{"text": text}],
                    },
                },
                {
                    "type": "event_msg",
                    "payload": {"type": "task_complete", "turn_id": turn, "error": error},
                },
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )


class NativeHistoryTests(unittest.TestCase):
    def test_only_completed_messages_are_stable_and_preserve_duplicate_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            file = root / "state/sessions/2026/session.jsonl"
            raw = '{"cases":[{"priority":"P2","priority":"P1"}],"notes":[],"complete":false}'
            history(
                file,
                [(raw, None), ("ordinary explanation", None), (raw, {"message": "interrupted"})],
            )
            with patch.object(native_candidates, "directory", return_value=root):
                values = native_candidates.completed_messages(str(uuid4()))
                self.assertEqual(len(values), 2)
                self.assertEqual(values[-1]["text"], raw)
                self.assertEqual(values[-1]["turn_id"], "turn-0")
                identity = values[-1]["id"]
                with file.open("a", encoding="utf-8") as out:
                    out.write("{partial")
                self.assertEqual(native_candidates.completed_messages("unused")[-1]["id"], identity)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class NativeResultsDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_case_generation.GenerationDatabaseTests.setUpClass.__func__)
    login = test_case_generation.GenerationDatabaseTests.login
    factory = test_case_generation.GenerationDatabaseTests.factory
    prepare = test_case_generation.GenerationDatabaseTests.prepare
    post = test_case_generation.GenerationDatabaseTests.post
    configuration = test_case_generation.GenerationDatabaseTests.configuration
    apply_all = test_case_generation.GenerationDatabaseTests.apply_all

    def setUp(self):
        test_case_generation.GenerationDatabaseTests.setUp(self)
        self.native_dir = tempfile.TemporaryDirectory()
        self.directory_patch = patch.object(
            codex_terminal, "directory", return_value=Path(self.native_dir.name)
        )
        self.directory_patch.start()
        self.native_patch = patch.object(
            native_candidates, "directory", return_value=Path(self.native_dir.name)
        )
        self.native_patch.start()

    def tearDown(self):
        self.native_patch.stop()
        self.directory_patch.stop()
        self.native_dir.cleanup()
        test_case_generation.GenerationDatabaseTests.tearDown(self)

    def test_worker_saves_completed_cli_result_while_terminal_is_open(self):
        source = self.prepare(legacy=False)
        raw = '{"cases":[],"notes":[],"complete":false}'
        self.configure(source, [(raw, None), (raw, None), ("解释", None), ('{"cases":[', None)])
        with self.factory() as db:
            batch = db.get(CaseGenerationBatch, source["batches"][0]["id"])
            identity = batch.ai_config["generation_terminal"]["identity"]
            chat = CaseGenerationChatTurn(
                run_id=int(source["id"]),
                actor_id=batch.actor_id,
                request_id=str(uuid4()),
                function_key="",
                finding_key="",
                question="续接",
                status="RUNNING",
                context={
                    "native_terminal": {
                        "generation_bound": True,
                        "identity": identity,
                        "resume": True,
                        "rows": 30,
                        "cols": 110,
                    },
                },
            )
            db.add(chat)
            db.flush()
            chat_id = chat.id
            db.commit()

        def terminal(*args, on_progress, **kwargs):
            on_progress()
            items = self.client.get(self.api + f"/{source['id']}/terminal/results").json()["items"]
            saved = [item for item in items if item["saved"]]
            self.assertEqual(len(saved), 1)
            self.assertEqual(saved[0]["timestamp"], "2026-11-17T06:01:00Z")
            url = f"/{source['id']}/terminal/results/{saved[0]['id']}/save"
            again = self.post(url, {"request_id": str(uuid4()), "confirmed": True})
            self.assertEqual(len(again.json()["nativeRounds"]), 1)

        events = [
            {
                "method": "turn/completed",
                "status": "completed",
                "thread_id": "thread-1",
                "turn_id": f"turn-{i}",
            }
            for i in (1, 2, 3)
        ]
        with (
            patch.object(native_terminal, "require_enabled"),
            patch.object(
                native_terminal,
                "analysis_configuration",
                return_value=(
                    {"base_url": "https://example.com", "model": "test", "reasoning_effort": "low"},
                    "fake-key",
                ),
            ),
            patch.object(codex_terminal, "turn_events", side_effect=[(events, 100), ([], 100)]),
            patch.object(native_terminal.ai_client, "terminal", side_effect=terminal),
        ):
            native_results.execute_chat(chat_id, self.factory)
        with self.factory() as db:
            self.assertEqual(db.get(CaseGenerationChatTurn, chat_id).status, "COMPLETED")
            run = db.get(CaseGenerationRun, int(source["id"]))
            results = list(run.metadata_snapshot["native_results"].values())
            self.assertEqual([item["save_mode"] for item in results], ["AUTO"])

    def test_completed_partial_result_stays_in_original_record_then_uses_existing_apply(self):
        source = self.prepare(legacy=False)
        raw = json.dumps(
            {
                "cases": [
                    {
                        "action": "NEW",
                        "sources": ["M1-current"],
                        "design": {
                            "title": "合成CLI候选",
                            "steps": "提交",
                            "expected": "显示结果",
                            "priority": "P1",
                        },
                    }
                ],
                "notes": [
                    {
                        "kind": "BUSINESS_QUESTION",
                        "sources": ["M1-current"],
                        "text": "未知分支结果待确认",
                    }
                ],
                "complete": False,
            },
            ensure_ascii=False,
        )
        self.configure(
            source, [(raw, None), ("why is complete false?", None), (raw, {"message": "failed"})]
        )
        base = f"/{source['id']}/terminal/results"
        choices = self.client.get(self.api + base)
        self.assertEqual(choices.status_code, 200, choices.text)
        self.assertEqual(len(choices.json()["items"]), 1)
        identity = choices.json()["items"][0]["id"]
        preview = self.client.get(self.api + base + "/" + identity)
        self.assertEqual(preview.json()["valid_cases"], 1)
        payload = {"request_id": str(uuid4()), "confirmed": True}
        with patch.object(
            execution.responses, "analyze", side_effect=AssertionError("no model call")
        ):
            saved = self.post(base + "/" + identity + "/save", payload)
            self.assertEqual(saved.status_code, 200, saved.text)
            result = saved.json()
            self.assertEqual(result["id"], source["id"])
            self.assertEqual(len(result["suggestions"]), 1)
            self.assertEqual(result["outcome"], "PARTIAL")
            again = self.post(base + "/" + identity + "/save", payload)
            self.assertEqual(again.json()["id"], result["id"])
            self.assertEqual(
                self.client.post(self.cases_api + "/search", json={}).json()["total"], 0
            )
            applied = self.apply_all(result)
            self.assertEqual(applied["applications"][-1]["status"], "COMPLETED")
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 1)
        with self.factory() as db:
            original = db.get(CaseGenerationRun, int(source["id"]))
            self.assertEqual(original.status, "COMPLETED")
            self.assertEqual(db.get(CaseGenerationBatch, source["batches"][0]["id"]).report, {})
            stored = db.get(CaseGenerationRun, int(result["id"]))
            self.assertEqual(stored.metadata_snapshot["skill"], original.metadata_snapshot["skill"])
            self.assertEqual(
                stored.metadata_snapshot["native_results"][identity]["source_run_id"],
                int(source["id"]),
            )
        self.login(self.admin_name)
        self.assertEqual(self.client.get(self.api + base).status_code, 403)
        self.assertEqual(self.post(base + "/" + identity + "/save", payload).status_code, 403)

    def test_selection_conflicts_origin_and_project_are_checked_without_library_writes(self):
        source = self.prepare(legacy=False)
        raw = json.dumps({"cases": [], "notes": [], "complete": False})
        self.configure(source, [(raw, None), (raw, None)])
        base = f"/{source['id']}/terminal/results"
        choices = self.client.get(self.api + base).json()["items"]
        self.assertEqual(len(choices), 2)
        first, second = [v["id"] for v in choices]
        payload = {"request_id": str(uuid4()), "confirmed": True}
        url = self.api + base + "/" + first + "/save"
        self.assertEqual(self.client.post(url, json=payload).status_code, 403)
        self.assertEqual(
            self.post(base + "/" + first + "/save", {**payload, "confirmed": False}).status_code,
            422,
        )
        self.assertEqual(self.post(base + "/" + first + "/save", payload).status_code, 200)
        self.assertEqual(self.post(base + "/" + second + "/save", payload).status_code, 409)
        foreign = self.api.replace(f"/projects/{self.project}/", f"/projects/{self.other}/")
        self.assertEqual(self.client.get(foreign + base).status_code, 404)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)

    def test_malformed_generation_json_is_visible_and_saved_for_manual_correction(self):
        source = self.prepare(legacy=False)
        raw = '{"cases":[{"design":'
        self.configure(source, [(raw, None)])
        base = f"/{source['id']}/terminal/results"
        item = self.client.get(self.api + base).json()["items"][0]
        self.assertIsNone(item["complete"])
        saved = self.post(
            base + "/" + item["id"] + "/save", {"request_id": str(uuid4()), "confirmed": True}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["status"], "FAILED")
        self.assertEqual(saved.json()["candidateIssues"][0]["rawJson"], raw)
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)

    def test_two_rounds_have_distinct_review_keys_and_preserve_prior_application(self):
        source = self.prepare(legacy=False)

        def raw(title):
            return json.dumps(
                {
                    "cases": [
                        {
                            "action": "NEW",
                            "sources": ["M1-current"],
                            "design": {"title": title, "steps": "提交", "expected": "显示结果"},
                        }
                    ],
                    "notes": [],
                    "complete": False,
                }
            )

        self.configure(source, [(raw("轮次一"), None), (raw("轮次二"), None)])
        base = f"/{source['id']}/terminal/results"
        values = self.client.get(self.api + base).json()["items"]
        first = values[1]["id"]
        second = values[0]["id"]
        one = self.post(
            base + "/" + first + "/save", {"request_id": str(uuid4()), "confirmed": True}
        ).json()
        self.assertEqual(one["id"], source["id"])
        first_key = one["suggestions"][0]["key"]
        applied = self.apply_all(one, [first_key])
        before = applied["handling"][first_key]
        two = self.post(
            base + "/" + second + "/save", {"request_id": str(uuid4()), "confirmed": True}
        )
        self.assertEqual(two.status_code, 200, two.text)
        two = two.json()
        self.assertEqual(two["id"], source["id"])
        self.assertEqual(len(two["nativeRounds"]), 2)
        self.assertEqual(two["handling"][first_key], before)
        self.assertEqual(len({v["key"] for v in two["suggestions"]}), 2)
        self.assertEqual({v["nativeResultId"] for v in two["suggestions"]}, {first, second})
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 1)
        listings = self.client.get(self.api + base).json()["items"]
        self.assertTrue(all(v["saved"] for v in listings))
        with self.factory() as db:
            from sqlalchemy import func, select

            count = db.scalar(
                select(func.count())
                .select_from(CaseGenerationRun)
                .where(CaseGenerationRun.project_id == self.project)
            )
            self.assertEqual(count, 1)
        repeat = self.post(
            base + "/" + second + "/save", {"request_id": str(uuid4()), "confirmed": True}
        ).json()
        self.assertEqual(len(repeat["nativeRounds"]), 2)

    def test_automatic_generation_result_is_linked_without_duplicating_candidates(self):
        from app.modules.case_generation import contract

        source = self.prepare(legacy=False)
        raw = json.dumps(
            {
                "cases": [
                    {
                        "action": "NEW",
                        "sources": ["M1-current"],
                        "design": {
                            "title": "首次自动结果",
                            "steps": "提交",
                            "expected": "显示结果",
                        },
                    }
                ],
                "notes": [],
                "complete": True,
            }
        )
        self.configure(source, [(raw, None)])
        with self.factory() as db:
            row = db.get(CaseGenerationRun, int(source["id"]))
            batch = db.get(CaseGenerationBatch, source["batches"][0]["id"])
            row.status = batch.status = "COMPLETED"
            batch.report = contract.validate_report(batch.input_snapshot, json.loads(raw))
            batch.attempts = [
                {"request_id": batch.request_id, "actor_id": self.member_id, "candidate": True}
            ]
            execution.save_candidate(batch, raw)
            db.commit()
            original_report = batch.report
        base = f"/{source['id']}/terminal/results"
        identity = self.client.get(self.api + base).json()["items"][0]["id"]
        saved = self.post(
            base + "/" + identity + "/save", {"request_id": str(uuid4()), "confirmed": True}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(len(saved.json()["batches"]), 1)
        self.assertEqual(len(saved.json()["suggestions"]), 1)
        with self.factory() as db:
            self.assertEqual(
                db.get(CaseGenerationBatch, source["batches"][0]["id"]).report, original_report
            )

    def test_old_unreviewed_copy_is_archived_into_the_original_conversation(self):
        import copy

        from app.db.models import UserAccount
        from app.modules.case_generation import contract, native_results

        source = self.prepare(legacy=False)
        raw = json.dumps(
            {
                "cases": [
                    {
                        "action": "NEW",
                        "sources": ["M1-current"],
                        "design": {"title": "旧副本候选", "steps": "提交", "expected": "显示结果"},
                    }
                ],
                "notes": [],
                "complete": False,
            }
        )
        self.configure(source, [(raw, None)])
        with self.factory() as db:
            root = db.get(CaseGenerationRun, int(source["id"]))
            actor = db.get(UserAccount, self.member_id)
            item = native_results.candidates(self.project, root, actor, db)[0]
            original = db.get(CaseGenerationBatch, item["batch_id"])
            legacy = CaseGenerationRun(
                project_id=self.project,
                actor_id=self.member_id,
                request_id=str(uuid4()),
                title="旧独立副本",
                mode=root.mode,
                status="COMPLETED",
                input_snapshot=copy.deepcopy(root.input_snapshot),
                metadata_snapshot={
                    "origin": "IMPORT",
                    "skill": copy.deepcopy(root.metadata_snapshot["skill"]),
                    "bindings": copy.deepcopy(root.metadata_snapshot["bindings"]),
                    "native_result": {
                        **{
                            k: item[k]
                            for k in ("id", "thread_id", "turn_id", "timestamp", "sha256")
                        },
                        "source_run_id": root.id,
                        "source_batch_id": original.id,
                    },
                },
                handling={},
            )
            db.add(legacy)
            db.flush()
            old_id = legacy.id
            old_batch = CaseGenerationBatch(
                run_id=legacy.id,
                actor_id=self.member_id,
                batch_ref=original.batch_ref,
                request_id=original.request_id,
                status="COMPLETED",
                input_snapshot=copy.deepcopy(original.input_snapshot),
                report=contract.validate_report(original.input_snapshot, json.loads(raw)),
                ai_config={},
                attempts=[],
            )
            db.add(old_batch)
            db.flush()
            old_bid = old_batch.id
            execution.save_candidate(old_batch, raw)
            db.commit()
            before = copy.deepcopy(old_batch.report)
        base = f"/{source['id']}/terminal/results/{item['id']}/save"
        with self.factory() as db:
            legacy = db.get(CaseGenerationRun, old_id)
            legacy.handling = {"suggestions": {"existing": []}}
            db.commit()
        blocked = self.post(base, {"request_id": str(uuid4()), "confirmed": True})
        self.assertEqual(blocked.status_code, 409)
        with self.factory() as db:
            legacy = db.get(CaseGenerationRun, old_id)
            self.assertIsNone(legacy.deleted_at)
            legacy.handling = {}
            db.commit()
        saved = self.post(base, {"request_id": str(uuid4()), "confirmed": True})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["id"], source["id"])
        self.assertEqual(len(saved.json()["nativeRounds"]), 1)
        with self.factory() as db:
            old = db.get(CaseGenerationRun, old_id)
            self.assertIsNotNone(old.deleted_at)
            self.assertEqual(
                old.metadata_snapshot["native_result_archive"]["destination_run_id"],
                int(source["id"]),
            )
            self.assertEqual(db.get(CaseGenerationBatch, old_bid).report, before)
            self.assertEqual(
                execution.candidate_path(db.get(CaseGenerationBatch, old_bid)).read_text(
                    encoding="utf-8"
                ),
                raw,
            )
        self.assertEqual(self.client.post(self.cases_api + "/search", json={}).json()["total"], 0)

    def configure(self, source, values):
        with self.factory() as db:
            row = db.get(CaseGenerationRun, int(source["id"]))
            row.status = "FAILED"
            batch = db.get(CaseGenerationBatch, source["batches"][0]["id"])
            batch.status = "FAILED"
            batch.ai_config = {
                "call_mode": "CODEX_EXEC",
                "generation_terminal": {"identity": str(uuid4()), "execution": -batch.id},
            }
            db.commit()
        history(Path(self.native_dir.name) / "state/sessions/2026/session.jsonl", values)

    def test_duplicate_field_is_quarantined_without_losing_other_candidates_or_original(self):
        source = self.prepare(legacy=False)
        raw = (
            '{"cases":[{"action":"NEW","sources":["M1-current"],"design":{"title":"有效'
            '候选","steps":"提交","expected":"成功"}},{"action":"NEW","sources":["M1-curren'
            't"],"design":{"title":"冲突候选","steps":"提交","expected":"成功","priority":"P2'
            '","priority":"P1"}}],"notes":[],"complete":false}'
        )
        self.configure(source, [(raw, None)])
        base = f"/{source['id']}/terminal/results"
        identity = self.client.get(self.api + base).json()["items"][0]["id"]
        preview = self.client.get(self.api + base + "/" + identity).json()
        self.assertEqual((preview["valid_cases"], preview["issues"]), (1, 1))
        saved = self.post(
            base + "/" + identity + "/save", {"request_id": str(uuid4()), "confirmed": True}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        value = saved.json()
        self.assertEqual(len(value["suggestions"]), 1)
        self.assertEqual(value["candidateIssues"][0]["duplicates"][0]["values"], ['"P2"', '"P1"'])
        with self.factory() as db:
            batch = db.get(
                CaseGenerationBatch,
                next(b["id"] for b in value["batches"] if b.get("nativeResultId") == identity),
            )
            self.assertEqual(execution.candidate_path(batch).read_text(encoding="utf-8"), raw)
