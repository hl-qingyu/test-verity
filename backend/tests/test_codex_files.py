"""Complete scoped task input reading; no platform file access or model requests."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.integrations.codex_files import TaskFiles


class TaskFileTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "outputs"
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_multibyte_complete_file_reassembles_without_loss_over_stdin_limit(self):
        text = '{"固定资料":"' + "多字节完整原文🌱\n" * 220000 + '"}'
        binary = text.encode()
        (self.folder / "input.json").write_bytes(binary)
        reader = TaskFiles(self.folder)
        chunks = []
        offset = 0
        while True:
            result = reader.read({"offset_bytes": offset, "max_bytes": 32768})
            chunks.append(result["text"])
            self.assertEqual(result["sha256"], hashlib.sha256(binary).hexdigest())
            if result["eof"]:
                break
            self.assertGreater(result["next_offset_bytes"], offset)
            offset = result["next_offset_bytes"]
        self.assertEqual("".join(chunks), text)

    def test_parent_absolute_other_file_and_invalid_ranges_are_denied(self):
        (self.folder / "input.json").write_text("授权资料", encoding="utf-8")
        (self.folder / "secret.env").write_text("synthetic secret", encoding="utf-8")
        reader = TaskFiles(self.folder)
        for path in ("../secret.env", str(self.folder / "secret.env"), "secret.env"):
            with self.assertRaises(ValueError):
                reader.read({"path": path})
            with self.assertRaises(ValueError):
                reader.search({"path": path, "query": "secret"})
        for values in (
            {"offset_bytes": -1},
            {"max_bytes": 0},
            {"max_bytes": 999999},
            {"offset_bytes": 1},
        ):
            with self.assertRaises(ValueError):
                reader.read(values)

    def test_literal_search_paginates_without_mutating_input(self):
        binary = ("前缀[needle]后缀\n" * 30).encode()
        path = self.folder / "input.json"
        path.write_bytes(binary)
        reader = TaskFiles(self.folder)
        first = reader.search({"query": "[needle]"})
        second = reader.search({"query": "[needle]", "offset_bytes": first["next_offset_bytes"]})
        self.assertEqual(len(first["match_offsets_bytes"]), 20)
        self.assertEqual(len(second["match_offsets_bytes"]), 10)
        self.assertTrue(second["eof"])
        self.assertEqual(path.read_bytes(), binary)
