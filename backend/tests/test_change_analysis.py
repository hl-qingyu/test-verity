import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import test_auth
import test_code_analysis
from sqlalchemy import select, text

from app.core.errors import AppError
from app.db.models import (
    AIConnection,
    ChangeAnalysisChatTurn,
    ChangeAnalysisTask,
    GitHubConnection,
    GitHubRepository,
    ProjectMember,
    ProjectRepository,
    SourceDocument,
    UserAccount,
)
from app.modules.change_analysis import (
    artifacts,
    batch_execution,
    batching,
    chat,
    contract,
    evidence,
    execution,
    schemas,
    service,
    sources,
)

EXAMPLES = Path(__file__).resolve().parents[2] / "skill/change-impact/examples"


def sample(name):
    return tuple(
        json.loads((EXAMPLES / f"{name}-{kind}.json").read_text(encoding="utf-8"))
        for kind in ("input", "report")
    )


def prototype_segment_mismatch():
    data, report = sample("prototype")
    unit = data["snapshots"][1]["units"][0]
    unit["segments"].append(
        {
            **unit["segments"][0],
            "segment_id": "s2",
            "location": "同一页面 · 公共批注",
            "text": "另一段固定公共批注，与按钮原文无关。",
        }
    )
    unit["content_sha256"] = hashlib.sha256(
        "\n".join(s["text"] for s in unit["segments"]).encode()
    ).hexdigest()
    report["coverage"][1]["segment_reviews"].append(
        {"segment_id": "s2", "status": "CHECKED", "note": "已核查固定批注"}
    )
    report["evidence"][1]["segment_id"] = "s2"
    return data, report


class ChangeContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cache = patch.object(artifacts, "result_directory", return_value=Path(directory.name))
        cache.start()
        self.addCleanup(cache.stop)

    def test_prototype_reads_reuse_verified_blobs_and_recheck_permissions(self):
        path, raw = "prototype/page.html", b"<p>fixed prototype</p>"
        sha = sources.github.blob_sha(raw)
        row = SimpleNamespace(repository_id=7, path="", current_version=1, name="prototype")
        repo, connection = SimpleNamespace(github_id=9), SimpleNamespace(version=1)
        pair = {
            "source_id": 3,
            "connection_id": 4,
            "before_ref": "a" * 40,
            "after_ref": "b" * 40,
            "paths": [path],
        }
        scope = {
            "commit": pair["before_ref"],
            "full_name": "team/prototype",
            "files": [{"path": path, "sha": sha, "size": len(raw)}],
        }
        with (
            patch.object(sources, "document", return_value=row),
            patch.object(
                sources.prototypes, "authorization", return_value=(repo, connection)
            ) as auth,
            patch.object(sources, "saved_token", return_value="synthetic"),
            patch.object(sources.github, "prototype_scope", return_value=scope),
            patch.object(sources.github, "prototype_content", return_value=raw) as read,
        ):
            db = SimpleNamespace(rollback=lambda: None)
            before = sources.prototype_git(1, pair, "before", "old", None, db)
            scope["commit"] = pair["after_ref"]
            after = sources.prototype_git(1, pair, "after", "new", None, db)
            self.assertEqual(read.call_count, 1)
            self.assertEqual(auth.call_count, 4)
            self.assertEqual(before["units"][0]["segments"], after["units"][0]["segments"])
            auth.side_effect = AppError(403, "github_repository_not_allowed")
            with self.assertRaises(AppError):
                sources.prototype_git(1, pair, "after", "denied", None, db)
            self.assertEqual(read.call_count, 1)

    def test_large_selected_sql_is_complete_in_old_new_snapshots_and_verified_cache(self):
        raw = b"INSERT INTO region VALUES (1, 'example');\n" * 100_000
        self.assertGreater(len(raw), 2_000_000)
        sha = sources.github.blob_sha(raw)
        path = "src/migrations/seed.sql"
        repo = SimpleNamespace(kind="BACKEND", full_name="team/source", github_id=1)
        connection = SimpleNamespace(version=1)
        pair = {
            "kind": "GITHUB_CODE",
            "source_id": 1,
            "source_version": 1,
            "connection_id": 1,
            "before_ref": "a" * 40,
            "after_ref": "b" * 40,
            "paths": [path],
        }

        def scope(token, repository_id, ref, **kwargs):
            return {
                "commit": ref,
                "full_name": repo.full_name,
                "files": [{"path": path, "size": len(raw), "sha": sha}],
            }

        with (
            patch.object(
                sources.code_sources, "source_authorization", return_value=(repo, connection)
            ),
            patch.object(sources, "saved_token", return_value="synthetic"),
            patch.object(sources.github, "code_scope", side_effect=scope),
            patch.object(sources.github, "prototype_content", return_value=raw) as read,
        ):
            snapshots = [
                sources.code_snapshot(
                    1, pair, side, f"p1-{side}", None, SimpleNamespace(rollback=lambda: None)
                )
                for side in ("before", "after")
            ]
        self.assertEqual(read.call_count, 1)
        self.assertEqual(artifacts.load_blob(1, 1, sha), raw)
        data, _ = sample("code")
        data.update(
            snapshots=snapshots,
            context_refs=[],
            targets=["BUG"],
            comparison_pairs=[sources.comparison("p1", *snapshots, "CODE_SNAPSHOT")],
        )
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        sent = json.loads(
            sources.analysis_materials.model_content(data, [], attachment_key="image_ref")[0][
                "text"
            ]
        )
        for snapshot in sent["snapshots"]:
            self.assertEqual(snapshot["units"][0]["segments"][0]["text"].encode(), raw)
        with patch.object(sources.github, "prototype_content") as no_read:
            with self.assertRaises(AppError) as invalid:
                sources.github_text(1, 1, "synthetic", repo.full_name, {"sha": sha, "size": -1})
            self.assertEqual(invalid.exception.detail, "github_invalid_response")
            no_read.assert_not_called()
        with patch.object(sources.github, "prototype_content", return_value=raw):
            with self.assertRaises(AppError) as invalid:
                sources.github_text(
                    1, 1, "synthetic", repo.full_name, {"sha": sha, "size": len(raw) - 1}
                )
            self.assertEqual(invalid.exception.detail, "github_invalid_response")

    def test_pem_cleanup_passes_read_cache_and_fixed_input_but_key_content_never_caches(self):
        cleanup = 'return privateKey.replace("-----BEGIN PRIVATE KEY-----", "");'
        raw = cleanup.encode()
        entry = {"sha": sources.github.blob_sha(raw), "size": len(raw)}
        with patch.object(sources.github, "prototype_content", return_value=raw):
            self.assertEqual(
                sources.github_text(1, 1, "synthetic", "team/source", entry), (cleanup, False)
            )
        self.assertEqual(artifacts.load_blob(1, 1, entry["sha"]), raw)
        data, _ = sample("code")
        old_unit = data["snapshots"][0]["units"][0]
        old_segment = old_unit["segments"][0]
        data["snapshots"][0]["units"][0] = sources.unit(
            old_unit["unit_id"],
            old_unit["path"],
            segments=[{**old_segment, "text": cleanup}],
        )
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        for raw, expected in (
            (b"\xffbinary", "code_text_required"),
            (b"binary\x00text", "code_text_required"),
            (b"-----BEGIN PRIVATE KEY-----\n" + b"A" * 64, "code_private_key_content"),
        ):
            entry = {"sha": sources.github.blob_sha(raw), "size": len(raw)}
            with patch.object(sources.github, "prototype_content", return_value=raw):
                with self.assertRaises(AppError) as caught:
                    sources.github_text(1, 1, "synthetic", "team/source", entry)
            self.assertEqual(caught.exception.detail, expected)
            self.assertIsNone(artifacts.load_blob(1, 1, entry["sha"]))
        data["snapshots"][0]["units"][0] = sources.unit(
            old_unit["unit_id"],
            old_unit["path"],
            segments=[{**old_segment, "text": raw.decode()}],
        )
        with self.assertRaises(AppError) as caught:
            contract.validate_input(contract.AnalysisInput.model_validate(data))
        self.assertEqual(caught.exception.detail, "code_private_key_content")

    def test_full_git_range_preserves_more_than_2000_files(self):
        paths = [f"src/File{n}.java" for n in range(3327)]
        pair = schemas.PairSelection.model_validate(
            {
                "kind": "GITHUB_CODE",
                "source_id": 1,
                "source_version": 1,
                "connection_id": 1,
                "before_ref": "a" * 40,
                "after_ref": "b" * 40,
                "update_mode": "CODE_SNAPSHOT",
                "paths": paths,
            }
        ).model_dump()
        repo = SimpleNamespace(kind="BACKEND", full_name="synthetic/repository", github_id=1)
        connection = SimpleNamespace(version=1)
        scope = {
            "commit": pair["after_ref"],
            "full_name": repo.full_name,
            "files": [
                {"path": p, "size": 5, "sha": sources.github.blob_sha(b"value")} for p in paths
            ],
        }
        with (
            patch.object(
                sources.code_sources, "source_authorization", return_value=(repo, connection)
            ),
            patch.object(sources, "saved_token", return_value="synthetic"),
            patch.object(sources.github, "code_scope", return_value=scope),
            patch.object(sources.github, "prototype_content", return_value=b"value") as reader,
        ):
            result = sources.code_snapshot(
                1, pair, "after", "after", None, SimpleNamespace(rollback=lambda: None)
            )
        snapshot = contract.Snapshot.model_validate(result)
        self.assertEqual([u.path for u in snapshot.units], paths)
        self.assertEqual(reader.call_count, 1)

    def test_old_full_plus_new_changed_blobs_keeps_complete_distinct_model_input(self):
        github = sources.github
        contents = [b"same", b"old", b"new", b"deleted", b"added", b"renamed"]
        blobs = {github.blob_sha(content): content for content in contents}
        before_files = dict(
            zip(
                ("same.py", "edit.py", "delete.py", "old-name.py"),
                (contents[0], contents[1], contents[3], contents[5]),
                strict=True,
            )
        )
        after_files = dict(
            zip(
                ("same.py", "edit.py", "add.py", "new-name.py"),
                (contents[0], contents[2], contents[4], contents[5]),
                strict=True,
            )
        )
        paths = sorted(set(before_files) | set(after_files) | {"unreadable.py"})
        pair = schemas.PairSelection.model_validate(
            {
                "kind": "GITHUB_CODE",
                "source_id": 1,
                "source_version": 1,
                "connection_id": 1,
                "before_ref": "a" * 40,
                "after_ref": "b" * 40,
                "update_mode": "CODE_SNAPSHOT",
                "paths": paths,
            }
        ).model_dump()
        repo = SimpleNamespace(kind="BACKEND", full_name="team/repository", github_id=1)
        connection = SimpleNamespace(version=1)

        def scope(token, repository_id, commit, **kwargs):
            files = before_files if commit == pair["before_ref"] else after_files
            return {
                "commit": commit,
                "full_name": repo.full_name,
                "present_paths": [*files, "unreadable.py"],
                "files": [
                    {"path": p, "sha": github.blob_sha(raw), "size": len(raw)}
                    for p, raw in files.items()
                ],
            }

        with (
            patch.object(
                sources.code_sources, "source_authorization", return_value=(repo, connection)
            ),
            patch.object(sources, "saved_token", return_value="synthetic"),
            patch.object(github, "code_scope", side_effect=scope),
            patch.object(
                github, "prototype_content", side_effect=lambda token, name, sha: blobs[sha]
            ) as reader,
        ):
            snapshots = [
                sources.code_snapshot(
                    1, pair, side, f"p1-{side}", None, SimpleNamespace(rollback=lambda: None)
                )
                for side in ("before", "after")
            ]
            self.assertEqual(reader.call_count, len(before_files) + 2)
            again = sources.code_snapshot(
                1, pair, "after", "p1-after", None, SimpleNamespace(rollback=lambda: None)
            )
            self.assertEqual(reader.call_count, len(before_files) + 2)
            self.assertEqual([u["path"] for u in again["units"]], paths)
        data, _ = sample("code")
        data.update(
            snapshots=snapshots,
            context_refs=[],
            targets=["BUG"],
            comparison_pairs=[sources.comparison("p1", *snapshots, "CODE_SNAPSHOT")],
        )
        contract.validate_input(contract.AnalysisInput.model_validate(data))
        content = sources.analysis_materials.model_content(data, [], attachment_key="image_ref")
        sent = json.loads(content[0]["text"])
        self.assertEqual(sent["comparison_pairs"][0]["before_ref"], "p1-before")
        self.assertEqual(sent["comparison_pairs"][0]["after_ref"], "p1-after")
        for snapshot, expected in zip(sent["snapshots"], (before_files, after_files), strict=True):
            self.assertEqual([u["path"] for u in snapshot["units"]], paths)
            for unit in snapshot["units"]:
                if unit["path"] in expected:
                    self.assertEqual(unit["segments"][0]["text"], expected[unit["path"]].decode())
            self.assertIn(
                "旧基准" if snapshot["snapshot_ref"].endswith("before") else "新目标",
                snapshot["scope_note"],
            )
        notes = {
            p: m["note"]
            for p, m in zip(paths, sent["comparison_pairs"][0]["unit_mappings"], strict=True)
        }
        for path, label in (
            ("same.py", "正文未变"),
            ("edit.py", "正文修改"),
            ("delete.py", "删除"),
            ("add.py", "新增"),
            ("old-name.py", "删除"),
            ("new-name.py", "新增"),
            ("unreadable.py", "无法确定"),
        ):
            self.assertIn(label, notes[path])
        with (
            patch.object(
                sources.code_sources,
                "source_authorization",
                side_effect=AppError(403, "github_repository_not_allowed"),
            ),
            patch.object(artifacts, "load_blob") as cache,
        ):
            with self.assertRaises(AppError):
                sources.code_snapshot(1, pair, "after", "p1-after", None, None)
            cache.assert_not_called()

    def test_partial_reads_survive_failure_cache_is_scoped_and_corruption_is_refetched(self):
        first, second = b"first", b"second"
        first_sha, second_sha = (sources.github.blob_sha(raw) for raw in (first, second))
        entries = [
            {"sha": sha, "size": len(raw)}
            for sha, raw in ((first_sha, first), (second_sha, second))
        ]
        with patch.object(
            sources.github,
            "prototype_content",
            side_effect=[first, AppError(502, "github_connection_failed"), second, first],
        ) as reader:
            sources.github_text(1, 1, "synthetic", "team/repository", entries[0])
            with self.assertRaises(AppError):
                sources.github_text(1, 1, "synthetic", "team/repository", entries[1])
            self.assertIsNone(artifacts.load_blob(1, 1, second_sha))
            self.assertEqual(
                sources.github_text(1, 1, "synthetic", "team/repository", entries[0]),
                ("first", True),
            )
            sources.github_text(1, 1, "synthetic", "team/repository", entries[1])
            self.assertEqual(reader.call_count, 3)
            self.assertIsNone(artifacts.load_blob(2, 1, first_sha))
            self.assertIsNone(artifacts.load_blob(1, 2, first_sha))
            artifacts._blob_path(1, 1, first_sha).write_bytes(b"corrupt")
            self.assertIsNone(artifacts.load_blob(1, 1, first_sha))
            self.assertEqual(
                sources.github_text(1, 1, "synthetic", "team/repository", entries[0]),
                ("first", False),
            )
            self.assertEqual(reader.call_count, 4)
        with self.assertRaises(AppError):
            artifacts.load_blob(1, 1, "../escape")
        with self.assertRaises(AppError):
            artifacts.save_blob(1, 1, first_sha, b"wrong hash")
        other_sha = sources.github.blob_sha(b"other")
        with patch.object(artifacts.os, "replace", side_effect=OSError("private storage error")):
            with self.assertRaises(AppError) as caught:
                artifacts.save_blob(1, 1, other_sha, b"other")
        self.assertEqual(caught.exception.detail, "change_source_storage_unavailable")
        self.assertIsNone(artifacts.load_blob(1, 1, other_sha))
        self.assertFalse(list(artifacts._blob_path(1, 1, other_sha).parent.glob(".*")))

    def test_fixed_git_presence_keeps_unreadable_entries_distinct_from_absence(self):
        from app.integrations import github

        commit, tree = "a" * 40, "b" * 40
        repo = {
            "id": 5,
            "full_name": "team/source",
            "private": True,
            "default_branch": "main",
            "owner": {"login": "team", "type": "Organization"},
        }

        def remote(token, operation, **kwargs):
            if operation == "repository":
                return repo
            if operation == "git_commit":
                return {"sha": commit, "tree": {"sha": tree}}
            if operation == "tree":
                return {
                    "sha": tree,
                    "truncated": False,
                    "tree": [
                        {
                            "path": "index.html",
                            "type": "blob",
                            "mode": "120000",
                            "sha": "c" * 40,
                            "size": 10,
                        },
                        {
                            "path": "logo.png",
                            "type": "blob",
                            "mode": "100644",
                            "sha": "d" * 40,
                            "size": 10,
                        },
                    ],
                }
            self.fail(operation)

        with patch.object(github, "github_get", side_effect=remote):
            code = github.code_scope("synthetic", 5, commit, include_presence=True)
            proto = github.prototype_scope(
                "synthetic", 5, commit, "", include_presence=True, allow_empty=True
            )
            for result in (code, proto):
                self.assertEqual(result["files"], [])
                self.assertEqual(set(result["present_paths"]), {"index.html", "logo.png"})
            with self.assertRaises(AppError):
                github.prototype_scope("synthetic", 5, commit, "")

    def test_three_modes_and_corrupt_evidence_are_checked(self):
        for name in ("requirement", "code", "prototype"):
            data, report = sample(name)
            contract.validate_report(
                contract.AnalysisInput.model_validate(data), contract.Report.model_validate(report)
            )
        data, report = sample("code")
        for mutate in (
            lambda r: r.update(project_id=99),
            lambda r: r["evidence"][0].update(side="AFTER"),
            lambda r: r["evidence"][0].update(excerpt="fabricated"),
            lambda r: r["evidence"][0].update(end_line=999),
            lambda r: r["risks"][0]["attribution"].update(kind="introduced", before_refs=[]),
            lambda r: r["risks"][0].update(change_refs=["missing"]),
            lambda r: r["coverage"].pop(),
            lambda r: r["changes"][0].update(kind="UNCHANGED"),
            lambda r: r["risks"][0].update(status="RESOLVED"),
        ):
            invalid = copy.deepcopy(report)
            mutate(invalid)
            with self.assertRaises((ValueError, AppError)):
                contract.validate_report(
                    contract.AnalysisInput.model_validate(data),
                    contract.Report.model_validate(invalid),
                )

    def test_coordinate_normalization_keeps_original_and_rejects_ambiguous_or_invented_text(self):
        data, raw = sample("code")
        raw["evidence"][0].update(start_line=2, end_line=999)
        parsed = contract.AnalysisInput.model_validate(data)
        original = contract.Report.model_validate(raw)
        fixed, corrections = evidence.normalize_coordinates(parsed, original)
        contract.validate_report(parsed, fixed)
        self.assertEqual(original.evidence[0].end_line, 999)
        self.assertTrue(corrections)
        raw["evidence"][0]["excerpt"] = "invented"
        fixed, corrections = evidence.normalize_coordinates(
            parsed, contract.Report.model_validate(raw)
        )
        self.assertFalse(corrections)
        with self.assertRaises(AppError):
            contract.validate_report(parsed, fixed)

    def test_prototype_segment_repair_uses_one_exact_occurrence_and_preserves_originals(self):
        data, raw = prototype_segment_mismatch()
        parsed = contract.AnalysisInput.model_validate(data)
        original = contract.Report.model_validate(raw)
        with self.assertRaises(AppError):
            contract.validate_report(parsed, original)
        fixed, corrections = evidence.normalize_coordinates(parsed, original)
        contract.validate_report(parsed, fixed)
        self.assertEqual(len(corrections), 1)
        self.assertEqual(corrections[0]["original_location"], "同一页面 · 公共批注")
        self.assertEqual(corrections[0]["location"], "order.html")
        self.assertEqual(
            {
                k: corrections[0][k]
                for k in ("kind", "evidence_key", "original_segment_id", "segment_id")
            },
            {
                "kind": "EXACT_TEXT_SEGMENT",
                "evidence_key": "E2",
                "original_segment_id": "s2",
                "segment_id": "s1",
            },
        )
        expected = copy.deepcopy(raw)
        expected["evidence"][1]["segment_id"] = "s1"
        self.assertEqual(fixed.model_dump(by_alias=True), expected)
        self.assertEqual(original.model_dump(by_alias=True), raw)
        self.assertEqual(parsed.model_dump(), data)

    def test_prototype_segment_repair_does_not_guess_ambiguous_or_foreign_evidence(self):
        for kind in (
            "duplicate_segments",
            "repeated_in_one_segment",
            "other_unit",
            "other_snapshot",
            "wrong_side",
            "unknown_segment",
            "invented_excerpt",
        ):
            with self.subTest(kind=kind):
                data, raw = prototype_segment_mismatch()
                unit = data["snapshots"][1]["units"][0]
                excerpt = raw["evidence"][1]["excerpt"]
                if kind == "duplicate_segments":
                    unit["segments"].append({**unit["segments"][0], "segment_id": "s3"})
                    raw["coverage"][1]["segment_reviews"].append(
                        {"segment_id": "s3", "status": "CHECKED", "note": "固定重复段"}
                    )
                elif kind == "repeated_in_one_segment":
                    unit["segments"][0]["text"] = excerpt + "\n" + excerpt
                elif kind == "other_unit":
                    other = copy.deepcopy(unit)
                    other.update(unit_id="other-unit", path="other.html")
                    data["snapshots"][1]["units"].append(other)
                    unit["segments"][0]["text"] = "本固定文件没有所引摘录。"
                    raw["coverage"].append(
                        {**copy.deepcopy(raw["coverage"][1]), "unit_id": "other-unit"}
                    )
                elif kind == "other_snapshot":
                    data["snapshots"][0]["units"][0]["segments"][0]["text"] += "\n" + excerpt
                    unit["segments"][0]["text"] = "本版本没有所引摘录。"
                elif kind == "wrong_side":
                    raw["evidence"][1]["side"] = "BEFORE"
                elif kind == "unknown_segment":
                    raw["evidence"][1]["segment_id"] = "unknown-segment"
                else:
                    raw["evidence"][1]["excerpt"] = "模型编造的原文"
                for snapshot in data["snapshots"]:
                    for item in snapshot["units"]:
                        item["content_sha256"] = hashlib.sha256(
                            "\n".join(s["text"] for s in item["segments"]).encode()
                        ).hexdigest()
                parsed = contract.AnalysisInput.model_validate(data)
                contract.validate_input(parsed)
                original = contract.Report.model_validate(raw)
                fixed, corrections = evidence.normalize_coordinates(parsed, original)
                self.assertEqual(corrections, [])
                self.assertEqual(fixed.model_dump(by_alias=True), raw)
                self.assertEqual(original.model_dump(by_alias=True), raw)
                self.assertEqual(parsed.model_dump(), data)
                with self.assertRaises(AppError):
                    contract.validate_report(parsed, fixed)

    def test_after_side_roles_local_scope_and_json_boundaries(self):
        data, _ = sample("code")
        data["targets"].append("FRONTEND_BACKEND_MISMATCH")
        with self.assertRaises(AppError) as error:
            contract.validate_input(contract.AnalysisInput.model_validate(data))
        self.assertEqual(error.exception.detail, "change_both_sides_required")
        self.assertTrue(sources.in_scope("src/a.py", ["/"]))
        self.assertTrue(sources.in_scope("src/a.py", ["src/"]))
        self.assertFalse(sources.in_scope("src/a.py", ["other/"]))
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', "```json\n{}\n```"):
            with self.assertRaises(AppError):
                service.json_object(raw)
        with self.assertRaises(ValueError):
            schemas.AnalysisRequest.model_validate(
                {
                    "request_id": str(uuid4()),
                    "title": "非法目标",
                    "mode": "REQUIREMENT_CHANGE",
                    "targets": ["BUG"],
                    "pairs": [{"kind": "FILE", "source_id": 1, "update_mode": "FULL_REPLACEMENT"}],
                    "confirmed": True,
                }
            )


class ChangeRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_request_is_not_rejected_by_the_old_64mib_envelope_limit(self):
        payload = {
            "request_id": str(uuid4()),
            "title": "完整单次分析",
            "mode": "CODE_CHANGE",
            "targets": ["BUG"],
            "confirmed": True,
            "pairs": [
                {
                    "kind": "GITHUB_CODE",
                    "source_id": 1,
                    "update_mode": "CODE_SNAPSHOT",
                    "paths": ["src/main.py"],
                }
            ],
        }

        async def chunks():
            for _ in range(65):
                yield b" " * 1024 * 1024
            yield json.dumps(payload).encode()

        parsed = await service.read_payload(chunks(), schemas.AnalysisRequest)
        self.assertEqual(str(parsed.request_id), payload["request_id"])

    async def test_request_errors_are_distinct_from_result_contract_errors(self):
        for raw, expected in (
            (b"{}", "change_request_invalid"),
            (b'{"a":1,"a":2}', "change_request_invalid"),
            (b"\xff", "change_json_invalid"),
        ):

            async def chunks():
                yield raw

            with self.assertRaises(AppError) as error:
                await service.read_payload(chunks(), schemas.AnalysisRequest)
            self.assertEqual(error.exception.detail, expected)
        with self.assertRaises(AppError) as error:
            service.parse(contract.Report, {})
        self.assertEqual(error.exception.detail, "change_contract_invalid")


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class ChangeDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    tearDown = test_code_analysis.CodeAnalysisDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login
    factory = test_code_analysis.CodeAnalysisDatabaseTests.factory
    configuration = test_code_analysis.CodeAnalysisDatabaseTests.configuration
    post = test_code_analysis.CodeAnalysisDatabaseTests.post

    def setUp(self):
        test_code_analysis.CodeAnalysisDatabaseTests.setUp(self)
        self.api = f"/api/projects/{self.project}/change-analysis"
        for module in (service, execution, chat, batch_execution):
            p = patch.object(module, "analysis_configuration", side_effect=self.configuration)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(
            artifacts, "result_directory", return_value=Path(self.artifact_directory.name)
        )
        p.start()
        self.addCleanup(p.stop)
        self.input, self.report = sample("code")

    def payload(self):
        sides = []
        import hashlib

        for n, s in enumerate(self.input["snapshots"], 1):
            content = s["units"][0]["segments"][0]["text"]
            sides.append(
                {
                    "ref": f"read-{n}",
                    "captured_at": "2026-10-10T10:00:00+08:00",
                    "scope": ["/"],
                    "files": [
                        {
                            "path": "orders.py",
                            "content": content,
                            "sha256": hashlib.sha256(content.encode()).hexdigest(),
                        }
                    ],
                    "skipped": {},
                }
            )
        return {
            "request_id": str(uuid4()),
            "title": "变更分析测试",
            "mode": "CODE_CHANGE",
            "targets": ["BUG"],
            "focus": "函数边界",
            "confirmed": True,
            "pairs": [
                {
                    "kind": "LOCAL_CODE",
                    "source_id": self.source_id,
                    "source_version": 1,
                    "update_mode": "CODE_SNAPSHOT",
                    "before_ref": "read-1",
                    "after_ref": "read-2",
                    "paths": ["orders.py"],
                    "before_local": sides[0],
                    "after_local": sides[1],
                }
            ],
        }

    def answer(self, *args, **kwargs):
        data = json.loads(args[5][0]["text"])
        result = copy.deepcopy(self.report)
        for k in ("request_id", "project_id", "revision", "mode"):
            result[k] = data[k]

        def walk(v):
            if isinstance(v, dict):
                return {k: walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [walk(x) for x in v]
            return (
                {
                    "code-old": "p1-before",
                    "code-new": "p1-after",
                    "u1": "u0",
                    "s1": "full",
                    "m1": "m0",
                    "d1": "d0",
                }.get(v, v)
                if isinstance(v, str)
                else v
            )

        return json.dumps(walk(result), ensure_ascii=False)

    def run_task(self, task_id, answer=None):
        with self.factory() as db:
            row = db.get(ChangeAnalysisTask, task_id)
            row.status = "RUNNING"
            db.commit()
        with patch(
            "app.integrations.responses.analyze", side_effect=answer or self.answer
        ) as remote:
            execution.execute(task_id, self.factory)
        return self.client.get(f"{self.api}/{task_id}").json(), remote

    def batch_payload(self):
        payload = self.payload()
        pair = payload["pairs"][0]
        pair["paths"].append("second.py")
        for side in ("before_local", "after_local"):
            pair[side]["files"].append({**pair[side]["files"][0], "path": "second.py"})
        return payload

    def test_http_rejection_keeps_private_reason_and_safe_task_diagnostics_without_retry(self):
        import base64
        import io
        from urllib.error import HTTPError

        from cryptography.fernet import Fernet

        from app.integrations import response_errors, responses

        created = self.post("", self.payload()).json()
        original_call = responses.analyze
        body = json.dumps(
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "Specific provider constraint synthetic private source",
                }
            }
        ).encode()
        opener = MagicMock()
        opener.open.side_effect = HTTPError(
            "https://example.invalid/responses", 400, "", {}, io.BytesIO(body)
        )
        encrypted = Fernet(Fernet.generate_key())
        with (
            patch("app.integrations.responses.build_opener", return_value=opener),
            patch.object(
                response_errors,
                "directory",
                return_value=Path(self.artifact_directory.name) / "errors",
            ),
            patch.object(response_errors, "credential_cipher", return_value=encrypted),
        ):
            failed, remote = self.run_task(created["id"], original_call)
            self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(failed["error_code"], "ai_request_rejected")
            with self.factory() as db:
                saved = db.get(ChangeAnalysisTask, created["id"])
                stats = saved.metadata_snapshot["ai_diagnostics"]
                self.assertEqual(stats["http_status"], 400)
                self.assertEqual(stats["upstream_type"], "invalid_request_error")
                self.assertNotIn("synthetic source", json.dumps(stats))
                self.assertEqual(saved.input_snapshot, failed["input"])
            capture = response_errors.read(stats["error_ref"])
            self.assertIn(b"Specific provider constraint", base64.b64decode(capture["body_base64"]))
        remote.assert_called_once()
        opener.open.assert_called_once()

    def prepare_historical_batches(self, created, *, integration=False, authorize=True):
        with self.factory() as db:
            row = db.get(ChangeAnalysisTask, created["id"])
            row.metadata_snapshot = {
                **row.metadata_snapshot,
                "execution_mode": "BATCHED_V2" if integration else "BATCHED_V1",
            }
            db.commit()

        def planned(data, *, version):
            with patch.object(batching, "LEGACY_TARGET_BYTES", 1):
                plan = batching.legacy_plan(data)
            if not integration:
                return plan
            for batch in plan["batches"]:
                batch.update(
                    plan_version=2,
                    kind="ANALYSIS",
                    depends_on=[],
                    callable=True,
                    blocked_targets=[],
                    limitations=[],
                )
            review = copy.deepcopy(plan["batches"][0])
            review.update(
                id=3,
                kind="INTEGRATION",
                depends_on=[1, 2],
                mappings=[k for b in plan["batches"] for k in b["mappings"]],
                primary=[k for b in plan["batches"] for k in b["primary"]],
            )
            review["input_bytes"] = batching.size(batching.input_for(data, review))
            plan["batches"].append(review)
            plan["version"] = 2
            return plan

        with patch.object(batching, "plan", side_effect=planned):
            ready, remote = self.run_task(created["id"])
        remote.assert_not_called()
        self.assertEqual(ready["status"], "PREPARED")
        self.assertFalse(ready["can_start"])
        if integration:
            self.assertEqual(ready["batches"]["review_batches"], 1)
        if authorize:
            # Seed an already-authorized historical task; current start must not create new batches.
            with self.factory() as db:
                row = db.get(ChangeAnalysisTask, created["id"])
                row.metadata_snapshot = {**row.metadata_snapshot, "batch_authorized": True}
                row.status = "QUEUED"
                db.commit()
        return ready

    def test_historical_association_review_waits_and_retry_analyzes_complete_input_once(self):
        from app.modules.change_analysis import comparison

        created = self.post("", self.batch_payload()).json()
        self.prepare_historical_batches(created, integration=True)
        calls = 0

        def first_attempt(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise AppError(504, "ai_gateway_timeout")
            return self.answer(*args, **kwargs)

        partial, remote = self.run_task(created["id"], first_attempt)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(partial["batches"]["batches"][2]["status"], "QUEUED")
        self.assertEqual(
            partial["batches"]["batches"][2]["error_code"], "change_batch_dependencies_pending"
        )
        self.assertEqual(partial["outcome"], "PARTIAL")
        self.assertEqual(len(partial["report"]["risks"]), 1)
        retry = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())}).json()
        self.assertFalse(retry.get("batches"))
        self.assertFalse(retry["handling"])

        def complete(*args, **kwargs):
            data = json.loads(args[5][0]["text"])
            self.assertEqual(len(args[5]), 1)
            self.assertTrue(all(len(s["units"]) == 2 for s in data["snapshots"]))
            result = comparison.unchanged_report(data)
            return json.dumps(result, ensure_ascii=False)

        done, remote = self.run_task(retry["id"], complete)
        remote.assert_called_once()
        self.assertEqual(done["status"], "COMPLETED", done.get("error_code"))
        self.assertFalse(done.get("batches"))
        self.assertEqual(done["report"]["risks"], [])
        old = self.client.get(f"{self.api}/{created['id']}").json()
        self.assertEqual(old["report"], partial["report"])
        historical = self.post("", self.batch_payload()).json()
        self.prepare_historical_batches(historical, integration=True)
        count = 0

        def review_complete(*args, **kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return self.answer(*args, **kwargs)
            subset = json.loads(args[5][0]["text"])
            result = comparison.unchanged_report(subset)
            if count == 3:
                self.assertEqual(len(args[5]), 2)
                previous = json.loads(args[5][1]["text"])["prior_batch_reports"]
                self.assertEqual([x["batch_id"] for x in previous], [1, 2])
                return json.dumps({"report": result, "reconciliations": []}, ensure_ascii=False)
            return json.dumps(result, ensure_ascii=False)

        compatible, remote = self.run_task(historical["id"], review_complete)
        self.assertEqual(remote.call_count, 3)
        self.assertEqual(compatible["status"], "COMPLETED", compatible.get("error_code"))
        self.assertEqual(compatible["batches"]["completed"], 3)
        self.assertEqual(len(compatible["report"]["risks"]), 1)

    def test_historical_prepared_plan_retry_uses_full_input_and_preserves_original_plan(self):
        created = self.post("", self.batch_payload()).json()
        ready = self.prepare_historical_batches(created, authorize=False)
        self.assertFalse(ready["can_start"])
        self.assertTrue(ready["can_retry"])
        rejected = self.post(f"/{created['id']}/start", {})
        self.assertEqual(rejected.status_code, 422)
        self.assertEqual(rejected.json()["detail"], "change_full_input_required")
        old = self.client.get(f"{self.api}/{created['id']}").json()
        with self.factory() as db:
            original = db.get(ChangeAnalysisTask, created["id"])
            original_metadata = copy.deepcopy(original.metadata_snapshot)
        retry = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())}).json()
        self.assertFalse(retry.get("batches"))
        with self.factory() as db:
            row = db.get(ChangeAnalysisTask, retry["id"])
            self.assertEqual(row.metadata_snapshot["execution_mode"], "FULL_INPUT")
            self.assertNotIn("batch_authorized", row.metadata_snapshot)
            self.assertEqual(row.metadata_snapshot["skill"], original_metadata["skill"])
            self.assertEqual(
                row.metadata_snapshot["previous_batch_execution"]["plan"]["version"], 1
            )
        from app.modules.change_analysis import comparison

        def complete(*args, **kwargs):
            return json.dumps(
                comparison.unchanged_report(json.loads(args[5][0]["text"])), ensure_ascii=False
            )

        with patch.object(batching, "plan") as no_planning:
            new, remote = self.run_task(retry["id"], complete)
        remote.assert_called_once()
        no_planning.assert_not_called()
        self.assertEqual(new["status"], "COMPLETED")
        self.assertFalse(new.get("batches"))
        self.assertEqual(
            self.client.get(f"{self.api}/{created['id']}").json()["report"], old["report"]
        )
        with self.factory() as db:
            original = db.get(ChangeAnalysisTask, created["id"])
            self.assertEqual(original.metadata_snapshot, original_metadata)
            self.assertEqual(original.input_snapshot, old["input"])

    def test_full_local_repository_and_code_context_are_not_truncated(self):
        from app.modules.change_analysis import comparison

        payload = self.payload()
        pair = payload["pairs"][0]
        paths = [f"src/file{n}.py" for n in range(3327)]
        file = pair["before_local"]["files"][0]
        for side in ("before_local", "after_local"):
            pair[side]["files"] = [{**file, "path": p} for p in paths]
            pair[side]["scope"] = paths
        pair["paths"] = paths
        payload["sources"] = [
            {
                "kind": "LOCAL",
                "source_id": self.source_id,
                "source_version": 1,
                "files": pair["before_local"]["files"],
            }
        ]
        created = self.post("", payload)
        self.assertEqual(created.status_code, 202, created.text)

        def complete(*args, **kwargs):
            data = json.loads(args[5][0]["text"])
            return json.dumps(comparison.unchanged_report(data), ensure_ascii=False)

        with patch.object(batching, "plan") as no_planning:
            done, remote = self.run_task(created.json()["id"], complete)
        self.assertEqual(done["status"], "COMPLETED", done.get("error_code"))
        remote.assert_called_once()
        no_planning.assert_not_called()
        self.assertEqual(len(done["input"]["snapshots"]), 3)
        for snapshot in done["input"]["snapshots"]:
            self.assertEqual([u["path"] for u in snapshot["units"]], paths)
        self.assertEqual(len(done["report"]["coverage"]), 3 * len(paths))
        with self.factory() as db:
            saved = db.get(ChangeAnalysisTask, created.json()["id"])
            self.assertEqual(saved.metadata_snapshot["selections"]["pairs"][0]["paths"], paths)

    def test_large_input_reaches_model_once_with_all_versions_and_context_unchanged(self):
        import hashlib

        payload = self.payload()
        pair = payload["pairs"][0]
        paths = [f"src/file{n}.py" for n in range(9)]
        text = "x" * 2_000_000
        for side in ("before_local", "after_local"):
            pair[side]["files"] = [
                {"path": path, "content": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
                for path in paths
            ]
        pair["paths"] = paths
        changed = pair["after_local"]["files"][-1]
        changed["content"] = "y" + text[1:]
        changed["sha256"] = hashlib.sha256(changed["content"].encode()).hexdigest()
        payload["sources"] = [
            {
                "kind": "LOCAL",
                "source_id": self.source_id,
                "source_version": 1,
                "files": pair["before_local"]["files"],
            }
        ]
        created = self.post("", payload)
        self.assertEqual(created.status_code, 202, created.status_code)

        def model_rejects(*args, **kwargs):
            sent = json.loads(args[5][0]["text"])
            self.assertEqual(len(args[5]), 1)
            self.assertEqual(len(sent["snapshots"]), 3)
            self.assertTrue(all(len(s["units"]) == 9 for s in sent["snapshots"]))
            for snapshot in sent["snapshots"]:
                self.assertEqual([u["path"] for u in snapshot["units"]], paths)
            self.assertEqual(sent["targets"], payload["targets"])
            self.assertTrue(sent["context_refs"])
            with self.factory() as db:
                fixed = db.get(ChangeAnalysisTask, created.json()["id"])
                self.assertEqual(sent, fixed.input_snapshot)
                self.assertEqual(fixed.metadata_snapshot["execution_mode"], "FULL_INPUT")
                self.assertNotIn("batch_plan", fixed.metadata_snapshot)
            self.assertEqual(
                sent["snapshots"][1]["units"][-1]["segments"][0]["text"], changed["content"]
            )
            raise AppError(422, "ai_model_input_rejected")

        with patch.object(batching, "plan") as no_planning:
            done, remote = self.run_task(created.json()["id"], model_rejects)
        no_planning.assert_not_called()
        self.assertEqual(done["status"], "FAILED")
        self.assertEqual(done["error_code"], "ai_model_input_rejected")
        self.assertTrue(done["input"])
        self.assertEqual(remote.call_count, 1)
        self.assertTrue(done["can_retry"])
        exported = self.client.get(f"{self.api}/{created.json()['id']}/export?format=input")
        self.assertEqual(exported.status_code, 422)
        self.assertEqual(exported.json()["detail"], "change_report_not_ready")
        with self.factory() as db:
            prepared, _, _ = sources.code_sources.prepare(
                self.project,
                payload["request_id"],
                {
                    "sources": payload["sources"],
                    "materials": [],
                    "targets": ["BUG"],
                    "focus": "",
                },
                db.get(UserAccount, self.member_id),
                db,
            )
            self.assertEqual([f["path"] for f in prepared["sources"][0]["files"]], paths)
            self.assertTrue(
                all(f["segments"][0]["text"] == text for f in prepared["sources"][0]["files"])
            )

    def test_historical_partial_report_retry_uses_current_actor_full_input_and_keeps_old_review(
        self,
    ):
        from app.modules.change_analysis import comparison

        payload = self.batch_payload()
        created = self.post("", payload).json()
        ready = self.prepare_historical_batches(created, authorize=False)
        self.assertEqual(ready["batches"]["total"], 2)
        self.login()
        self.assertEqual(self.post(f"/{created['id']}/start", {}).status_code, 403)
        self.login(self.member_name)
        self.assertEqual(self.post(f"/{created['id']}/start", {}).status_code, 422)
        with self.factory() as db:
            row = db.get(ChangeAnalysisTask, created["id"])
            row.metadata_snapshot = {**row.metadata_snapshot, "batch_authorized": True}
            db.commit()
        calls = []

        def one_fails(*args, **kwargs):
            calls.append(args)
            if len(calls) == 2:
                raise AppError(504, "ai_gateway_timeout")
            return self.answer(*args, **kwargs)

        done, remote = self.run_task(created["id"], one_fails)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(done["status"], "COMPLETED", done.get("error_code"))
        self.assertEqual(done["outcome"], "PARTIAL")
        self.assertEqual(done["batches"]["completed"], 1)
        self.assertEqual(done["batches"]["failed"], 1)
        self.assertTrue(done["can_retry"])
        self.assertEqual(len(done["report"]["risks"]), 1)
        key = done["report"]["risks"][0]["key"]
        handled = self.post(
            f"/{created['id']}/handling",
            {
                "revision": done["revision"],
                "item_key": key,
                "status": "CONFIRMED",
                "note": "复用成功批次时保留人工确认",
            },
        )
        self.assertEqual(handled.status_code, 200, handled.text)
        exported = self.client.get(f"{self.api}/{created['id']}/export?format=markdown")
        self.assertEqual(exported.status_code, 200)
        self.assertIn("分批执行记录、原批成果与调用审计", exported.text)
        self.assertIn("input_hash", exported.text)
        original = copy.deepcopy(done["report"])
        self.login()
        retry = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())})
        self.assertEqual(retry.status_code, 202, retry.text)

        def completed(*args, **kwargs):
            self.assertEqual(args[2], f"secret-{self.admin_id}")
            data = json.loads(args[5][0]["text"])
            self.assertEqual(len(args[5]), 1)
            self.assertEqual(data["snapshots"], done["input"]["snapshots"])
            return json.dumps(comparison.unchanged_report(data), ensure_ascii=False)

        retried, remote = self.run_task(retry.json()["id"], completed)
        remote.assert_called_once()
        self.assertEqual(retried["status"], "COMPLETED", retried.get("error_code"))
        self.assertFalse(retried.get("batches"))
        self.assertFalse(retried["can_retry"])
        self.assertEqual(retried["report"]["risks"], [])
        self.assertEqual(retried["handling"], {})
        with self.factory() as db:
            row = db.get(ChangeAnalysisTask, retry.json()["id"])
            self.assertEqual(
                row.metadata_snapshot["previous_batch_execution"]["handling"][key],
                handled.json()["handling"][key],
            )
        old = self.client.get(f"{self.api}/{created['id']}").json()
        self.assertEqual(old["report"], original)
        self.assertEqual(old["handling"], handled.json()["handling"])
        self.assertEqual(old["batches"]["failed"], 1)

    def test_historical_batch_cancellation_and_free_revalidation_preserve_saved_attempts(self):
        from sqlalchemy import inspect

        from app.modules.change_analysis import comparison

        created = self.post("", self.batch_payload()).json()
        self.prepare_historical_batches(created)
        with self.factory() as db:
            row = service.own(
                self.project,
                created["id"],
                db.get(UserAccount, self.member_id),
                db,
                state_only=True,
            )
            self.assertTrue(
                {"input_snapshot", "metadata_snapshot", "report"} <= inspect(row).unloaded
            )
        calls = 0

        def cancel_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.post(f"/{created['id']}/cancel", {})
            return json.dumps(
                comparison.unchanged_report(json.loads(args[5][0]["text"])), ensure_ascii=False
            )

        cancelled, remote = self.run_task(created["id"], cancel_second)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(cancelled["batches"]["completed"], 1)
        self.assertEqual(cancelled["report"], {})

        second = self.post("", self.batch_payload()).json()
        self.prepare_historical_batches(second)

        def valid(*args, **kwargs):
            return json.dumps(
                comparison.unchanged_report(json.loads(args[5][0]["text"])), ensure_ascii=False
            )

        with patch.object(
            batch_execution, "candidate", side_effect=AppError(422, "change_contract_invalid")
        ):
            failed, remote = self.run_task(second["id"], valid)
        self.assertEqual(remote.call_count, 2)
        self.assertEqual(failed["status"], "FAILED")
        self.assertTrue(failed["can_revalidate"])
        with patch("app.integrations.responses.analyze") as no_ai:
            fixed = self.post(f"/{second['id']}/revalidate", {})
        no_ai.assert_not_called()
        self.assertEqual(fixed.status_code, 200, fixed.text)
        self.assertEqual(fixed.json()["batches"]["completed"], 2)
        self.assertEqual(fixed.json()["status"], "COMPLETED")
        with self.factory() as db:
            plan = db.get(ChangeAnalysisTask, second["id"]).metadata_snapshot["batch_plan"]
            self.assertTrue(
                all(
                    len(b["attempts"]) == 1 and b["attempts"][0]["status"] == "FAILED"
                    for b in plan["batches"]
                )
            )
        third = self.post("", self.batch_payload()).json()
        self.prepare_historical_batches(third)

        def rejected(*args, **kwargs):
            raise AppError(502, "ai_auth_failed")

        blocked, remote = self.run_task(third["id"], rejected)
        remote.assert_called_once()
        self.assertEqual(blocked["status"], "FAILED")
        self.assertEqual([b["status"] for b in blocked["batches"]["batches"]], ["FAILED", "QUEUED"])

    def test_queue_worker_handling_chat_export_and_actual_comments(self):
        payload = self.payload()
        first = self.post("", payload)
        self.assertEqual(first.status_code, 202, first.text)
        task_id = first.json()["id"]
        self.assertEqual(self.post("", payload).json()["id"], task_id)
        self.assertEqual(self.post("", {**payload, "focus": "other"}).status_code, 409)
        done, remote = self.run_task(task_id)
        self.assertEqual(done["status"], "COMPLETED", done)
        self.assertEqual(done["report"]["risks"][0]["attribution"]["kind"], "pre_existing")
        self.assertEqual(remote.call_args.args[2], f"secret-{self.member_id}")
        self.assertEqual(
            self.post(
                f"/{task_id}/handling",
                {"revision": 1, "item_key": "R1", "status": "CONFIRMED", "note": ""},
            ).status_code,
            422,
        )
        handled = self.post(
            f"/{task_id}/handling",
            {"revision": 1, "item_key": "R1", "status": "CONFIRMED", "note": "人工核查"},
        )
        self.assertEqual(handled.status_code, 200, handled.text)
        self.assertEqual(handled.json()["report"], done["report"])
        self.assertEqual(
            self.post(
                f"/{task_id}/handling",
                {"revision": 1, "item_key": "R1", "status": "RESOLVED", "note": "过期"},
            ).status_code,
            409,
        )
        for format in ("input", "report", "markdown"):
            exported = self.client.get(f"{self.api}/{task_id}/export?format={format}")
            self.assertEqual(exported.status_code, 200, exported.text)
            self.assertIn(
                "pre_existing", exported.text if format != "input" else json.dumps(done["report"])
            )
        turn = self.post(
            f"/{task_id}/chat",
            {"request_id": str(uuid4()), "question": "为什么是原有问题？", "finding_key": "R1"},
        )
        self.assertEqual(turn.status_code, 202, turn.text)
        self.assertEqual(
            self.post(
                f"/{task_id}/chat", {"request_id": str(uuid4()), "question": "第二轮"}
            ).status_code,
            409,
        )
        with self.factory() as db:
            db.get(ChangeAnalysisChatTurn, turn.json()["id"]).status = "RUNNING"
            db.commit()
        with patch(
            "app.integrations.responses.converse", return_value="旧版也有相同首项读取，尚未执行。"
        ):
            execution.execute_chat(turn.json()["id"], self.factory)
        messages = self.client.get(f"{self.api}/{task_id}/chat").json()
        self.assertEqual(messages["items"][0]["status"], "COMPLETED", messages)
        with self.factory() as db:
            comments = db.execute(
                text(
                    "SELECT obj_description('change_analysis_task'::regclass), "
                    "col_description('change_analysis_task'::regclass, "
                    "(SELECT attnum FROM pg_attribute "
                    "WHERE attrelid='change_analysis_task'::regclass AND attname='mode'))"
                )
            ).one()
            self.assertTrue(all(any("\u4e00" <= c <= "\u9fff" for c in note) for note in comments))
        self.login()
        shared = self.client.get(f"{self.api}/{task_id}")
        self.assertEqual(shared.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/projects/{self.other}/change-analysis/{task_id}").status_code,
            404,
        )

    def test_failed_preparation_retries_original_scope_with_current_members_ai(self):
        payload = self.payload()
        created = self.post("", payload).json()
        with patch.object(
            sources, "prepare", side_effect=AppError(502, "github_connection_failed")
        ):
            failed, remote = self.run_task(created["id"])
        remote.assert_not_called()
        self.assertEqual(failed["status"], "FAILED")
        self.assertEqual(failed["input"], {})
        self.assertTrue(failed["can_retry"])
        self.assertTrue(failed["retry_preparation"])
        listed = self.client.get(self.api).json()["items"][0]
        self.assertTrue(listed["can_retry"])
        self.assertTrue(listed["retry_preparation"])
        with self.factory() as db:
            original = copy.deepcopy(db.get(ChangeAnalysisTask, created["id"]).metadata_snapshot)
        self.login()
        request = {"request_id": str(uuid4())}
        with patch.object(
            sources, "skill_snapshot", side_effect=AssertionError("keep the fixed Skill")
        ):
            retried = self.post(f"/{created['id']}/retry", request)
        self.assertEqual(retried.status_code, 202, retried.text)
        self.assertEqual(
            self.post(f"/{created['id']}/retry", request).json()["id"], retried.json()["id"]
        )
        with self.factory() as db:
            retry = db.get(ChangeAnalysisTask, retried.json()["id"])
            self.assertEqual(retry.retry_of, created["id"])
            self.assertEqual(retry.metadata_snapshot["selections"], original["selections"])
            self.assertEqual(retry.metadata_snapshot["skill"], original["skill"])
        done, remote = self.run_task(retried.json()["id"])
        self.assertEqual(done["status"], "COMPLETED", done.get("error_code"))
        self.assertEqual(remote.call_count, 1)
        self.assertEqual(remote.call_args.args[2], f"secret-{self.admin_id}")
        old = self.client.get(f"{self.api}/{created['id']}").json()
        self.assertEqual(old["status"], "FAILED")
        self.assertEqual(old["input"], {})
        self.assertEqual(old["selections"], failed["selections"])

    def test_page_queries_keep_display_permissions_and_full_export_without_loading_list_input(self):
        created = self.post("", self.payload()).json()
        task_id = created["id"]
        page_url = f"{self.api}/{task_id}?page_view=true"
        queued = self.client.get(page_url)
        self.assertEqual(queued.status_code, 200, queued.text)
        self.assertEqual(queued.json()["input"], {})
        self.assertEqual(queued.json()["selections"], created["selections"])
        done, remote = self.run_task(task_id)
        remote.assert_called_once()
        page = self.client.get(page_url).json()
        self.assertTrue(page.pop("input_projected"))
        for key in done.keys() - {"input", "skill"}:
            self.assertEqual(page[key], done[key], key)
        self.assertEqual(page["input"]["comparison_pairs"], done["input"]["comparison_pairs"])
        for projected, original in zip(
            page["input"]["snapshots"], done["input"]["snapshots"], strict=True
        ):
            self.assertEqual(projected["snapshot_ref"], original["snapshot_ref"])
            self.assertEqual(projected["provenance"], original["provenance"])
            self.assertEqual(
                projected["units"],
                [{"unit_id": unit["unit_id"], "path": unit["path"]} for unit in original["units"]],
            )
        statements = []
        from sqlalchemy import event

        def capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(self.connection, "before_cursor_execute", capture)
        try:
            listed = self.client.get(f"{self.api}?page_view=true").json()["items"][0]
        finally:
            event.remove(self.connection, "before_cursor_execute", capture)
        self.assertEqual(listed["id"], task_id)
        self.assertNotIn("retry_preparation", listed)
        self.assertFalse(any("input_snapshot" in sql for sql in statements))
        self.assertEqual(
            self.client.get(f"{self.api}/{task_id}/export?format=input").json(), done["input"]
        )
        self.assertEqual(self.client.get(f"{self.api}/{task_id}").json(), done)
        self.assertEqual(
            self.client.get(
                f"/api/projects/{self.other}/change-analysis/{task_id}?page_view=true"
            ).status_code,
            404,
        )

    def test_retry_missing_scope_skill_and_stale_source_do_not_enqueue_or_call_ai(self):
        created = self.post("", self.payload()).json()
        with self.factory() as db:
            row = db.get(ChangeAnalysisTask, created["id"])
            row.status = "FAILED"
            original = copy.deepcopy(row.metadata_snapshot)
            db.commit()
        for remove in ("selections", "skill"):
            with self.factory() as db:
                bad = copy.deepcopy(original)
                bad.pop(remove)
                db.get(ChangeAnalysisTask, created["id"]).metadata_snapshot = bad
                db.commit()
            with patch.object(service, "analysis_configuration") as no_ai:
                result = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())})
            self.assertEqual(result.status_code, 422)
            self.assertEqual(result.json()["detail"], "change_retry_scope_unavailable")
            no_ai.assert_not_called()
        with self.factory() as db:
            bad = copy.deepcopy(original)
            bad["selections"]["pairs"][0]["source_version"] += 1
            db.get(ChangeAnalysisTask, created["id"]).metadata_snapshot = bad
            db.commit()
        stale = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()["detail"], "code_source_changed")
        self.assertEqual(
            self.client.post(
                f"/api/projects/{self.other}/change-analysis/{created['id']}/retry",
                json={"request_id": str(uuid4())},
                headers=test_auth.ORIGIN,
            ).status_code,
            404,
        )
        self.assertEqual(len(self.client.get(self.api).json()["items"]), 1)

    def test_github_preparation_retry_keeps_commits_and_uses_retrying_members_connection(self):
        with self.factory() as db:
            repo = ProjectRepository(
                project_id=self.project,
                github_id=789123,
                full_name="example/server",
                kind="BACKEND",
                default_branch="main",
                version=1,
                updated_by=self.member_id,
            )
            db.add(repo)
            connections = {}
            for owner_id in (self.member_id, self.admin_id):
                connection = GitHubConnection(
                    owner_id=owner_id,
                    name="只读测试",
                    kind="personal",
                    resource_owner="example",
                    github_login="example",
                    encrypted_token="synthetic",
                    version=1,
                )
                db.add(connection)
                db.flush()
                db.add(
                    GitHubRepository(
                        connection_id=connection.id,
                        github_id=repo.github_id,
                        full_name=repo.full_name,
                        default_branch="main",
                        private=True,
                    )
                )
                connections[owner_id] = connection.id
            db.commit()
            repository_id = repo.id
        payload = self.payload()
        payload["pairs"] = [
            {
                "kind": "GITHUB_CODE",
                "source_id": repository_id,
                "source_version": 1,
                "connection_id": connections[self.member_id],
                "before_ref": "a" * 40,
                "after_ref": "b" * 40,
                "paths": ["orders.py"],
                "update_mode": "CODE_SNAPSHOT",
            }
        ]
        created = self.post("", payload).json()
        with patch.object(
            sources, "prepare", side_effect=AppError(502, "github_connection_failed")
        ):
            self.run_task(created["id"])
        self.login()
        retried = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())})
        self.assertEqual(retried.status_code, 202, retried.text)
        blobs = {}
        manifests = {}
        for ref, snapshot in zip(("a" * 40, "b" * 40), self.input["snapshots"], strict=True):
            raw = snapshot["units"][0]["segments"][0]["text"].encode()
            sha = sources.github.blob_sha(raw)
            blobs[sha] = raw
            manifests[ref] = {
                "commit": ref,
                "full_name": "example/server",
                "files": [{"path": "orders.py", "size": len(raw), "sha": sha}],
            }
        with (
            patch.object(sources, "saved_token", side_effect=lambda c: f"git-{c.owner_id}"),
            patch.object(
                sources.github,
                "code_scope",
                side_effect=lambda token, repo, ref, **kw: manifests[ref],
            ) as trees,
            patch.object(
                sources.github, "prototype_content", side_effect=lambda token, name, sha: blobs[sha]
            ),
        ):
            done, remote = self.run_task(retried.json()["id"])
        self.assertEqual(done["status"], "COMPLETED", done.get("error_code"))
        self.assertEqual(remote.call_count, 1)
        self.assertEqual({call.args[0] for call in trees.call_args_list}, {f"git-{self.admin_id}"})
        self.assertEqual({call.args[2] for call in trees.call_args_list}, {"a" * 40, "b" * 40})

    def test_candidate_failed_late_cancel_retry_frozen_and_configuration_changes(self):
        created = self.post("", self.payload()).json()

        def wrong_coordinates(*args, **kwargs):
            candidate = json.loads(self.answer(*args, **kwargs))
            candidate["evidence"][0].update(start_line=2, end_line=999)
            return json.dumps(candidate, ensure_ascii=False)

        with patch.object(evidence, "normalize_coordinates", side_effect=lambda data, r: (r, [])):
            failed, _ = self.run_task(created["id"], wrong_coordinates)
        self.assertEqual(failed["status"], "FAILED", failed)
        self.assertTrue(failed["can_revalidate"])
        self.assertEqual(self.client.get(f"{self.api}/{created['id']}/candidate").status_code, 200)
        original = failed["input"]
        original_candidate = artifacts.candidate_path(created["id"]).read_bytes()
        with patch("app.integrations.responses.analyze") as no_ai:
            fixed = self.post(f"/{created['id']}/revalidate", {})
            self.assertEqual(fixed.status_code, 200, fixed.text)
            no_ai.assert_not_called()
        self.assertEqual(fixed.json()["input"], original)
        self.assertEqual(artifacts.candidate_path(created["id"]).read_bytes(), original_candidate)
        self.assertTrue(fixed.json()["evidence_corrections"])
        created = self.post("", self.payload()).json()

        def cancelled(*args, **kwargs):
            self.assertEqual(self.post(f"/{created['id']}/cancel", {}).status_code, 200)
            return self.answer(*args, **kwargs)

        cancelled_row, _ = self.run_task(created["id"], cancelled)
        self.assertEqual(cancelled_row["status"], "CANCELLED", cancelled_row)
        self.assertFalse(cancelled_row["report"])
        self.login()
        retry = self.post(f"/{created['id']}/retry", {"request_id": str(uuid4())})
        self.assertEqual(retry.status_code, 202, retry.text)
        self.assertEqual(retry.json()["input"]["snapshots"], cancelled_row["input"]["snapshots"])
        done, remote = self.run_task(retry.json()["id"])
        self.assertEqual(done["status"], "COMPLETED", done)
        self.assertEqual(remote.call_args.args[2], f"secret-{self.admin_id}")
        self.login(self.member_name)
        created = self.post("", self.payload()).json()
        with self.factory() as db:
            db.get(AIConnection, self.member_id).version += 1
            db.commit()
        failed, remote = self.run_task(created["id"])
        self.assertEqual(failed["status"], "FAILED", failed)
        remote.assert_not_called()

    def test_prototype_exact_segment_repair_and_free_revalidation_keep_raw_candidate(self):
        from app.modules.change_analysis import comparison

        data, _ = sample("prototype")
        before_text = data["snapshots"][0]["units"][0]["segments"][0]["text"]
        after_text = data["snapshots"][1]["units"][0]["segments"][0]["text"]
        url = "https://prototype.example.invalid/fixed/"
        with self.factory() as db:
            source = SourceDocument(
                project_id=self.project,
                purpose="PROTOTYPE",
                kind="LINK",
                name="固定原型段号测试",
                url=url,
                current_version=1,
            )
            db.add(source)
            db.commit()
            source_id = source.id
        payload = {
            "request_id": str(uuid4()),
            "title": "原型引用段号测试",
            "mode": "PROTOTYPE_CHANGE",
            "targets": ["BUSINESS_IMPACT"],
            "confirmed": True,
            "pairs": [
                {
                    "kind": "LINK_PROTOTYPE",
                    "source_id": source_id,
                    "update_mode": "FULL_REPLACEMENT",
                    "baseline_report_id": 1,
                    "paths": ["order.html"],
                    "snapshot": "b" * 64,
                    "url": url,
                }
            ],
        }
        raw_answers = []

        def wrong_segment(*args, **kwargs):
            sent = json.loads(args[5][0]["text"])
            result = comparison.unchanged_report(sent)
            result["evidence"] = [
                {
                    "key": "E1",
                    "side": "AFTER",
                    "pair_ref": "p1",
                    "snapshot_ref": "p1-after",
                    "unit_id": "pages",
                    "segment_id": "s1",
                    "kind": "TEXT",
                    "start_line": None,
                    "end_line": None,
                    "excerpt": after_text,
                    "observation": "",
                }
            ]
            raw = json.dumps(result, ensure_ascii=False)
            raw_answers.append(raw)
            return raw

        with (
            patch.object(
                sources,
                "link_baseline",
                return_value={
                    "snapshot_ref": "a" * 64,
                    "segments": [{"location": "固定页面正文", "text": before_text}],
                },
            ),
            patch.object(
                sources.prototypes,
                "link_pages",
                return_value={
                    "snapshot_ref": "b" * 64,
                    "segments": [
                        {"location": "固定页面正文", "text": after_text},
                        {"location": "公共批注", "text": "其他公共批注，不含所引原文。"},
                    ],
                },
            ),
        ):
            first = self.post("", payload).json()
            done, remote = self.run_task(first["id"], wrong_segment)
            remote.assert_called_once()
            self.assertEqual(done["status"], "COMPLETED", done.get("error_code"))
            self.assertEqual(done["report"]["evidence"][0]["segment_id"], "s0")
            correction = done["evidence_corrections"][0]
            self.assertEqual(correction["kind"], "EXACT_TEXT_SEGMENT")
            self.assertEqual(correction["original_segment_id"], "s1")
            self.assertEqual(correction["segment_id"], "s0")
            self.assertEqual(
                artifacts.candidate_path(first["id"]).read_bytes(), raw_answers[-1].encode()
            )
            second = self.post("", {**payload, "request_id": str(uuid4())}).json()
            with patch.object(evidence, "normalize_coordinates", side_effect=lambda d, r: (r, [])):
                failed, remote = self.run_task(second["id"], wrong_segment)
            remote.assert_called_once()
            self.assertEqual(failed["status"], "FAILED")
            self.assertEqual(failed["error_code"], "change_evidence_invalid")
            self.assertTrue(failed["can_revalidate"])
            original_candidate = artifacts.candidate_path(second["id"]).read_bytes()
            original_input = copy.deepcopy(failed["input"])
            with self.factory() as db:
                fixed_skill = copy.deepcopy(
                    db.get(ChangeAnalysisTask, second["id"]).metadata_snapshot["skill"]
                )
            with patch("app.integrations.responses.analyze") as no_ai:
                recovered = self.post(f"/{second['id']}/revalidate", {})
            no_ai.assert_not_called()
            self.assertEqual(recovered.status_code, 200, recovered.text)
            self.assertEqual(recovered.json()["status"], "COMPLETED")
            self.assertEqual(recovered.json()["input"], original_input)
            self.assertEqual(recovered.json()["report"]["evidence"][0]["segment_id"], "s0")
            self.assertEqual(
                artifacts.candidate_path(second["id"]).read_bytes(), original_candidate
            )
            with self.factory() as db:
                row = db.get(ChangeAnalysisTask, second["id"])
                self.assertEqual(row.metadata_snapshot["skill"], fixed_skill)
                self.assertEqual(row.handling, {})
            with patch.object(evidence, "normalize_coordinates") as no_normalize:
                strict = self.post(
                    "/import",
                    {
                        "title": "仍严格校验导入",
                        "input_filename": "input.json",
                        "report_filename": "report.json",
                        "input_json": json.dumps(original_input, ensure_ascii=False),
                        "report_json": original_candidate.decode(),
                        "bindings": [],
                    },
                )
            no_normalize.assert_not_called()
            self.assertEqual(strict.status_code, 422)
            self.assertEqual(strict.json()["detail"], "change_evidence_invalid")

    def test_gate_revoke_and_local_scope_is_not_deleted(self):
        bad = self.payload()
        bad["targets"].append("FRONTEND_BACKEND_MISMATCH")
        self.assertEqual(self.post("", bad).status_code, 422)
        payload = self.payload()
        payload["pairs"][0]["after_local"]["scope"] = ["different/"]
        payload["pairs"][0]["after_local"]["files"] = []
        with self.factory() as db:
            actor = db.get(UserAccount, self.member_id)
            raw = schemas.AnalysisRequest.model_validate(payload).model_dump(mode="json")
            s = sources.code_snapshot(
                self.project, raw["pairs"][0], "after", "test-after", actor, db
            )
            self.assertEqual(s["units"][0]["presence"], "OUT_OF_SCOPE")
        created = self.post("", self.payload()).json()
        with self.factory() as db:
            member = db.scalar(
                select(ProjectMember).where(
                    ProjectMember.project_id == self.project,
                    ProjectMember.user_id == self.member_id,
                )
            )
            db.delete(member)
            db.commit()
        _, remote = self.run_task(created["id"])
        remote.assert_not_called()

    def test_paired_import_requires_real_project_role_binding(self):
        data, report = sample("code")
        for value in (data, report):
            value["project_id"] = self.project
        for s in data["snapshots"]:
            s["provenance"].update(source_kind="LOCAL", commit="")
        body = {
            "title": "导入变更",
            "input_filename": "input.json",
            "report_filename": "report.json",
            "input_json": json.dumps(data),
            "report_json": json.dumps(report),
            "bindings": [
                {
                    "snapshot_ref": s["snapshot_ref"],
                    "kind": "LOCAL",
                    "source_id": self.source_id,
                    "source_version": 1,
                }
                for s in data["snapshots"]
            ],
        }
        first = self.post("/import", body)
        self.assertEqual(first.status_code, 201, first.text)
        duplicate = self.post("/import", body)
        self.assertEqual(duplicate.json()["id"], first.json()["id"])
        self.assertTrue(duplicate.json()["duplicate"])
        bad = copy.deepcopy(body)
        bad["bindings"] = []
        self.assertEqual(self.post("/import", bad).status_code, 422)

    def test_full_input_does_not_skip_ai_on_static_no_change_and_worker_recovers(self):
        from app.modules.change_analysis import comparison

        payload = self.payload()
        payload["pairs"][0]["after_local"]["files"] = copy.deepcopy(
            payload["pairs"][0]["before_local"]["files"]
        )
        created = self.post("", payload).json()

        def analyze(*args, **kwargs):
            data = json.loads(args[5][0]["text"])
            self.assertEqual(data["comparison_pairs"][0]["text_diffs"], [])
            result = comparison.unchanged_report(data)
            result["summary"]["conclusion"] = "合成模型已检查全部固定内容，未发现变化。"
            return json.dumps(result, ensure_ascii=False)

        with patch.object(batching, "plan") as no_planning:
            done, remote = self.run_task(created["id"], analyze)
        remote.assert_called_once()
        no_planning.assert_not_called()
        self.assertEqual(done["status"], "COMPLETED", done)
        self.assertEqual(done["report"]["outcome"], "BLOCKED")
        self.assertEqual(done["report"]["risks"], [])
        with self.factory() as db:
            saved = db.get(ChangeAnalysisTask, created["id"])
            self.assertNotIn("no_ai", saved.metadata_snapshot)
        created = self.post("", self.payload()).json()
        with self.factory() as db:
            self.assertEqual(execution.claim(db), created["id"])
            execution.recover(db)
            self.assertEqual(
                db.get(ChangeAnalysisTask, created["id"], populate_existing=True).status, "FAILED"
            )

    def test_requirement_versions_are_actual_fixed_content_and_import_binding_is_checked(self):
        data, report = sample("requirement")
        texts = [s["units"][0]["segments"][0]["text"] for s in data["snapshots"]]
        base = f"/api/projects/{self.project}/documents"
        revision = self.client.get(base).json()["revision"]
        response = self.client.post(
            base + "/upload",
            params={"filename": "order.md", "revision": revision, "upload_id": str(uuid4())},
            content=texts[0].encode(),
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(response.status_code, 201, response.text)
        old = response.json()["documents"][0]
        response = self.client.post(
            base + "/upload",
            params={
                "filename": "order.md",
                "revision": response.json()["revision"],
                "upload_id": str(uuid4()),
                "document_id": old["id"],
            },
            content=texts[1].encode(),
            headers=test_auth.ORIGIN,
        )
        self.assertEqual(response.status_code, 201, response.text)
        newest = response.json()["documents"][0]
        payload = {
            "request_id": str(uuid4()),
            "title": "需求增量",
            "mode": "REQUIREMENT_CHANGE",
            "targets": ["BUSINESS_IMPACT"],
            "confirmed": True,
            "pairs": [
                {
                    "kind": "FILE",
                    "source_id": old["id"],
                    "before_version_id": old["current"]["id"],
                    "after_version_id": newest["current"]["id"],
                    "update_mode": "INCREMENTAL_SUPPLEMENT",
                }
            ],
        }
        with self.factory() as db:
            frozen, bindings, binaries = sources.prepare(
                self.project,
                payload["request_id"],
                schemas.AnalysisRequest.model_validate(payload).model_dump(mode="json"),
                db.get(UserAccount, self.member_id),
                db,
            )
        self.assertEqual([s["units"][0]["segments"][0]["text"] for s in frozen["snapshots"]], texts)
        self.assertEqual(frozen["comparison_pairs"][0]["update_mode"], "INCREMENTAL_SUPPLEMENT")
        self.assertFalse(binaries)
        self.assertEqual(bindings[0]["version_id"], old["current"]["id"])
        # File import must bind to the version whose actual text matches the frozen snapshot.
        for value in (data, report):
            value["project_id"] = self.project
        data["cases"] = []
        report["case_impacts"] = []
        report["regression_scope"] = []
        data["targets"] = ["BUSINESS_IMPACT"]
        report["target_results"] = report["target_results"][:1]
        body = {
            "title": "需求导入",
            "input_filename": "input.json",
            "report_filename": "report.json",
            "input_json": json.dumps(data),
            "report_json": json.dumps(report),
            "bindings": [
                {
                    "snapshot_ref": data["snapshots"][n]["snapshot_ref"],
                    "document_id": old["id"],
                    "version_id": v,
                }
                for n, v in enumerate((old["current"]["id"], newest["current"]["id"]))
            ],
        }
        response = self.post("/import", body)
        self.assertEqual(response.status_code, 201, response.text)
        bad = copy.deepcopy(body)
        bad["bindings"][0]["version_id"] = newest["current"]["id"]
        self.assertEqual(self.post("/import", bad).status_code, 422)

    def test_link_prototype_uses_saved_old_body_not_directory_and_new_body_is_frozen(self):
        from app.db.models import RequirementRiskReport, SourceDocument
        from app.modules.prototypes import service as prototypes

        url = "https://prototype.geekuat.com/p/Synthetic/"
        with self.factory() as db:
            source = SourceDocument(
                project_id=self.project,
                purpose="PROTOTYPE",
                kind="LINK",
                name="合成原型",
                url=url,
                current_version=1,
            )
            db.add(source)
            db.flush()
            saved = RequirementRiskReport(
                project_id=self.project,
                title="旧页面",
                input_filename="input.json",
                report_filename="report.json",
                sha256="a" * 64,
                input={
                    "materials": [
                        {
                            "source_id": "P1",
                            "origin": "PROTOTYPE",
                            "kind": "LINK",
                            "snapshot_ref": "old-body-v1",
                            "read_state": "PARTIAL",
                            "segments": [
                                {
                                    "segment_id": "s1",
                                    "location": "page-1.html",
                                    "text": "<button>取消</button>",
                                    "image_ref": "",
                                }
                            ],
                        }
                    ]
                },
                report={"risks": []},
                bindings=[
                    {
                        "source_id": "P1",
                        "document_id": source.id,
                        "kind": "LINK",
                        "purpose": "PROTOTYPE",
                        "url": url,
                    }
                ],
                created_by=self.member_id,
            )
            db.add(saved)
            db.commit()
            sid, rid = source.id, saved.id
        payload = {
            "request_id": str(uuid4()),
            "title": "原型变更",
            "mode": "PROTOTYPE_CHANGE",
            "targets": ["BUSINESS_IMPACT"],
            "confirmed": True,
            "pairs": [
                {
                    "kind": "LINK_PROTOTYPE",
                    "source_id": sid,
                    "baseline_report_id": rid,
                    "url": url,
                    "paths": ["page-1.html"],
                    "snapshot": "b" * 64,
                    "update_mode": "FULL_REPLACEMENT",
                }
            ],
        }
        with (
            self.factory() as db,
            patch.object(
                prototypes,
                "link_pages",
                return_value={
                    "snapshot_ref": "new-body-v2",
                    "segments": [{"location": "page-1.html", "text": "<button>取消订单</button>"}],
                },
            ) as reader,
        ):
            data, _, _ = sources.prepare(
                self.project,
                payload["request_id"],
                schemas.AnalysisRequest.model_validate(payload).model_dump(mode="json"),
                db.get(UserAccount, self.member_id),
                db,
            )
            self.assertEqual(
                data["snapshots"][0]["units"][0]["segments"][0]["text"], "<button>取消</button>"
            )
            self.assertEqual(data["snapshots"][1]["provenance"]["version_ref"], "new-body-v2")
            self.assertFalse(data["snapshots"][1]["scope_complete"])
            reader.assert_called_once()
        with self.factory() as db:
            saved = db.get(RequirementRiskReport, rid)
            saved.input = {
                "materials": [
                    {
                        "source_id": "P1",
                        "snapshot_ref": "URL",
                        "read_state": "NOT_LOADED",
                        "segments": [],
                    }
                ]
            }
            db.commit()
        self.assertEqual(self.post("", payload).status_code, 422)
