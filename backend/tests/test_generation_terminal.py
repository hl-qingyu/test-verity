"""Generation runs in the visible native CLI; synthetic model only, no billed request."""

import base64
import json
import os
import struct
import tempfile
import unittest
import zlib
from contextlib import nullcontext
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from test_codex_probe import FakeProvider

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import ai_client, codex_terminal
from app.integrations.terminal_policy import PolicyDenied
from app.integrations.terminal_result import TerminalResult


class GenerationTerminalResultTests(unittest.TestCase):
    def test_only_same_generation_turn_delivers_full_final_message(self):
        result = TerminalResult()
        result.request({"id": 1, "method": "turn/start", "params": {"threadId": "own"}})
        result.receive(
            {"method": "turn/started", "params": {"threadId": "own", "turn": {"id": "t"}}}
        )
        for text, thread, identity in [
            ("commentary", "own", "a"),
            ("wrong", "other", "b"),
            ('{"cases":[]}', "own", "c"),
        ]:
            result.receive(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": thread,
                        "turnId": "t",
                        "item": {"id": identity, "type": "agentMessage", "text": text},
                    },
                }
            )
        result.receive(
            {
                "method": "turn/completed",
                "params": {"threadId": "other", "turn": {"id": "t", "status": "completed"}},
            }
        )
        self.assertFalse(result.done.is_set())
        result.receive(
            {
                "method": "turn/completed",
                "params": {"threadId": "own", "turn": {"id": "t", "status": "completed"}},
            }
        )
        self.assertEqual(result.answer(), '{"cases":[]}')
        with self.assertRaises(PolicyDenied):
            result.request({"id": 2, "method": "turn/start", "params": {"threadId": "other"}})

    def test_failed_or_interrupted_output_never_becomes_a_complete_candidate(self):
        for status in ("failed", "interrupted", None):
            result = TerminalResult()
            result.status = status
            result.messages["a"] = "partial output"
            with self.assertRaises(AppError):
                result.answer()

    def test_start_rpc_error_finishes_without_waiting_for_a_turn_that_never_started(self):
        result = TerminalResult()
        result.request({"id": 7, "method": "turn/start", "params": {"threadId": "own"}})
        result.receive({"id": 6, "error": {"message": "unrelated"}})
        self.assertFalse(result.done.is_set())
        result.receive({"id": 7, "error": {"message": "synthetic model startup failure"}})
        self.assertTrue(result.done.is_set())
        with self.assertRaises(AppError) as error:
            result.answer()
        self.assertEqual(error.exception.detail, "generation_terminal_turn_failed")


@unittest.skipUnless(os.name == "nt", "Windows ConPTY integration")
class RealGenerationTerminalTests(unittest.TestCase):
    def test_resumed_cli_sends_continue_as_a_second_turn_using_the_same_history(self):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")
        with (
            tempfile.TemporaryDirectory() as folder,
            FakeProvider(text="SYNTHETIC_REPLY") as provider,
        ):
            identity = str(uuid4())
            local = SimpleNamespace(
                ai_cli_work_path=Path(folder), ai_cli_executable=settings.ai_cli_executable
            )
            deadline = monotonic() + 25

            def progress():
                if monotonic() > deadline:
                    raise AppError(409, "synthetic_deadline")

            with patch.object(codex_terminal, "Settings", return_value=local):
                first = None
                for execution, resume in ((1, False), (2, True)):
                    capture = TerminalResult()
                    # Old native history must receive the new guidance on resume.
                    guidance = codex_terminal.cli_reading.GUIDANCE if resume else ""
                    with (
                        patch.object(codex_terminal.cli_reading, "GUIDANCE", guidance),
                        patch.object(
                            codex_terminal.cli_reading,
                            "materialize",
                            side_effect=AssertionError("resume must reuse reading files"),
                        )
                        if resume
                        else nullcontext(),
                    ):
                        result = codex_terminal.run(
                            provider.url,
                            "gpt-6.1-sol",
                            "FAKE-KEY",
                            "low",
                            identity=identity,
                            execution=execution,
                            instructions="Synthetic fixed business Skill",
                            fixed_input={"synthetic": "complete fixed input"},
                            resume=resume,
                            initial_prompt="继续分析"
                            if resume
                            else "Read the fixed input and analyze",
                            capture=capture,
                            on_progress=progress,
                        )
                    self.assertEqual(result["answer"], "SYNTHETIC_REPLY")
                    if first is None:
                        first = capture.thread_id
                    else:
                        self.assertEqual(capture.thread_id, first)
                self.assertEqual(len(provider.requests), 2)
                request = json.dumps(provider.requests[-1][2], ensure_ascii=False)
                self.assertIn("继续分析", request)
                self.assertIn("SYNTHETIC_REPLY", request)
                self.assertIn("Synthetic fixed business Skill", request)
                self.assertIn("reading-v1-", request)
                self.assertIn("read_media_file", request)
                self.assertIn("无需从头重新加载全部资料", request)

    def run_generation(self, content, mode="ok"):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")
        with (
            tempfile.TemporaryDirectory() as folder,
            FakeProvider(mode, text='{"cases":[],"notes":[],"complete":true}') as provider,
        ):
            identity = str(uuid4())
            stats = {}
            deadline = monotonic() + 25
            local = SimpleNamespace(
                ai_cli_work_path=Path(folder), ai_cli_executable=settings.ai_cli_executable
            )
            with patch.object(codex_terminal, "Settings", return_value=local):

                def progress():
                    if monotonic() > deadline:
                        raise AppError(409, "synthetic_deadline")

                answer = ai_client.analyze(
                    provider.url,
                    "gpt-6.1-sol",
                    "FAKE-KEY",
                    "low",
                    "Synthetic fixed Skill",
                    content,
                    instruction_messages=[{"role": "developer", "content": "Fixed developer rule"}],
                    call_mode="CODEX_EXEC",
                    terminal_spec={"identity": identity, "execution": 9},
                    diagnostics=stats,
                    on_progress=progress,
                )
                fixed = json.loads(
                    (codex_terminal.directory(identity) / "input" / "input.json").read_text(
                        encoding="utf-8"
                    )
                )
                output = codex_terminal.output(identity, 9)
                self.assertEqual(output["resizes"][0], {"index": 0, "rows": 30, "cols": 110})
                self.assertEqual(answer, '{"cases":[],"notes":[],"complete":true}')
                self.assertIn("OpenAI Codex", "".join(output["chunks"]))
                self.assertEqual(stats["cli_terminal_id"], identity)
                self.assertEqual(stats["output_characters"], len(answer))
                self.assertEqual(
                    fixed["messages"][0], {"role": "developer", "content": "Fixed developer rule"}
                )
                return fixed, provider.requests

    def test_start_generation_submits_once_and_finishes_without_a_browser(self):
        text = "完整固定资料，无浏览器也必须执行。" * 100
        content = [{"type": "input_text", "text": text}]
        fixed, requests = self.run_generation(content)
        self.assertEqual(fixed["messages"][1], {"role": "user", "content": content})
        self.assertEqual(len(requests), 1)

    def test_standard_reading_files_reach_native_cli_with_images_and_no_truncated_text(self):
        from app.integrations import cli_reading

        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")

        # Valid synthetic 32x32 PNG. No real material, network model or credential.
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
        text = (
            "完整正文🌱" * 2000
            + '<img src="data:image/png;base64,'
            + base64.b64encode(binary).decode()
            + '">END_READING'
        )
        fixed = {"messages": [{"role": "user", "content": [{"type": "input_text", "text": text}]}]}
        with tempfile.TemporaryDirectory() as folder:
            identity = str(uuid4())
            local = SimpleNamespace(
                ai_cli_work_path=Path(folder), ai_cli_executable=settings.ai_cli_executable
            )
            with patch.object(codex_terminal, "Settings", return_value=local):
                _, _, work, _ = codex_terminal.prepare(
                    identity,
                    "https://example.com",
                    "gpt-6.1-sol",
                    "low",
                    "Fixed Skill",
                    fixed,
                    False,
                )
                index = cli_reading.build(work)
                program = (
                    "async function read(path){"
                    "const r=await tools.mcp__filesystem__read_text_file({path});"
                    "let p=r.structuredContent?.content;if(typeof p==='string')return p;"
                    "p=r.content[0].text;try{const o=JSON.parse(p);"
                    "return o.structuredContent?.content??o.content?.[0]?.text??p;}"
                    "catch{return p;}}"
                    f"const index={json.dumps(index)};"
                    "const root=index.slice(0,index.lastIndexOf('/')+1);"
                    "async function collect(page){"
                    "const v=JSON.parse(await read(root+page));let all=[];"
                    "for(const e of v.entries){"
                    "if(e.kind==='catalogue')all.push(...await collect(e.file));"
                    "else all.push(e);}return all;}"
                    "const rows=await collect('index.json');"
                    "const parts=rows.filter(x=>x.kind==='text_part');"
                    "text(await read(root+parts[0].file));"
                    "text({"
                    "tail:(await read(root+parts.at(-1).file)).slice(-100),parts:parts.length});"
                    "const media=rows.find(x=>x.kind==='embedded_image');"
                    "const r=await tools.mcp__filesystem__read_media_file({path:root+media.file});"
                    "for(const c of r.content??[])if(c.type==='image')image(c);"
                )
                with FakeProvider(
                    text='{"cases":[],"notes":[],"complete":true}', tool_program=program
                ) as provider:
                    result = codex_terminal.run(
                        provider.url,
                        "gpt-6.1-sol",
                        "FAKE-KEY",
                        "low",
                        identity=identity,
                        execution=1,
                        instructions="Fixed Skill",
                        fixed_input=fixed,
                        capture=TerminalResult(),
                        initial_prompt="Read the indexed input completely.",
                    )
                    self.assertEqual(result["answer"], '{"cases":[],"notes":[],"complete":true}')
                    self.assertEqual(len(provider.requests), 2)
                    request = provider.requests[-1][2]
                    outputs = [
                        x for x in request["input"] if x.get("type") == "custom_tool_call_output"
                    ]
                    actual = json.dumps(outputs, ensure_ascii=False)
                    self.assertIn("END_READING", actual)
                    self.assertIn("完整正文", actual)
                    self.assertNotIn("Warning: truncated output", actual)
                    images = [
                        p
                        for x in outputs
                        for p in x.get("output", [])
                        if isinstance(p, dict) and p.get("type") == "input_image"
                    ]
                    self.assertTrue(images, actual[-1000:])
                    self.assertEqual(
                        base64.b64decode(images[0]["image_url"].partition(",")[2]), binary
                    )
                    self.assertEqual(
                        (work / "input.json").read_text(encoding="utf-8"),
                        json.dumps(fixed, ensure_ascii=False),
                    )

    def test_native_tui_uses_upstream_filesystem_for_full_large_input(self):
        text = "标准文件服务完整原文🌱" * 100000 + "END_OF_FULL_INPUT"
        _, requests = self.run_generation([{"type": "input_text", "text": text}], "native_file")
        self.assertEqual(len(requests), 2)
        returned = json.dumps(requests[-1][2], ensure_ascii=False)
        self.assertIn("mcp__filesystem__read_text_file", returned)
        self.assertIn("END_OF_FULL_INPUT", returned)
        self.assertNotIn("mcp__verity_input__", returned)

    def test_preselected_image_original_bytes_reach_same_model_turn(self):
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
        content = [
            {"type": "input_text", "text": "Fixed image task"},
            {"type": "input_image", "image_url": "data:image/png;base64," + encoded},
        ]
        fixed, requests = self.run_generation(content)
        self.assertEqual(fixed["messages"][1]["content"][1]["attachment"], "image-1.png")
        self.assertIn(encoded, json.dumps(requests))
