"""Native business CLI against synthetic local providers; no real key or billed request."""

import base64
import json
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from test_codex_probe import FakeProvider

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import ai_client, codex_exec
from app.security.secrets import credential_cipher


class NativeContractTests(unittest.TestCase):
    def test_version_detection_never_blocks_an_installed_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "codex.exe"
            executable.touch()
            settings = Settings(ai_cli_executable=executable)
            for output, expected in (
                (b"codex-cli 0.169.1", "0.169.1"),
                (b"codex-cli 1.0.0-beta.1", "1.0.0-beta.1"),
                (b"", None),
            ):
                with (
                    self.subTest(output=output),
                    patch.object(codex_exec, "Settings", return_value=settings),
                    patch.object(
                        codex_exec.subprocess,
                        "run",
                        return_value=subprocess.CompletedProcess([], 0, stdout=output),
                    ),
                ):
                    codex_exec._inspect.cache_clear()
                    runtime = codex_exec.runtime_status()
                    self.assertTrue(runtime["available"])
                    self.assertTrue(runtime["probe_available"])
                    self.assertEqual(runtime["version"], expected)

    def test_native_final_message_keeps_final_after_progress_and_recovered_error(self):
        def answer(text):
            return {"type": "item.completed", "item": {"type": "agent_message", "text": text}}

        events = [
            answer("进度说明"),
            {"type": "error", "message": "retrying"},
            answer('{"cases":[]}'),
            {"type": "turn.completed"},
        ]
        self.assertEqual(codex_exec.final_message(events, 0, native=True), '{"cases":[]}')
        with self.assertRaises(AppError):
            codex_exec.final_message(events, 0)
        with self.assertRaises(AppError):
            codex_exec.final_message(events, 1, native=True)

    def test_native_input_preserves_full_text_roles_order_and_skill(self):
        text = "完整固定资料\n" * 300000
        messages = [
            {"role": "developer", "content": [{"type": "input_text", "text": "固定契约"}]},
            {"role": "user", "content": [{"type": "input_text", "text": text}]},
        ]
        original = deepcopy(messages)
        rules, payload, images = codex_exec.native_input("固定Skill", messages)
        self.assertEqual(json.loads(payload)["messages"], messages)
        self.assertEqual(messages, original)
        self.assertTrue(rules.startswith("固定Skill\n\n固定契约"))
        self.assertEqual(images, [])

    def test_pdf_and_remote_image_are_explicitly_rejected(self):
        for part in (
            {"type": "input_file", "file_data": "data:application/pdf;base64,AA=="},
            {"type": "input_image", "image_url": "https://example.com/a.png"},
        ):
            with self.assertRaises(AppError) as caught:
                codex_exec.native_input("规则", [{"role": "user", "content": [part]}])
            self.assertEqual(caught.exception.detail, "ai_cli_attachment_unsupported")


@unittest.skipUnless(os.name == "nt", "Windows native CLI integration")
class RealNativeCLITests(unittest.TestCase):
    def setUp(self):
        if not codex_exec.runtime_status()["available"]:
            self.skipTest("requires installed CLI exe")

    def call(self, provider, text="合成业务输入", extra=()):
        with (
            provider,
            patch(
                "app.integrations.codex_exec.subprocess.Popen", wraps=codex_exec.subprocess.Popen
            ) as process,
        ):
            stats = {}
            try:
                result = ai_client.analyze(
                    provider.url,
                    "gpt-6.1-sol",
                    "NATIVE-FAKE-KEY",
                    "low",
                    "固定合成Skill",
                    [{"type": "input_text", "text": text}, *extra],
                    call_mode="CODEX_EXEC",
                    diagnostics=stats,
                )
            except AppError:
                own = Settings().ai_cli_work_path / stats["cli_attempt_id"] / "events.enc"
                print(
                    "synthetic CLI diagnostics",
                    credential_cipher("ai_key_storage_unavailable")
                    .decrypt(own.read_bytes())
                    .decode(),
                )
                print("synthetic provider paths", [x[0] for x in provider.requests])
                raise
            arguments = process.call_args.args[0]
            self.last_attempt = stats["cli_attempt_id"]
            self.assertFalse(
                any(
                    "request_max_retries" in arg or "stream_max_retries" in arg for arg in arguments
                )
            )
            self.assertFalse(
                any("model_post_turn_compact_threshold_percent" in arg for arg in arguments)
            )
            self.assertNotIn("NATIVE-FAKE-KEY", " ".join(arguments))
            return result, provider.requests, arguments

    def test_native_business_report_and_large_input_reach_actual_cli(self):
        text = "合成大输入原文\n" * 60000
        result, requests, _ = self.call(FakeProvider(text='{"cases":[],"complete":true}'), text)
        self.assertEqual(json.loads(result), {"cases": [], "complete": True})
        self.assertEqual(len(requests), 1)
        payload = requests[0][2]
        self.assertIn("固定合成Skill", json.dumps(payload, ensure_ascii=False))
        self.assertTrue(
            any(
                part.get("type") == "input_text"
                and part.get("text", "").startswith('{"messages"')
                and json.loads(part["text"])["messages"][0]["content"][0]["text"] == text
                for item in payload["input"]
                for part in item.get("content", [])
                if isinstance(part, dict)
            )
        )
        self.assertEqual(requests[0][1], "Bearer NATIVE-FAKE-KEY")

    def test_cli_native_retry_and_multiple_requests_are_not_blocked(self):
        for mode in ("native_retry", "native_round"):
            with self.subTest(mode=mode):
                result, requests, _ = self.call(FakeProvider(mode, text='{"result":"done"}'))
                self.assertEqual(json.loads(result), {"result": "done"})
                self.assertGreaterEqual(len(requests), 2)

    def test_over_stdin_limit_uses_real_mcp_reader_in_own_directory(self):
        text = "大文件完整原文\n" * 160000
        result, requests, args = self.call(
            FakeProvider("native_file", text='{"result":"read"}'), text
        )
        self.assertEqual(json.loads(result), {"result": "read"})
        self.assertEqual(len(requests), 2)
        self.assertTrue(any("mcp_servers.filesystem=" in arg for arg in args))
        outputs = [
            x
            for x in requests[1][2]["input"]
            if x.get("type") in ("function_call_output", "custom_tool_call_output")
        ]
        self.assertTrue(outputs)
        self.assertIn("大文件完整原文", json.dumps(outputs, ensure_ascii=False))
        text_blocks = [
            x["text"]
            for item in outputs
            for x in item.get("output", [])
            if isinstance(x, dict) and x.get("type") == "input_text"
        ]
        parsed = next(json.loads(x) for x in text_blocks if x.startswith('{"tools":'))
        expected = json.dumps(
            {"messages": [{"role": "user", "content": [{"type": "input_text", "text": text}]}]},
            ensure_ascii=False,
        )
        self.assertEqual(parsed["characters"], len(expected))
        self.assertEqual(parsed["tail"], expected[-150:])
        self.assertTrue(
            {"mcp__filesystem__read_text_file", "mcp__filesystem__get_file_info"}.issubset(
                parsed["tools"]
            )
        )
        self.assertNotIn("exec_command", parsed["tools"])
        self.assertNotIn("view_image", parsed["tools"])
        self.assertFalse(any("filesystem__write" in name for name in parsed["tools"]))
        environment = json.dumps(requests[0][2]["input"], ensure_ascii=False)
        self.assertIn('access=\\"deny\\"', environment)

    def test_native_image_bytes_are_preserved_in_actual_model_request(self):
        def chunk(kind, data):
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data))
            )

        binary = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 32, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\x00" + b"\xff\x00\x00" * 32) * 32))
            + chunk(b"IEND", b"")
        )
        encoded = base64.b64encode(binary).decode()
        extra = [{"type": "input_image", "image_url": "data:image/png;base64," + encoded}]
        result, requests, args = self.call(FakeProvider(text='{"image":"observed"}'), extra=extra)
        self.assertEqual(json.loads(result), {"image": "observed"})
        self.assertIn("--image", args)
        parts = [
            part
            for item in requests[0][2]["input"]
            for part in item.get("content", [])
            if isinstance(part, dict) and part.get("type") == "input_image"
        ]
        if not parts:
            print(
                "synthetic image user input",
                json.dumps(
                    [x for x in requests[0][2]["input"] if x.get("role") == "user"],
                    ensure_ascii=False,
                )[-1700:],
            )
        self.assertEqual(len(parts), 1)
        self.assertEqual(
            base64.b64decode(parts[0]["image_url"].partition(",")[2]), base64.b64decode(encoded)
        )
