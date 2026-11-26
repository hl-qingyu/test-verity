import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import test_auth
from sqlalchemy.orm import Session
from worker_fixtures import claim as claim_for_execution

from app.core.errors import AppError
from app.db import models as worker_models
from app.db.models import AIConnection, SkillChatTurn, UserAccount
from app.modules.skills import execution, files, schemas, service


class LocalFiles:
    def add_runtime_rules(self):
        folder = self.root / "case-generation"
        (folder / "references").mkdir(exist_ok=True)
        (folder / "references/design.md").write_text(
            "# Design rules\nOriginal rules", encoding="utf-8"
        )
        value = {
            "schema_version": 1,
            "instructions": ["SKILL.md", "references/design.md", "contract.md"],
        }
        (folder / "resources.json").write_text(json.dumps(value), encoding="utf-8")
        return value

    def setup_files(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name) / "skill"
        root.mkdir()
        for key in files.REGISTRY:
            directory = root / key
            directory.mkdir()
            (directory / "SKILL.md").write_bytes(
                b'---\r\nname: fixed\r\nmetadata:\r\n  version: "1.0.0"\r\n---\r\n\r\n'
                b"# Body\r\nOriginal\r\n"
            )
            contract_heading = (
                (files.ROOT / key / "contract.md").read_text(encoding="utf-8").splitlines()[0]
            )
            (directory / "contract.md").write_text(
                contract_heading + "\n\n# Fixed contract", encoding="utf-8"
            )
            (directory / "evaluation.md").write_text("# Reference", encoding="utf-8")
        self.root = root
        self.patches = [
            patch.object(files, "ROOT", root),
            patch.object(files, "BACKUPS", Path(self.temp.name) / "backups"),
        ]
        for p in self.patches:
            p.start()

    def cleanup_files(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()


class SkillFilesTests(LocalFiles, unittest.TestCase):
    setUp = LocalFiles.setup_files
    tearDown = LocalFiles.cleanup_files

    def payload(self, body="Updated\n"):
        return schemas.Save(
            request_id=uuid4(), expected_token=files.bundle("case-generation")["token"], body=body
        )

    def test_backup_preserves_metadata_contract_and_replay_is_idempotent(self):
        key = "case-generation"
        old = (self.root / key / "SKILL.md").read_bytes()
        p = self.payload()
        saved = files.write_body(key, p, 7)
        new = (self.root / key / "SKILL.md").read_bytes()
        self.assertEqual(files.parts(old.decode())[0], files.parts(new.decode())[0])
        self.assertTrue(new.endswith(b"Updated\r\n"))
        self.assertEqual(next(files.BACKUPS.glob("*.before")).read_bytes(), old)
        self.assertTrue(
            (self.root / key / "contract.md")
            .read_text(encoding="utf-8")
            .endswith("# Fixed contract")
        )
        self.assertEqual(files.write_body(key, p, 7)["token"], saved["token"])
        self.assertEqual(len(list(files.BACKUPS.glob("*.before"))), 1)
        with self.assertRaises(AppError):
            files.write_body(key, p, 8)
        files.write_body(
            key,
            schemas.Save(
                request_id=uuid4(), expected_token=saved["token"], body=files.parts(old.decode())[1]
            ),
            7,
        )
        self.assertEqual((self.root / key / "SKILL.md").read_bytes(), old)
        with self.assertRaises(AppError):
            files.write_body(key, p, 7)

    def test_stale_save_and_interrupted_replacement_never_destroy_current_file(self):
        p = self.payload()
        old = (self.root / "case-generation/SKILL.md").read_bytes()
        real_replace = os.replace

        def fail_target(source, target):
            if Path(target).name == "SKILL.md":
                raise OSError("synthetic failure")
            real_replace(source, target)

        with patch.object(files.os, "replace", side_effect=fail_target):
            with self.assertRaises(AppError):
                files.write_body("case-generation", p, 7)
        self.assertEqual((self.root / "case-generation/SKILL.md").read_bytes(), old)
        files.write_body("case-generation", p, 7)
        with self.assertRaises(AppError):
            files.write_body(
                "case-generation",
                schemas.Save(request_id=uuid4(), expected_token=p.expected_token, body="Other"),
                7,
            )
        self.assertEqual(
            files.parts((self.root / "case-generation/SKILL.md").read_text())[1], "Updated\n"
        )

    def test_only_registered_files_are_read_and_snapshot_is_immutable(self):
        with self.assertRaises(AppError):
            files.bundle("../requirements")
        with self.assertRaises(AppError):
            service.read_file("case-generation", "../../secret")
        original = files.snapshot("case-generation")
        self.assertEqual(original["version"], "1.0.0")
        files.write_body("case-generation", self.payload(), 7)
        self.assertIn("Original", original["instructions"])
        self.assertNotEqual(original["sha256"], files.snapshot("case-generation")["sha256"])
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("not readable", encoding="utf-8")
        link = self.root / "case-generation/link.md"
        try:
            link.symlink_to(outside)
        except OSError:
            return
        with self.assertRaises(AppError):
            files.bundle("case-generation")

    def test_all_analysis_snapshots_check_contract_versions(self):
        for key, (_, version, _) in files.REGISTRY.items():
            with self.subTest(skill=key):
                frozen = files.snapshot(key)
                self.assertEqual(frozen["contract_version"], version)
                with self.assertRaisesRegex(AppError, "skill_contract_mismatch"):
                    files.verify_snapshot_contract({**frozen, "contract_version": version + 1})
                target = self.root / key / "contract.md"
                original = target.read_text(encoding="utf-8")
                heading = original.splitlines()[0]
                target.write_text(
                    original.replace(heading, heading.replace(str(version), str(version + 1)), 1),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(AppError, "skill_contract_mismatch"):
                    files.snapshot(key)

    def test_ai_output_retains_unicode_and_rejects_structure_or_metadata_changes(self):
        text = json.dumps(
            {"message": "建议人工核对", "body": "# 新正文\n保留证据"}, ensure_ascii=False
        )
        self.assertIn("保留证据", execution.parse_answer(text).body)
        for bad in (
            '{"message":"x","body":"y","body":"z"}',
            '{"message":"x"}',
            '{"message":"x","body":""}',
            '{"message":"x","body":"y","path":"secret"}',
            json.dumps({"message": "x", "body": "---\nname: evil\n---\nbody"}),
        ):
            with self.assertRaises(AppError):
                execution.parse_answer(bad)

    def test_runtime_manifest_freezes_order_contents_and_hashes_without_extra_files(self):
        manifest = self.add_runtime_rules()
        frozen = files.snapshot("case-generation")
        self.assertEqual([f["path"] for f in frozen["files"]], manifest["instructions"])
        self.assertEqual(frozen["sha256"], files.digest(frozen["instructions"]))
        self.assertLess(
            frozen["instructions"].index("Original rules"),
            frozen["instructions"].index("# Fixed contract"),
        )
        self.assertNotIn("# Reference", frozen["instructions"])
        self.assertEqual(json.loads(frozen["resources"]["text"]), manifest)
        target = self.root / "case-generation/references/design.md"
        self.assertEqual(frozen["files"][1]["sha256"], files.digest(target.read_bytes()))
        visible = files.bundle("case-generation")["files"]
        self.assertEqual(
            {f["path"] for f in visible if f["usage"] == "current"}, set(manifest["instructions"])
        )
        target.write_text("# Changed rules", encoding="utf-8")
        self.assertIn("Original rules", frozen["instructions"])
        self.assertNotEqual(frozen["sha256"], files.snapshot("case-generation")["sha256"])
        old = files.snapshot("case-analysis")
        self.assertNotIn("files", old)
        self.assertEqual(
            old["instructions"],
            '---\nname: fixed\nmetadata:\n  version: "1.0.0"\n---\n\n'
            "# Body\nOriginal\n\n\n# CASE_REVIEW 契约1\n\n# Fixed contract",
        )

    def test_runtime_manifest_rejects_missing_duplicate_escaping_and_non_markdown_files(self):
        value = self.add_runtime_rules()
        manifest = self.root / "case-generation/resources.json"
        for paths in (
            [],
            ["SKILL.md", "contract.md", "references/design.md"],
            ["SKILL.md", "references/design.md", "references/design.md", "contract.md"],
            ["SKILL.md", "../secret.md", "contract.md"],
            ["SKILL.md", "references\\design.md", "contract.md"],
            ["SKILL.md", "references/missing.md", "contract.md"],
            ["SKILL.md", "resources.json", "contract.md"],
            ["SKILL.md", 1, "contract.md"],
        ):
            with self.subTest(paths=paths):
                manifest.write_text(json.dumps({**value, "instructions": paths}), encoding="utf-8")
                with self.assertRaises(AppError) as error:
                    files.snapshot("case-generation")
                self.assertEqual(error.exception.detail, "skill_resources_invalid")
        for raw in (
            "{",
            '{"schema_version":1,"schema_version":1,"instructions":[]}',
            '{"schema_version":true,"instructions":["SKILL.md","contract.md"]}',
            "[]",
        ):
            manifest.write_text(raw, encoding="utf-8")
            with self.assertRaises(AppError):
                files.bundle("case-generation")
        manifest.write_text(json.dumps(value), encoding="utf-8")
        (self.root / "case-generation/references/design.md").write_text(" ", encoding="utf-8")
        with self.assertRaises(AppError):
            files.snapshot("case-generation")

    def test_model_context_preserves_frozen_rules_and_legacy_instruction_bytes(self):
        self.add_runtime_rules()
        snapshot = files.snapshot("case-generation")
        (self.root / "case-generation/references/design.md").write_text(
            "New unrelated rules", encoding="utf-8"
        )
        with patch.object(files, "bundle", side_effect=AssertionError("must use frozen files")):
            instructions, messages = files.model_context(snapshot)
        self.assertIn("Original", instructions)
        self.assertIn("# Fixed contract", instructions)
        self.assertNotIn("Original rules", instructions)
        self.assertEqual(
            messages,
            [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "文件：references/design.md\n\n# Design rules\nOriginal rules",
                        }
                    ],
                }
            ],
        )
        self.assertEqual(
            files.model_context({"instructions": "legacy\r\nexact"}), ("legacy\r\nexact", [])
        )
        self.assertNotIn("New unrelated rules", json.dumps(messages))
        snapshot["files"][1]["text"] = "Changed fixed rule"
        with self.assertRaises(AppError):
            files.model_context(snapshot)

    def test_runtime_snapshot_rejects_files_changing_during_read(self):
        self.add_runtime_rules()
        original = Path.read_bytes
        target = self.root / "case-generation/references/design.md"

        def changing(path):
            raw = original(path)
            if path == target:
                target.write_text("Changed during read", encoding="utf-8")
            return raw

        with patch.object(Path, "read_bytes", changing), self.assertRaises(AppError) as error:
            files.snapshot("case-generation")
        self.assertEqual(error.exception.detail, "skill_content_changed")

    def test_declared_manifest_cannot_silently_fall_back_to_two_files(self):
        folder = self.root / "case-generation"
        (folder / "SKILL.md").write_text(
            '---\nmetadata:\n  resources: "resources.json"\n---\nBody', encoding="utf-8"
        )
        with self.assertRaises(AppError) as error:
            files.snapshot("case-generation")
        self.assertEqual(error.exception.detail, "skill_resources_invalid")

    def test_management_cache_reuses_text_but_detects_external_changes_and_expires(self):
        key = "case-generation"
        real_read = Path.read_bytes
        with patch.object(Path, "read_bytes", autospec=True, side_effect=real_read) as read:
            first = files.cached_bundle(key)
            cold_reads = read.call_count
            for _ in range(3):
                cached = files.cached_bundle(key)
                self.assertEqual(cached["token"], first["token"])
            self.assertEqual(read.call_count, cold_reads)
            cached["files"][0]["text"] = "must not mutate the shared cache"
            self.assertNotEqual(
                files.cached_bundle(key)["files"][0]["text"], cached["files"][0]["text"]
            )
            target = self.root / key / "evaluation.md"
            target.write_text("# Changed reference", encoding="utf-8")
            changed = files.cached_bundle(key)
            self.assertNotEqual(changed["token"], first["token"])
            before_expiry = read.call_count
            with patch.object(
                files.time, "monotonic", return_value=files._VIEW_CACHE[key][0] + files.VIEW_TTL + 1
            ):
                files.cached_bundle(key)
            self.assertGreater(read.call_count, before_expiry)
            before_snapshot = read.call_count
            files.snapshot(key)
            self.assertGreater(read.call_count, before_snapshot)

    def test_batched_management_content_uses_known_token_and_save_invalidates_it(self):
        key = "case-generation"
        first = service.detail(key, include_contents=True)
        self.assertEqual(len(first["contents"]), first["file_count"])
        self.assertTrue(
            all(f["key"] == key and f["token"] == first["token"] for f in first["contents"])
        )
        same = service.detail(key, include_contents=True, known_token=first["token"])
        self.assertTrue(same["unchanged"])
        self.assertEqual(same["contents"], [])
        saved = files.write_body(key, self.payload("Updated cached body"), 7)
        updated = service.detail(key, include_contents=True, known_token=first["token"])
        self.assertFalse(updated["unchanged"])
        self.assertEqual(updated["token"], saved["token"])
        self.assertEqual(
            next(f["body"] for f in updated["contents"] if f["path"] == "SKILL.md"),
            "Updated cached body",
        )
        with patch.object(files, "_bundle", wraps=files._bundle) as fresh:
            service.detail(key)
            service.detail(key, include_contents=True, refresh=True)
            self.assertEqual(fresh.call_count, 2)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL")
class SkillDatabaseTests(LocalFiles, unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    login = test_auth.AuthDatabaseTests.login

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def setUp(self):
        test_auth.AuthDatabaseTests.setUp(self)
        self.setup_files()
        self.login()
        with self.factory() as db:
            db.add(
                AIConnection(
                    id=self.admin_id,
                    owner_id=self.admin_id,
                    name="合成配置",
                    base_url="https://api.openai.com/v1",
                    model="synthetic-model",
                    encrypted_key="NOT-A-KEY",
                    version=1,
                    updated_by=self.admin_id,
                )
            )
            db.commit()
        self.ai_patches = [
            patch.object(
                m,
                "analysis_configuration",
                return_value=(
                    {
                        "name": "合成配置",
                        "model": "synthetic-model",
                        "version": 1,
                        "base_url": "https://api.openai.com/v1",
                        "reasoning_effort": "default",
                    },
                    "NOT-A-KEY",
                ),
            )
            for m in (service, execution)
        ]
        for p in self.ai_patches:
            p.start()

    def tearDown(self):
        for p in self.ai_patches:
            p.stop()
        self.cleanup_files()
        test_auth.AuthDatabaseTests.tearDown(self)

    def chat_payload(self, key="case-generation", **extra):
        return {
            "request_id": str(uuid4()),
            "expected_token": files.bundle(key)["token"],
            "body": "Fixed draft",
            "question": "简化说明",
            **extra,
        }

    def test_read_write_origin_and_actual_admin_permissions(self):
        self.login(self.member_name)
        self.assertEqual(self.client.get("/api/skills").status_code, 200)
        self.assertEqual(self.client.get("/api/skills/case-generation").json()["file_count"], 3)
        payload = self.chat_payload()
        self.assertEqual(
            self.client.post(
                "/api/skills/case-generation/chat", json=payload, headers=test_auth.ORIGIN
            ).status_code,
            403,
        )
        save = {k: v for k, v in payload.items() if k != "question"}
        self.assertEqual(
            self.client.put(
                "/api/skills/case-generation/content", json=save, headers=test_auth.ORIGIN
            ).status_code,
            403,
        )
        self.login()
        self.assertEqual(
            self.client.put("/api/skills/case-generation/content", json=save).status_code, 403
        )
        self.assertEqual(
            self.client.put(
                "/api/skills/case-generation/content", json=save, headers=test_auth.ORIGIN
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.put(
                "/api/skills/case-generation/content",
                json={**save, "path": "other.md"},
                headers=test_auth.ORIGIN,
            ).status_code,
            422,
        )
        batched = self.client.get("/api/skills/case-generation?include_contents=true")
        self.assertEqual(batched.status_code, 200)
        self.assertEqual(len(batched.json()["contents"]), 3)
        self.client.post("/api/auth/logout", headers=test_auth.ORIGIN)
        self.assertEqual(
            self.client.get("/api/skills/case-generation?include_contents=true").status_code, 401
        )

    def test_personal_chat_freezes_context_keeps_files_and_isolates_history(self):
        self.add_runtime_rules()
        payload = self.chat_payload()
        url = "/api/skills/case-generation/chat"
        first = self.client.post(url, json=payload, headers=test_auth.ORIGIN)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(
            self.client.post(url, json=payload, headers=test_auth.ORIGIN).json()["id"],
            first.json()["id"],
        )
        with self.factory() as db:
            task = claim_for_execution(db, worker_models.SkillChatTurn)
            row = db.get(SkillChatTurn, task)
            self.assertEqual(row.context["body"], "Fixed draft")
            self.assertEqual(len(row.context["references"]), 3)
        (self.root / "case-generation/references/design.md").write_text(
            "Changed after enqueue", encoding="utf-8"
        )
        source = (self.root / "case-generation/SKILL.md").read_bytes()
        reply = json.dumps({"message": "已简化，请核对", "body": "Updated suggestion"})
        with patch.object(execution.responses, "converse", return_value=reply) as model:
            execution.execute(task, self.factory)
            self.assertEqual(model.call_args.args[1], "synthetic-model")
            self.assertIn("Fixed draft", model.call_args.args[5][0]["content"])
            self.assertIn("Original rules", model.call_args.args[5][0]["content"])
            self.assertNotIn("Changed after enqueue", model.call_args.args[5][0]["content"])
        self.assertEqual((self.root / "case-generation/SKILL.md").read_bytes(), source)
        done = self.client.get(url).json()["items"][0]
        self.assertEqual(done["status"], "COMPLETED")
        self.assertEqual(done["candidate_body"], "Updated suggestion")
        self.assertEqual(self.client.get("/api/skills/code-review/chat").json()["items"], [])
        with self.factory() as db:
            other = UserAccount(
                login_name=self.prefix + "_second",
                display_name="另一管理员",
                password_hash=self.encoded,
                platform_role="ADMIN",
            )
            db.add(other)
            db.flush()
            other_name = other.login_name
            db.commit()
        self.login(other_name)
        self.assertEqual(self.client.get(url).json()["items"], [])
        self.assertEqual(
            self.client.post(url + f"/{task}/cancel", headers=test_auth.ORIGIN).status_code, 404
        )

    def test_cancel_bad_response_and_role_loss_do_not_apply_or_replay(self):
        url = "/api/skills/case-generation/chat"
        p = self.chat_payload()
        first = self.client.post(url, json=p, headers=test_auth.ORIGIN).json()
        with self.factory() as db:
            task = claim_for_execution(db, worker_models.SkillChatTurn)
        self.client.post(url + f"/{task}/cancel", headers=test_auth.ORIGIN)
        with patch.object(execution.responses, "converse", return_value='{"body":"bad"}'):
            execution.execute(task, self.factory)
        self.assertEqual(self.client.get(url).json()["items"][0]["status"], "CANCELLED")
        p = self.chat_payload(last_turn_id=first["id"])
        second = self.client.post(url, json=p, headers=test_auth.ORIGIN).json()
        with self.factory() as db:
            task = claim_for_execution(db, worker_models.SkillChatTurn)
        with patch.object(execution.responses, "converse", return_value='{"body":"bad"}'):
            execution.execute(task, self.factory)
        with self.factory() as db:
            row = db.get(SkillChatTurn, second["id"])
            self.assertEqual(row.status, "FAILED")
            self.assertEqual(row.raw_response, '{"body":"bad"}')
        p = self.chat_payload(last_turn_id=second["id"])
        self.client.post(url, json=p, headers=test_auth.ORIGIN)
        with self.factory() as db:
            task = claim_for_execution(db, worker_models.SkillChatTurn)
            actor = db.get(UserAccount, self.admin_id)
            actor.platform_role = "USER"
            db.commit()
        with patch.object(execution.responses, "converse") as model:
            execution.execute(task, self.factory)
            model.assert_not_called()
        with self.factory() as db:
            self.assertEqual(db.get(SkillChatTurn, task).status, "FAILED")
