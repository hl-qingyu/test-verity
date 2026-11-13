import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import test_auth
import test_requirements
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.models import (
    AIConnection,
    CodeAnalysisChatTurn,
    CodeAnalysisTask,
    GitHubConnection,
    GitHubRepository,
    LocalCodeSource,
    ProjectMember,
    ProjectRepository,
    SourceDocument,
    UserAccount,
)
from app.integrations import github
from app.modules.code_analysis import artifacts, chat, contract, execution, service, sources
from app.modules.prototypes import service as prototypes

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/code-review/examples"


def sample(prefix=""):
    return tuple(
        json.loads((EXAMPLES / f"{prefix}{name}.json").read_text(encoding="utf-8"))
        for name in ("input", "output")
    )


class CodeContractTests(unittest.TestCase):
    def test_link_material_accepts_nested_paths_without_bypassing_project_or_source_checks(self):
        row = SourceDocument(
            id=7,
            project_id=3,
            kind="LINK",
            purpose="PROTOTYPE",
            deleted_at=None,
            url="http://127.0.0.1:4173/#page=pages%2Fadmin%2Fedit.html",
        )
        db, actor = Mock(), object()
        db.get.return_value = row
        selection = {
            "document_id": 7,
            "version_id": None,
            "paths": ["admin/docs/edit.html"],
            "snapshot": "a" * 64,
            "url": row.url,
        }
        with patch.object(sources.documents, "access") as access:
            self.assertIs(sources.material_authorization(3, selection, actor, db), row)
            access.assert_called_once_with(3, actor, db)
            for path in ("../edit.html", "admin/../edit.html", "/admin/edit.html"):
                with self.assertRaises(AppError):
                    sources.material_authorization(3, {**selection, "paths": [path]}, actor, db)
            with self.assertRaises(AppError):
                sources.material_authorization(4, selection, actor, db)
            with self.assertRaises(AppError):
                sources.material_authorization(
                    3, {**selection, "url": "http://elsewhere/"}, actor, db
                )

    def test_marker_cleanup_is_allowed_and_other_private_key_content_is_rejected(self):
        data, _ = sample("local-")
        segment = data["sources"][0]["files"][0]["segments"][0]
        segment["text"] += '\nkey = key.replace("-----BEGIN PRIVATE KEY-----", "")'
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        segment["text"] += "\n-----BEGIN PRIVATE KEY-----\n" + "A" * 64
        with self.assertRaises(AppError) as caught:
            contract.validate_input(contract.AnalysisInput.model_validate(data))
        self.assertEqual(caught.exception.detail, "code_private_key_content")

    def test_normalize_only_unique_exact_full_lines(self):
        data, result = sample("local-")
        segment = data["sources"][0]["files"][0]["segments"][0]
        segment["text"] += "\n# following line"
        original = result["evidence"][0]["excerpt"]
        altered = copy.deepcopy(result)
        altered["evidence"][0].update(start_line=2, end_line=4, excerpt=original + "\n")
        parsed = contract.AnalysisInput.model_validate(data)
        normalized, corrections = contract.normalize_code_evidence(
            parsed, contract.Report.model_validate(altered)
        )
        contract.validate_report(parsed, normalized)
        self.assertEqual(normalized.evidence[0].excerpt, original)
        self.assertEqual(
            (normalized.evidence[0].start_line, normalized.evidence[0].end_line), (1, 3)
        )
        self.assertEqual(corrections[0]["evidence_key"], "E1")
        self.assertEqual(altered["evidence"][0]["excerpt"], original + "\n")
        for excerpt in ("invented", original[1:]):
            altered["evidence"][0]["excerpt"] = excerpt
            rejected, changes = contract.normalize_code_evidence(
                parsed, contract.Report.model_validate(altered)
            )
            self.assertEqual(changes, [])
            with self.assertRaises(AppError):
                contract.validate_report(parsed, rejected)
        segment["text"] += "\n" + original
        altered["evidence"][0]["excerpt"] = original + "\n"
        ambiguous = contract.AnalysisInput.model_validate(data)
        rejected, changes = contract.normalize_code_evidence(
            ambiguous, contract.Report.model_validate(altered)
        )
        self.assertEqual(changes, [])
        with self.assertRaises(AppError):
            contract.validate_report(ambiguous, rejected)

    def test_git_code_scope_includes_backend_and_mobile_regular_files(self):
        commit, tree = "a" * 40, "b" * 40

        def remote(token, operation, **kwargs):
            if operation == "repository":
                return {
                    "id": 9,
                    "full_name": "example/server",
                    "default_branch": "main",
                    "private": True,
                    "owner": {"login": "example", "type": "User"},
                }
            if operation == "branch":
                return {"name": "main", "commit": {"sha": commit}}
            if operation == "git_commit":
                self.assertEqual(kwargs["sha"], commit)
                return {"sha": commit, "tree": {"sha": tree}}
            if operation == "tree":
                return {
                    "sha": tree,
                    "truncated": False,
                    "tree": [
                        {"path": path, "type": "blob", "mode": mode, "sha": "c" * 40, "size": 10}
                        for path, mode in (
                            ("src/Main.java", "100644"),
                            ("app/main.dart", "100644"),
                            ("query.sql", "100644"),
                            ("link.py", "120000"),
                            ("binary.png", "100644"),
                        )
                    ],
                }
            self.fail(operation)

        with patch.object(github, "github_get", side_effect=remote):
            for ref in ("main", commit):
                result = github.code_scope("test-token", 9, ref)
                self.assertEqual(result["commit"], commit)
                self.assertEqual(
                    {f["path"] for f in result["files"]},
                    {"src/Main.java", "app/main.dart", "query.sql"},
                )

    def test_strict_documents_and_cross_references(self):
        data, output = sample()
        contract.validate_report(
            contract.AnalysisInput.model_validate(data), contract.Report.model_validate(output)
        )
        for mutate in (
            lambda r: r.update(request_id="foreign"),
            lambda r: r["evidence"][0].update(excerpt="invented"),
            lambda r: r["evidence"][0].update(end_line=99999),
            lambda r: r["evidence"][0].update(source_id="foreign"),
            lambda r: r["findings"][0].update(status="RESOLVED"),
            lambda r: r["target_results"][0].update(finding_refs=[]),
            lambda r: r["coverage"].pop(),
            lambda r: r["chains"][0]["edges"][0].update(evidence_refs=[]),
            lambda r: r["findings"][0]["target_views"][0].update(basis_refs=["missing"]),
        ):
            invalid = copy.deepcopy(output)
            mutate(invalid)
            with self.assertRaises((ValueError, AppError)):
                contract.validate_report(
                    contract.AnalysisInput.model_validate(data),
                    contract.Report.model_validate(invalid),
                )
        for role in ("WEB", "FLUTTER"):
            selected = copy.deepcopy(data)
            selected["sources"] = [
                s for s in selected["sources"] if s["repository_kind"] in (role, "BACKEND")
            ]
            contract.validate_input(contract.AnalysisInput.model_validate(selected))
            selected["sources"] = [s for s in selected["sources"] if s["repository_kind"] == role]
            with self.assertRaises(AppError) as error:
                contract.validate_input(contract.AnalysisInput.model_validate(selected))
            self.assertEqual(error.exception.detail, "code_both_sides_required")
        local, report = sample("local-")
        contract.validate_report(
            contract.AnalysisInput.model_validate(local), contract.Report.model_validate(report)
        )
        report["outcome"] = "COMPLETE"
        with self.assertRaises(AppError):
            contract.validate_report(
                contract.AnalysisInput.model_validate(local), contract.Report.model_validate(report)
            )

    def test_paths_and_json_are_data_not_instructions(self):
        for path in (
            "../file.py",
            "/tmp/a.py",
            "C:/secret.py",
            ".env",
            "app/.env.prod",
            "key.pem",
            "node_modules/a.js",
        ):
            self.assertFalse(contract.safe_path(path), path)
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"):
            with self.assertRaises(AppError):
                service.json_object(raw)


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class CodeAnalysisDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    tearDown = test_requirements.RequirementDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login

    def factory(self):
        return Session(
            self.connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )

    def setUp(self):
        test_requirements.RequirementDatabaseTests.setUp(self)
        self.api = f"/api/projects/{self.project}/code-analysis"
        self.artifact_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.artifact_directory.cleanup)
        self.artifact_patch = patch.object(
            artifacts, "result_directory", return_value=Path(self.artifact_directory.name)
        )
        self.artifact_patch.start()
        self.addCleanup(self.artifact_patch.stop)
        self.input, self.report = sample("local-")
        with self.factory() as db:
            source = LocalCodeSource(
                project_id=self.project,
                owner_id=self.member_id,
                client_id=str(uuid4()),
                name="本地后端",
                directory_name="test-code",
                kind="BACKEND",
            )
            db.add(source)
            for actor_id in (self.member_id, self.admin_id):
                db.add(
                    AIConnection(
                        id=actor_id,
                        owner_id=actor_id,
                        name="本人AI",
                        base_url="https://api.openai.com/v1",
                        model="test-model",
                        encrypted_key="NOT-A-REAL-CREDENTIAL",
                        version=1,
                        updated_by=actor_id,
                    )
                )
            db.commit()
            self.source_id = source.id
        self.config_patches = [
            patch.object(module, "analysis_configuration", side_effect=self.configuration)
            for module in (service, execution, chat)
        ]
        for item in self.config_patches:
            item.start()
            self.addCleanup(item.stop)

    def configuration(self, actor, db, version=None, **kwargs):
        if isinstance(version, dict):
            version = version.get("version")
        current = db.get(UserAccount, actor.id, populate_existing=True)
        if current is None or current.status != "ACTIVE":
            raise AppError(401, "not_authenticated")
        connection = db.get(AIConnection, actor.id, populate_existing=True)
        if version is not None and connection.version != version:
            raise AppError(409, "ai_configuration_changed")
        return {
            "name": "本人AI",
            "base_url": connection.base_url,
            "reasoning_effort": connection.reasoning_effort,
            "model": f"model-{actor.id}",
            "version": connection.version,
        }, f"secret-{actor.id}"

    def payload(self):
        content = self.input["sources"][0]["files"][0]["segments"][0]["text"]
        return {
            "request_id": str(uuid4()),
            "title": "代码分析测试",
            "focus": "函数边界",
            "targets": ["BUG"],
            "sources": [
                {
                    "kind": "LOCAL",
                    "source_id": self.source_id,
                    "source_version": 1,
                    "commit": "",
                    "files": [
                        {
                            "path": "domain.py",
                            "content": content,
                            "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        }
                    ],
                }
            ],
            "materials": [],
        }

    def test_large_input_is_enqueued_and_sent_in_full_without_automatic_retry(self):
        payload = self.payload()
        content = "x" * 2_000_000
        files = [
            {
                "path": f"part{n}.py",
                "content": content,
                "sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
            for n in range(9)
        ]
        payload["sources"][0]["files"] = files
        self.assertGreater(len(json.dumps(payload).encode()), sources.FILE_LIMIT)
        response = self.post("", payload)
        self.assertEqual(response.status_code, 202, response.status_code)
        task_id = response.json()["id"]
        with self.factory() as db:
            self.assertEqual(execution.claim(db), task_id)

        def rejected(*args, **kwargs):
            sent = json.loads(args[5][0]["text"])
            actual = sent["sources"][0]["files"]
            self.assertEqual([f["path"] for f in actual], [f["path"] for f in files])
            self.assertTrue(all(f["segments"][0]["text"] == content for f in actual))
            raise AppError(422, "ai_context_limit")

        with patch("app.integrations.responses.analyze", side_effect=rejected) as upstream:
            execution.execute(task_id, self.factory)
        upstream.assert_called_once()
        with self.factory() as db:
            row = db.get(CodeAnalysisTask, task_id)
            self.assertEqual((row.status, row.error_code), ("FAILED", "ai_context_limit"))
            self.assertEqual(len(row.input_snapshot["sources"][0]["files"]), 9)

    def test_link_material_is_fixed_in_code_input(self):
        url = "https://prototype.geekuat.com/p/Test123/"
        with self.factory() as db:
            source = SourceDocument(
                project_id=self.project,
                purpose="PROTOTYPE",
                kind="LINK",
                name="原型",
                url=url,
                current_version=1,
            )
            db.add(source)
            db.commit()
            source_id = source.id
        payload = self.payload()
        payload["targets"] = ["REQUIREMENT_DEVIATION"]
        payload["materials"] = [
            {
                "document_id": source_id,
                "version_id": None,
                "commit": "",
                "paths": ["page-2.html"],
                "snapshot": "a" * 64,
                "url": url,
            }
        ]
        self.assertEqual(self.post("", payload).status_code, 202)
        with (
            self.factory() as db,
            patch.object(
                prototypes,
                "link_pages",
                return_value={
                    "snapshot_ref": "b" * 64,
                    "segments": [{"location": "首页 · 原型说明", "text": "订单规则"}],
                },
            ) as reader,
        ):
            actor = db.get(UserAccount, self.member_id)
            result, _, _ = sources.prepare(self.project, payload["request_id"], payload, actor, db)
            self.assertEqual(result["materials"][0]["segments"][0]["text"], "订单规则")
            self.assertEqual(result["materials"][0]["read_state"], "PARTIAL")
            reader.assert_called_once()
        with self.factory() as db:
            db.get(SourceDocument, source_id).url = url + "changed"
            db.commit()
        self.assertEqual(self.post("", {**payload, "request_id": str(uuid4())}).status_code, 409)

    def post(self, path, payload):
        return self.client.post(self.api + path, json=payload, headers=test_auth.ORIGIN)

    def import_payload(self):
        return {
            "title": "本地报告",
            "input_filename": "input.json",
            "report_filename": "report.json",
            "input_json": json.dumps(self.input, ensure_ascii=False),
            "report_json": json.dumps(self.report, ensure_ascii=False),
            "bindings": [],
        }

    def running(self, key, model=CodeAnalysisTask):
        with self.factory() as db:
            row = db.get(model, key)
            self.assertEqual(row.status, "QUEUED")
            row.status = "RUNNING"
            db.commit()

    def answer(self, base, model, key, effort, instructions, content, **kwargs):
        self.assertIn("v2", instructions)
        self.assertNotIn("NOT-A-REAL-CREDENTIAL", json.dumps(content))
        kwargs["on_progress"]()
        input_data = json.loads(content[0]["text"])
        result = copy.deepcopy(self.report)
        result.update(request_id=input_data["request_id"], outcome="COMPLETE", limitations=[])
        result["target_results"] = result["target_results"][:1]
        source = input_data["sources"][0]
        result["evidence"][0].update(
            source_id=source["source_id"], file_id=source["files"][0]["file_id"], segment_id="full"
        )
        result["coverage"][0].update(
            source_id=source["source_id"],
            file_id=source["files"][0]["file_id"],
            targets=result["coverage"][0]["targets"][:1],
        )
        return json.dumps(result, ensure_ascii=False)

    def answer_with_shifted_evidence(self, *args, **kwargs):
        result = json.loads(self.answer(*args, **kwargs))
        evidence = result["evidence"][0]
        evidence["start_line"] += 1
        evidence["end_line"] += 1
        evidence["excerpt"] += "\n"
        return json.dumps(result, ensure_ascii=False)

    def payload_with_following_line(self):
        payload = self.payload()
        file = payload["sources"][0]["files"][0]
        file["content"] += "\n# following line"
        file["sha256"] = hashlib.sha256(file["content"].encode()).hexdigest()
        return payload

    def test_import_duplicate_handling_export_and_project_isolation(self):
        with patch("app.integrations.responses.analyze") as upstream:
            response = self.post("/import", self.import_payload())
            self.assertEqual(response.status_code, 201, response.text)
            row = response.json()
            self.assertEqual(row["origin"], "IMPORT")
            self.assertEqual(row["report"]["outcome"], "PARTIAL")
            self.assertEqual(self.post("/import", self.import_payload()).json()["id"], row["id"])
            upstream.assert_not_called()
        handling = self.post(
            f"/{row['id']}/handling",
            {"revision": 1, "finding_key": "F1", "status": "RESOLVED", "note": "人工核查说明"},
        )
        self.assertEqual(handling.status_code, 200, handling.text)
        self.assertEqual(handling.json()["report"], self.report)
        self.assertEqual(handling.json()["revision"], 2)
        self.assertEqual(
            self.post(
                f"/{row['id']}/handling",
                {"revision": 1, "finding_key": "F1", "status": "PENDING", "note": ""},
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.get(f"/api/projects/{self.other}/code-analysis/{row['id']}").status_code,
            404,
        )
        for format in ("input", "report", "markdown"):
            result = self.client.get(f"{self.api}/{row['id']}/export?format={format}")
            self.assertEqual(result.status_code, 200, result.text)
        invalid = self.import_payload()
        bad = copy.deepcopy(self.report)
        bad["evidence"][0]["excerpt"] = "fabricated"
        invalid["report_json"] = json.dumps(bad)
        self.assertEqual(self.post("/import", invalid).status_code, 422)

    def test_queue_fixed_input_v2_validation_and_idempotency(self):
        payload = self.payload()
        first = self.post("", payload)
        self.assertEqual(first.status_code, 202, first.text)
        key = first.json()["id"]
        self.assertEqual(self.post("", payload).json()["id"], key)
        self.assertEqual(self.post("", {**payload, "focus": "changed"}).status_code, 409)
        self.running(key)
        with patch("app.integrations.responses.analyze", side_effect=self.answer) as upstream:
            execution.execute(key, self.factory)
            upstream.assert_called_once()
        record = self.client.get(f"{self.api}/{key}").json()
        self.assertEqual(record["status"], "COMPLETED", record)
        self.assertTrue(record["candidate_available"])
        candidate = self.client.get(f"{self.api}/{key}/candidate")
        self.assertEqual(candidate.status_code, 200, candidate.text)
        self.assertEqual(json.loads(candidate.text), record["report"])
        self.assertEqual(record["input"]["contract_version"], 2)
        self.assertEqual(record["input"]["sources"][0]["repository_kind"], "BACKEND")
        self.assertEqual(record["report"]["findings"][0]["key"], "F1")
        self.assertNotIn(f"secret-{self.member_id}", json.dumps(record))
        self.assertEqual(
            self.client.get(self.api + "/options").json()["local_sources"][0]["kind"], "BACKEND"
        )

    def test_worker_normalizes_exact_candidate_without_changing_raw_file(self):
        task = self.post("", self.payload_with_following_line()).json()
        self.running(task["id"])
        with patch(
            "app.integrations.responses.analyze", side_effect=self.answer_with_shifted_evidence
        ):
            execution.execute(task["id"], self.factory)
        record = self.client.get(f"{self.api}/{task['id']}").json()
        self.assertEqual(record["status"], "COMPLETED")
        self.assertEqual(len(record["evidence_corrections"]), 1)
        self.assertEqual(record["report"]["evidence"][0]["start_line"], 1)
        self.assertFalse(record["report"]["evidence"][0]["excerpt"].endswith("\n"))
        raw = json.loads(artifacts.candidate_path(task["id"]).read_text(encoding="utf-8"))
        self.assertEqual(raw["evidence"][0]["start_line"], 2)
        self.assertTrue(raw["evidence"][0]["excerpt"].endswith("\n"))

    def test_revalidate_saved_candidate_in_place_without_ai_call(self):
        task = self.post("", self.payload_with_following_line()).json()
        self.running(task["id"])
        with (
            patch.object(
                contract, "normalize_code_evidence", side_effect=lambda _, result: (result, [])
            ),
            patch(
                "app.integrations.responses.analyze", side_effect=self.answer_with_shifted_evidence
            ),
        ):
            execution.execute(task["id"], self.factory)
        failed = self.client.get(f"{self.api}/{task['id']}").json()
        self.assertEqual(failed["error_code"], "code_evidence_invalid")
        self.assertTrue(failed["can_revalidate"])
        self.assertEqual(failed["report"], {})
        self.assertEqual(
            self.client.get(f"/api/projects/{self.other}/code-analysis/{task['id']}").status_code,
            404,
        )
        self.login()
        self.assertEqual(self.post(f"/{task['id']}/revalidate", {}).status_code, 403)
        self.login(self.member_name)
        with patch("app.integrations.responses.analyze") as upstream:
            response = self.post(f"/{task['id']}/revalidate", {})
            upstream.assert_not_called()
        self.assertEqual(response.status_code, 200, response.text)
        record = response.json()
        self.assertEqual(
            (record["id"], record["status"], record["revision"]), (task["id"], "COMPLETED", 2)
        )
        self.assertEqual(record["error_code"], "")
        self.assertEqual(len(record["evidence_corrections"]), 1)
        self.assertEqual(self.post(f"/{task['id']}/revalidate", {}).json()["revision"], 2)
        self.assertEqual(
            self.client.get(f"{self.api}/{task['id']}/candidate").json()["evidence"][0][
                "start_line"
            ],
            2,
        )

    def test_missing_side_tampered_content_cancel_and_retry_with_current_actor(self):
        payload = self.payload()
        self.assertEqual(
            self.post("", {**payload, "targets": ["BUG", "FRONTEND_BACKEND_MISMATCH"]}).json()[
                "detail"
            ],
            "code_both_sides_required",
        )
        bad = copy.deepcopy(payload)
        bad["sources"][0]["files"][0]["sha256"] = "0" * 64
        self.assertEqual(self.post("", bad).status_code, 422)
        first = self.post("", payload).json()
        self.login()
        self.assertEqual(self.post(f"/{first['id']}/cancel", {}).status_code, 403)
        self.login(self.member_name)
        self.assertEqual(self.post(f"/{first['id']}/cancel", {}).json()["status"], "CANCELLED")
        with patch("app.integrations.responses.analyze") as upstream:
            execution.execute(first["id"], self.factory)
            upstream.assert_not_called()
        self.login()
        retried = self.post(f"/{first['id']}/retry", {"request_id": str(uuid4())})
        self.assertEqual(retried.status_code, 202, retried.text)
        key = retried.json()["id"]
        self.running(key)
        with patch("app.integrations.responses.analyze", side_effect=self.answer) as upstream:
            execution.execute(key, self.factory)
            self.assertEqual(upstream.call_args.args[2], f"secret-{self.admin_id}")
        self.assertEqual(self.client.get(f"{self.api}/{key}").json()["status"], "COMPLETED")

    def test_invalid_model_output_and_access_revocation_never_store_success(self):
        first = self.post("", self.payload()).json()
        self.running(first["id"])
        raw = '{"contract_version":1,"diagnostic":"preserve exact response"}'
        with patch("app.integrations.responses.analyze", return_value=raw):
            execution.execute(first["id"], self.factory)
        record = self.client.get(f"{self.api}/{first['id']}").json()
        self.assertEqual(record["status"], "FAILED")
        self.assertEqual(record["report"], {})
        self.assertTrue(record["candidate_available"])
        candidate = self.client.get(f"{self.api}/{first['id']}/candidate")
        self.assertEqual(candidate.content.decode(), raw)
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.other}/code-analysis/{first['id']}/candidate"
            ).status_code,
            404,
        )
        missing = self.post("", self.payload()).json()
        self.running(missing["id"])
        with patch(
            "app.integrations.responses.analyze", side_effect=AppError(502, "ai_connection_failed")
        ):
            execution.execute(missing["id"], self.factory)
        missing_record = self.client.get(f"{self.api}/{missing['id']}").json()
        self.assertFalse(missing_record["candidate_available"])
        self.assertEqual(self.client.get(f"{self.api}/{missing['id']}/candidate").status_code, 404)
        other = self.post("", self.payload()).json()
        self.running(other["id"])
        with self.factory() as db:
            db.delete(db.get(ProjectMember, (self.project, self.member_id)))
            db.commit()
        with patch("app.integrations.responses.analyze") as upstream:
            execution.execute(other["id"], self.factory)
            upstream.assert_not_called()
        self.assertEqual(self.client.get(f"{self.api}/{other['id']}").status_code, 404)
        with self.factory() as db:
            self.assertEqual(db.get(CodeAnalysisTask, other["id"]).status, "FAILED")

    def test_independent_chat_history_and_report_immutable(self):
        record = self.post("/import", self.import_payload()).json()
        endpoint = f"/{record['id']}/chat"
        question = {"request_id": str(uuid4()), "question": "解释F1", "finding_key": "F1"}
        first = self.post(endpoint, question)
        self.assertEqual(first.status_code, 202, first.text)
        self.assertEqual(self.post(endpoint, question).json()["id"], first.json()["id"])
        self.assertEqual(
            self.post(endpoint, {**question, "request_id": str(uuid4())}).status_code, 409
        )
        self.running(first.json()["id"], CodeAnalysisChatTurn)
        with patch(
            "app.integrations.responses.converse", return_value="固定代码中的索引路径需要修复。"
        ) as upstream:
            execution.execute_chat(first.json()["id"], self.factory)
            self.assertEqual(upstream.call_args.args[2], f"secret-{self.member_id}")
        history = self.client.get(self.api + endpoint).json()["items"]
        self.assertEqual(history[0]["status"], "COMPLETED")
        self.assertEqual(
            self.client.get(f"{self.api}/{record['id']}").json()["report"], self.report
        )
        second = self.post(
            endpoint, {**question, "request_id": str(uuid4()), "question": "继续"}
        ).json()
        with self.factory() as db:
            context = db.get(CodeAnalysisChatTurn, second["id"]).context
            self.assertEqual(context["messages"][-1]["content"], history[0]["answer"])
        self.assertEqual(
            self.post(endpoint + f"/{second['id']}/cancel", {}).json()["status"], "CANCELLED"
        )

    def test_cancel_or_config_change_during_response_discards_output(self):
        first = self.post("", self.payload()).json()
        self.running(first["id"])

        def cancelled(*args, **kwargs):
            answer = self.answer(*args, **kwargs)
            self.assertEqual(self.post(f"/{first['id']}/cancel", {}).status_code, 200)
            return answer

        with patch("app.integrations.responses.analyze", side_effect=cancelled):
            execution.execute(first["id"], self.factory)
        result = self.client.get(f"{self.api}/{first['id']}").json()
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(result["report"], {})
        self.assertTrue(result["candidate_available"])
        self.assertEqual(
            self.client.get(f"{self.api}/{first['id']}/candidate").json()["contract_version"],
            2,
        )
        second = self.post("", self.payload()).json()
        self.running(second["id"])

        def config_changed(*args, **kwargs):
            answer = self.answer(*args, **kwargs)
            with self.factory() as db:
                db.get(AIConnection, self.member_id).version = 2
                db.commit()
            return answer

        with patch("app.integrations.responses.analyze", side_effect=config_changed):
            execution.execute(second["id"], self.factory)
        result = self.client.get(f"{self.api}/{second['id']}").json()
        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["report"], {})
        self.assertTrue(result["candidate_available"])

    def test_new_database_columns_have_actual_comments(self):
        with self.factory() as db:
            missing = db.scalars(
                text(
                    "SELECT a.attname FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' "
                    "AND c.relname IN ('code_analysis_chat_turn','code_analysis_task') "
                    "AND a.attnum>0 AND NOT a.attisdropped "
                    "AND col_description(c.oid,a.attnum) IS NULL"
                )
            ).all()
            self.assertEqual(missing, [])

    def test_github_permissions_fixed_commit_and_worker_read(self):
        with self.factory() as db:
            connection = GitHubConnection(
                owner_id=self.member_id,
                name="只读连接",
                kind="personal",
                resource_owner="example",
                github_login="example",
                encrypted_token="test-cipher",
                version=1,
            )
            repo = ProjectRepository(
                project_id=self.project,
                github_id=789123,
                full_name="example/server",
                kind="BACKEND",
                default_branch="main",
                version=1,
                updated_by=self.member_id,
            )
            db.add_all([connection, repo])
            db.flush()
            grant = GitHubRepository(
                connection_id=connection.id,
                github_id=repo.github_id,
                full_name=repo.full_name,
                default_branch="main",
                private=True,
            )
            db.add(grant)
            db.commit()
            connection_id, repo_id = connection.id, repo.id
        commit = "a" * 40
        content = self.input["sources"][0]["files"][0]["segments"][0]["text"]
        scope = {
            "commit": commit,
            "full_name": "example/server",
            "files": [{"path": "domain.py", "sha": "b" * 40, "size": len(content.encode())}],
        }
        query = f"repository_id={repo_id}&connection_id={connection_id}"
        with (
            patch("app.modules.github.service.saved_token", return_value="git-test"),
            patch.object(sources, "saved_token", return_value="git-test"),
            patch.object(github, "code_scope", return_value=scope) as remote,
            patch.object(github, "prototype_content", return_value=content.encode()),
        ):
            result = self.client.get(self.api + f"/github-scope?{query}&branch=main")
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["repository_kind"], "BACKEND")
            self.assertEqual(
                [
                    row["id"]
                    for row in self.client.get(self.api + "/options").json()["repositories"]
                ],
                [repo_id],
            )
            preview = self.client.get(
                self.api + f"/github-file?{query}&commit={commit}&path=domain.py"
            )
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["content"], content)
            self.assertEqual(
                self.client.get(
                    self.api + f"/github-file?{query}&commit={commit}&path=.env"
                ).status_code,
                422,
            )
            payload = self.payload()
            payload["sources"] = [
                {
                    "kind": "GITHUB",
                    "source_id": repo_id,
                    "connection_id": connection_id,
                    "source_version": 1,
                    "commit": commit,
                    "files": [{"path": "domain.py"}],
                }
            ]
            response = self.post("", payload)
            self.assertEqual(response.status_code, 202, response.text)
            self.running(response.json()["id"])
            with patch("app.integrations.responses.analyze", side_effect=self.answer):
                execution.execute(response.json()["id"], self.factory)
            record = self.client.get(f"{self.api}/{response.json()['id']}").json()
            self.assertEqual(record["status"], "COMPLETED", record)
            self.assertEqual(record["input"]["sources"][0]["commit"], commit)
            self.assertEqual(remote.call_args.args[2], commit)
            queued = self.post("", {**payload, "request_id": str(uuid4())}).json()
            with self.factory() as db:
                db.delete(db.get(GitHubRepository, (connection_id, 789123)))
                db.commit()
            self.running(queued["id"])
            with patch("app.integrations.responses.analyze") as upstream:
                execution.execute(queued["id"], self.factory)
                upstream.assert_not_called()
            self.assertEqual(
                self.client.get(self.api + f"/github-scope?{query}&branch=main").status_code, 403
            )
