"""Reading layout preserves exact input while keeping each tool result small."""

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.errors import AppError
from app.integrations import cli_reading, codex_terminal
from app.modules.case_generation import reading


def entries(root, page="index.json"):
    result = []
    for item in json.loads((root / page).read_text(encoding="utf-8"))["entries"]:
        if item["kind"] == "catalogue":
            result.extend(entries(root, item["file"]))
        else:
            result.append(item)
    return result


def restore(root, rows, message, part):
    selected = [r for r in rows if r.get("message") == message and r.get("part") == part]
    view = "".join(
        (root / r["file"]).read_bytes().decode() for r in selected if r["kind"] == "text_part"
    )
    restored, cursor, delta = [], 0, 0
    for r in selected:
        if r["kind"] != "embedded_image":
            continue
        start = r["start"] - delta
        restored.append(view[cursor:start])
        restored.append(
            r["uri_prefix"] + base64.b64encode((root / r["file"]).read_bytes()).decode()
        )
        cursor = start + len(r["replacement"])
        delta += r["end"] - r["start"] - len(r["replacement"])
    return "".join(restored) + view[cursor:]


class ReadingFilesTests(unittest.TestCase):
    def setUp(self):
        self.cipher = Fernet(Fernet.generate_key())
        crypto = patch.object(cli_reading, "credential_cipher", return_value=self.cipher)
        crypto.start()
        self.addCleanup(crypto.stop)

    def test_structured_layout_splits_without_losing_lines_and_verifies_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            fixed = b'{"snapshot":"fixed"}'
            (work / "input.json").write_bytes(fixed)
            original = ("完整内容\r\n" * 13_000) + "长行" * 45_000
            path = cli_reading.build_files(
                work, [{"path": "source-1/原型:首页.txt", "text": original}], "先读索引"
            )
            self.assertEqual(cli_reading.resume_index(work), path)
            root = (work / path).parent
            parts = sorted(root.glob("source-1/原型_首页.part-*.txt"))
            self.assertGreaterEqual(len(parts), 3)
            self.assertEqual(
                "".join(p.read_bytes().decode().split("\n", 1)[1] for p in parts), original
            )
            self.assertEqual((work / "input.json").read_bytes(), fixed)
            parts[0].write_text("changed", encoding="utf-8")
            with self.assertRaises(AppError) as caught:
                cli_reading.resume_index(work)
            self.assertEqual(caught.exception.detail, "ai_cli_reading_unavailable")

    def test_structured_paths_cannot_escape_or_collide_after_sanitization(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / "input.json").write_text("{}", encoding="utf-8")
            for paths in (
                ["../escape.txt"],
                ["D:/absolute.txt"],
                ["a:b.txt"],
                ["index.md"],
                ["x?.txt", "x*.txt"],
            ):
                with self.subTest(paths=paths), self.assertRaises(AppError):
                    cli_reading.build_files(
                        work, [{"path": path, "text": "synthetic"} for path in paths], ""
                    )

    def test_case_generation_layout_preserves_prototype_and_document_sections(self):
        original = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "skill/case-generation/examples/compact-input.json"
            ).read_text(encoding="utf-8")
        )
        text = "固定正文\r\n第二行"
        prototype = {
            **original["materials"][0],
            "snapshot_ref": "prototype",
            "kind": "LINK",
            "segments": [{"segment_id": "page", "location": "订单 / 首页", "text": text}],
        }
        word = {
            **prototype,
            "snapshot_ref": "document",
            "kind": "FILE",
            "segments": [{"segment_id": "paragraph", "location": "第 1 段", "text": text}],
        }
        for materials in ([prototype], [prototype, word], [word]):
            with self.subTest(materials=[item["snapshot_ref"] for item in materials]):
                data = {**original, "materials": materials}
                files = reading.reading_layout(data, [])
                snippets = [entry for entry in files if "/segment-" in entry["path"]]
                self.assertEqual(len(snippets), len(materials))
                for material, entry in zip(materials, snippets, strict=True):
                    metadata, body = entry["text"].split("\n", 1)
                    self.assertEqual(json.loads(metadata)["snapshot_ref"], material["snapshot_ref"])
                    self.assertEqual(body, text)

    def test_full_unicode_text_and_embedded_media_reassemble_exactly_without_printing_base64(self):
        binary = b"RIFF" + (100000).to_bytes(4, "little") + b"WEBP" + b"synthetic" * 20000
        uri = "data:image/webp;base64," + base64.b64encode(binary).decode()
        html = '<img src="' + uri + '">\r\n' + "文字🌱\t" * 10000 + '<img src="' + uri + '">'
        data = {
            "messages": [
                {"role": "developer", "content": "固定Skill"},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": html},
                        {"type": "input_text", "text": "原文尾部 END"},
                        {"type": "input_image", "attachment": "image-1.png"},
                    ],
                },
            ]
        }
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            raw = json.dumps(data, ensure_ascii=False).encode()
            (work / "input.json").write_bytes(raw)
            index = cli_reading.build(work)
            root = (work / index).parent
            rows = entries(root)
            self.assertEqual(restore(root, rows, 1, 0), html)
            self.assertEqual(restore(root, rows, 1, 1), "原文尾部 END")
            self.assertEqual(restore(root, rows, 0, 0), "固定Skill")
            self.assertEqual(
                [r["role"] for r in rows if r["kind"] == "message"], ["developer", "user"]
            )
            self.assertEqual(len(list(root.glob("media-*"))), 1)
            self.assertEqual(len([r for r in rows if r["kind"] == "embedded_image"]), 2)
            self.assertEqual(
                [r for r in rows if r["kind"] == "attachment"][0]["content"],
                data["messages"][1]["content"][2],
            )
            for p in root.glob("text-*"):
                value = p.read_bytes().decode()
                self.assertLessEqual(len(value), cli_reading.TEXT_CHARACTERS)
                self.assertNotIn(uri, value)
            for p in root.glob("*.json"):
                self.assertLessEqual(p.stat().st_size, cli_reading.CATALOGUE_BYTES + 200)
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            modified = {p.name: p.stat().st_mtime_ns for p in root.iterdir()}
            with (
                patch.object(cli_reading, "materialize", side_effect=AssertionError("must reuse")),
                patch.object(
                    cli_reading.tempfile, "mkdtemp", side_effect=AssertionError("no rebuild")
                ),
            ):
                self.assertEqual(cli_reading.build(work), index)
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            self.assertEqual(modified, {p.name: p.stat().st_mtime_ns for p in root.iterdir()})
            self.assertEqual((work / "input.json").read_bytes(), raw)
            next(root.glob("text-*")).write_bytes(b"changed")
            with self.assertRaises(AppError):
                cli_reading.build(work)

    def test_cached_content_changes_are_rejected_even_when_size_and_timestamp_are_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / "input.json").write_text('{"messages":[{"role":"user","content":"ABCDE"}]}')
            root = (work / cli_reading.build(work)).parent
            text = next(root.glob("text-*"))
            stat = text.stat()
            text.write_bytes(b"ABXDE")
            os.utime(text, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            with self.assertRaises(AppError):
                cli_reading.build(work)

    def test_missing_or_forged_cache_does_not_silently_accept_modified_files(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / "input.json").write_text('{"messages":[{"role":"user","content":"original"}]}')
            index = cli_reading.build(work)
            checksum = next(work.glob("*.integrity.enc"))
            first_token = checksum.read_bytes()
            checksum.write_bytes(b'{"files":{}}')
            with self.assertRaises(AppError):
                cli_reading.build(work)
            checksum.write_bytes(first_token)
            next((work / index).parent.glob("text-*")).unlink()
            with self.assertRaises(AppError):
                cli_reading.build(work)

    def test_old_reading_directory_is_verified_and_cached_once_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / "input.json").write_text('{"messages":[{"role":"user","content":"old"}]}')
            index = cli_reading.build(work)
            root = (work / index).parent
            modified = {p.name: p.stat().st_mtime_ns for p in root.iterdir()}
            next(work.glob("*.integrity.enc")).unlink()
            with patch.object(cli_reading, "materialize", wraps=cli_reading.materialize) as build:
                self.assertEqual(cli_reading.build(work), index)
                self.assertEqual(cli_reading.build(work), index)
            self.assertEqual(build.call_count, 1)
            self.assertEqual(modified, {p.name: p.stat().st_mtime_ns for p in root.iterdir()})

    def test_invalid_image_and_svg_stay_literal_and_catalogue_pages_remain_bounded(self):
        value = '<svg src="data:image/svg+xml,%3Csvg%3E"> data:image/png;base64,QUJD '
        data = {
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": value + str(i)} for i in range(600)],
                }
            ]
        }
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            (work / "input.json").write_bytes(json.dumps(data).encode())
            root = (work / cli_reading.build(work)).parent
            rows = entries(root)
            self.assertEqual(restore(root, rows, 0, 599), value + "599")
            self.assertFalse(list(root.glob("media-*")))
            for p in root.glob("*.json"):
                self.assertLessEqual(p.stat().st_size, cli_reading.CATALOGUE_BYTES + 200)
            self.assertFalse(list(work.glob(".reading-*")))

    def test_resume_adds_reading_guidance_without_overwriting_original_input_skill_or_history(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = SimpleNamespace(
                ai_cli_terminal_work_path=Path(folder), ai_cli_executable=Path("codex.exe")
            )
            with patch.object(codex_terminal, "Settings", return_value=settings):
                identity = str(uuid4())
                root, state, work, args = codex_terminal.prepare(
                    identity,
                    "https://example.com",
                    "m",
                    "low",
                    "固定规则原文",
                    {"messages": [{"role": "user", "content": "original"}]},
                    False,
                )
                original, skill = (
                    (work / "input.json").read_bytes(),
                    (state / "instructions.txt").read_bytes(),
                )
                history = state / "original-history.jsonl"
                history.write_bytes(b"immutable native history")
                with patch.object(
                    cli_reading, "materialize", side_effect=AssertionError("no reload")
                ):
                    _, _, _, resume_args = codex_terminal.prepare(
                        identity,
                        "https://example.com",
                        "m",
                        "low",
                        "new wrong skill",
                        {"messages": []},
                        True,
                    )
                self.assertEqual((work / "input.json").read_bytes(), original)
                self.assertEqual((state / "instructions.txt").read_bytes(), skill)
                self.assertEqual(history.read_bytes(), b"immutable native history")
                configured = next(x for x in args if x.startswith("model_instructions_file="))
                content = Path(json.loads(configured.split("=", 1)[1])).read_text(encoding="utf-8")
                self.assertIn("固定规则原文", content)
                self.assertIn("reading-v1-", content)
                self.assertIn("truncated", content)
                self.assertIn("read_media_file", content)
                configured = next(
                    x for x in resume_args if x.startswith("model_instructions_file=")
                )
                resumed = Path(json.loads(configured.split("=", 1)[1])).read_text(encoding="utf-8")
                self.assertIn("无需从头重新加载全部资料", resumed)
                self.assertIn("历史中已完整读取", resumed)
