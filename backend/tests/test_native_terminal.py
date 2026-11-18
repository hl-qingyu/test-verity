"""Native terminal transport uses only synthetic providers and fake credentials."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import ValidationError
from test_codex_probe import FakeProvider

from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import codex_terminal
from app.integrations.terminal_policy import PolicyDenied, TerminalPolicy
from app.modules.case_generation import native_terminal
from app.modules.case_generation.schemas import TerminalInput


class TerminalTransportTests(unittest.TestCase):
    def test_large_replay_preserves_raw_frames_and_resize_positions_in_bounded_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            cipher = Fernet(Fernet.generate_key())
            identity = str(uuid4())
            with (
                patch.object(
                    codex_terminal,
                    "Settings",
                    return_value=SimpleNamespace(ai_cli_work_path=Path(folder)),
                ),
                patch.object(codex_terminal, "credential_cipher", return_value=cipher),
            ):
                root = codex_terminal.directory(identity) / "output"
                root.mkdir(parents=True)
                chunks = [f"frame-{i:05d} " + ("文" * 160) for i in range(5000)]
                (root / "7.enc.jsonl").write_bytes(
                    b"".join(cipher.encrypt(x.encode()) + b"\n" for x in chunks)
                )
                sizes = [
                    {"cursor": 0, "rows": 34, "cols": 126},
                    {"cursor": 2000, "rows": 24, "cols": 80},
                ]
                (root / "7.sizes.enc.jsonl").write_bytes(
                    b"".join(cipher.encrypt(json.dumps(x).encode()) + b"\n" for x in sizes)
                )
                cursor = 0
                actual = []
                pages = 0
                positions = []
                while True:
                    page = codex_terminal.output(identity, 7, cursor)
                    pages += 1
                    self.assertLessEqual(sum(map(len, page["chunks"])), 256 * 1024 + 200)
                    positions.extend(
                        {**s, "index": s["index"] + cursor} for s in page.get("resizes", [])
                    )
                    actual.extend(page["chunks"])
                    cursor = page["next_cursor"]
                    if not page["has_more"]:
                        break
                self.assertEqual(actual, chunks)
                self.assertEqual(cursor, 5000)
                self.assertLess(pages, 10)
                self.assertEqual(
                    positions,
                    [
                        {"index": 0, "rows": 34, "cols": 126},
                        {"index": 2000, "rows": 24, "cols": 80},
                    ],
                )

    def test_native_turn_status_tracks_completion_and_next_turn_separately_from_process(self):
        with tempfile.TemporaryDirectory() as folder:
            cipher = Fernet(Fernet.generate_key())
            identity = str(uuid4())
            with (
                patch.object(
                    codex_terminal,
                    "Settings",
                    return_value=SimpleNamespace(ai_cli_work_path=Path(folder)),
                ),
                patch.object(codex_terminal, "credential_cipher", return_value=cipher),
            ):
                directory = codex_terminal.directory(identity) / "output"
                directory.mkdir(parents=True)
                path = directory / "7.rpc.enc.jsonl"
                events = [
                    {"method": "turn/started", "status": "running"},
                    {
                        "method": "turn/completed",
                        "status": "failed",
                        "error": {"message": "stream closed before response.completed"},
                    },
                ]
                path.write_bytes(
                    b"".join(cipher.encrypt(json.dumps(e).encode()) + b"\n" for e in events)
                )
                state = codex_terminal.turn_state(identity, 7)
                self.assertEqual(state["turn_status"], "failed")
                self.assertIn("stream closed", state["turn_error"])
                with path.open("ab") as output:
                    output.write(
                        cipher.encrypt(
                            json.dumps({"method": "turn/started", "status": "running"}).encode()
                        )
                        + b"\n"
                    )
                    output.write(b"unfinished encrypted line")
                self.assertEqual(
                    codex_terminal.turn_state(identity, 7),
                    {"turn_status": "running", "turn_error": ""},
                )

    @unittest.skipUnless(os.name == "nt", "Windows ConPTY import")
    def test_gateway_failure_never_falls_back_to_an_unfiltered_cli(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                codex_terminal,
                "Settings",
                return_value=SimpleNamespace(
                    ai_cli_work_path=Path(folder), ai_cli_executable=Path(sys.executable)
                ),
            ),
            patch.object(codex_terminal.codex_exec, "require_available"),
            patch.object(
                codex_terminal,
                "TerminalGateway",
                side_effect=OSError("synthetic gateway unavailable"),
            ),
            patch("winpty.PtyProcess.spawn") as spawn,
            patch.object(
                codex_terminal, "credential_cipher", return_value=Fernet(Fernet.generate_key())
            ),
        ):
            with self.assertRaises(OSError):
                codex_terminal.run(
                    "https://example.com",
                    "test",
                    "FAKE-KEY",
                    "low",
                    identity=str(uuid4()),
                    execution=1,
                    instructions="Synthetic",
                    fixed_input={},
                )
            spawn.assert_not_called()

    def test_trial_user_allowlist_does_not_grant_shell_permission(self):
        with patch.object(
            native_terminal, "Settings", return_value=SimpleNamespace(ai_cli_terminal_user_ids=None)
        ):
            native_terminal.require_enabled(8)
        with patch.object(
            native_terminal, "Settings", return_value=SimpleNamespace(ai_cli_terminal_user_ids=[])
        ):
            with self.assertRaises(AppError):
                native_terminal.require_enabled(8)
        with patch.object(
            native_terminal, "Settings", return_value=SimpleNamespace(ai_cli_terminal_user_ids=[8])
        ):
            native_terminal.require_enabled(8)
            with self.assertRaises(AppError):
                native_terminal.require_enabled(9)

    def test_raw_vt_output_and_keys_roundtrip_encrypted_without_relabeling(self):
        with tempfile.TemporaryDirectory() as folder:
            identity = str(uuid4())
            root = Path(folder)
            cipher = Fernet(Fernet.generate_key())
            with (
                patch.object(
                    codex_terminal, "Settings", return_value=SimpleNamespace(ai_cli_work_path=root)
                ),
                patch.object(codex_terminal, "credential_cipher", return_value=cipher),
            ):
                raw = "\x1b[?1049h\x1b[31mOriginal CLI\r\n> 中文\x1b[0m"
                location = codex_terminal.directory(identity) / "output"
                location.mkdir(parents=True)
                (location / "7.enc.jsonl").write_bytes(cipher.encrypt(raw.encode()) + b"\n")
                self.assertEqual(codex_terminal.output(identity, 7)["chunks"], [raw])
                self.assertEqual(codex_terminal.output(identity, 7, 1)["chunks"], [])
                keys = "\x1b[A\x03输入\r"
                codex_terminal.put_command(identity, 7, {"type": "input", "data": keys})
                command = next((codex_terminal.directory(identity) / "control" / "7").glob("*.enc"))
                self.assertEqual(json.loads(cipher.decrypt(command.read_bytes()))["data"], keys)
                with self.assertRaises(AppError):
                    codex_terminal.directory("../../other")

    def test_split_key_mask_does_not_modify_normal_ansi(self):
        mask = codex_terminal.SecretFilter("FAKE-SECRET")
        self.assertEqual(mask.feed("\x1b[31mFAKE-"), "\x1b[31m")
        self.assertEqual(mask.feed("SECRET\x1b[0m"), "[REDACTED_API_KEY]\x1b[0m")

    def test_terminal_control_rejects_arbitrary_commands_paths_and_bad_dimensions(self):
        for body in (
            {"type": "shell", "data": "anything"},
            {"type": "resize", "rows": 0, "cols": 80},
            {"type": "input", "data": "abc", "path": "other"},
            {"type": "input"},
            {"type": "resize", "rows": 24, "cols": 80, "data": "abc"},
        ):
            with self.assertRaises(ValidationError):
                TerminalInput.model_validate(body)
        self.assertEqual(TerminalInput(type="input", data="\x03").data, "\x03")

    def test_permissions_are_checked_before_read_or_write(self):
        with (
            patch.object(
                native_terminal,
                "Settings",
                return_value=SimpleNamespace(ai_cli_terminal_user_ids=[]),
            ),
            patch.object(
                native_terminal, "authorized", side_effect=AppError(403, "generation_owner_only")
            ),
            patch.object(codex_terminal, "output") as read,
            patch.object(codex_terminal, "put_command") as write,
        ):
            with self.assertRaises(AppError):
                native_terminal.read(1, 2, 3, 0, object(), MagicMock())
            with self.assertRaises(AppError):
                native_terminal.write(
                    1,
                    2,
                    3,
                    TerminalInput(type="input", data="x"),
                    SimpleNamespace(id=8),
                    MagicMock(),
                )
            read.assert_not_called()
            write.assert_not_called()


@unittest.skipUnless(os.name == "nt", "Windows native ConPTY")
class RealNativeTerminalTests(unittest.TestCase):
    def test_real_tui_normal_reply_then_user_shell_is_denied_before_execution(self):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")
        with (
            tempfile.TemporaryDirectory() as folder,
            FakeProvider(text="SAFE_NATIVE_REPLY") as provider,
        ):
            identity = str(uuid4())
            local = SimpleNamespace(
                ai_cli_work_path=Path(folder), ai_cli_executable=settings.ai_cli_executable
            )
            chunks, denied, forwarded, denial_details = [], [], [], []
            cursor, stage, deadline = 0, 0, monotonic() + 20
            original = TerminalPolicy.request

            def audit(policy, message):
                try:
                    result = original(policy, message)
                    forwarded.append(message.get("method"))
                    return result
                except PolicyDenied as exc:
                    denied.append(message.get("method"))
                    denial_details.append((message.get("method"), str(exc)))
                    raise

            with (
                patch.object(codex_terminal, "Settings", return_value=local),
                patch.object(TerminalPolicy, "request", audit),
            ):
                started = monotonic()

                def progress():
                    nonlocal cursor, stage
                    page = codex_terminal.output(identity, 1, cursor)
                    cursor = page["next_cursor"]
                    chunks.extend(page["chunks"])
                    for raw in page["chunks"]:
                        if "\x1b[6n" in raw:
                            codex_terminal.put_command(
                                identity, 1, {"type": "input", "data": "\x1b[1;1R"}
                            )
                        if "\x1b[c" in raw:
                            codex_terminal.put_command(
                                identity, 1, {"type": "input", "data": "\x1b[?1;2c"}
                            )
                    elapsed = monotonic() - started
                    if stage == 0 and elapsed > 3:
                        codex_terminal.put_command(
                            identity, 1, {"type": "input", "data": "Explain punctuation ! safely."}
                        )
                        stage = 1
                    elif stage == 1 and elapsed > 4:
                        codex_terminal.put_command(identity, 1, {"type": "input", "data": "\r"})
                        stage = 2
                    elif stage == 2 and "SAFE_NATIVE_REPLY" in "".join(chunks) and elapsed > 6:
                        codex_terminal.put_command(
                            identity,
                            1,
                            {"type": "input", "data": "!echo blocked > must-not-exist.txt"},
                        )
                        stage = 3
                    elif stage == 3 and elapsed > 7:
                        codex_terminal.put_command(identity, 1, {"type": "input", "data": "\r"})
                        stage = 4
                    if monotonic() > deadline:
                        raise AppError(409, "synthetic_terminal_stop")

                with self.assertRaises(AppError):
                    codex_terminal.run(
                        provider.url,
                        "gpt-6.1-sol",
                        "FAKE-NATIVE-KEY",
                        "low",
                        identity=identity,
                        execution=1,
                        instructions="Reply to the user.",
                        fixed_input={"messages": []},
                        on_progress=progress,
                    )
                chunks.extend(codex_terminal.output(identity, 1, cursor)["chunks"])
                self.assertIn("SAFE_NATIVE_REPLY", "".join(chunks))
                self.assertIn("turn/start", forwarded)
                self.assertIn("thread/shellCommand", denied)
                self.assertNotIn("thread/shellCommand", forwarded)
                self.assertFalse(
                    (codex_terminal.directory(identity) / "input" / "must-not-exist.txt").exists()
                )
                self.assertNotIn("FAKE-NATIVE-KEY", "".join(chunks))
                # Reopen the same native history after a denied action; do not replay a model turn.
                resume_cursor, resume_chunks = 0, []
                resume_deadline = monotonic() + 12

                def resume_progress():
                    nonlocal resume_cursor
                    page = codex_terminal.output(identity, 2, resume_cursor)
                    resume_cursor = page["next_cursor"]
                    resume_chunks.extend(page["chunks"])
                    for raw in page["chunks"]:
                        if "\x1b[6n" in raw:
                            codex_terminal.put_command(
                                identity, 2, {"type": "input", "data": "\x1b[1;1R"}
                            )
                        if "\x1b[c" in raw:
                            codex_terminal.put_command(
                                identity, 2, {"type": "input", "data": "\x1b[?1;2c"}
                            )
                    if (
                        "SAFE_NATIVE_REPLY" in "".join(resume_chunks)
                        or monotonic() > resume_deadline
                    ):
                        raise AppError(409, "synthetic_terminal_stop")

                requests_before = len(provider.requests)
                with self.assertRaises(AppError):
                    codex_terminal.run(
                        provider.url,
                        "gpt-6.1-sol",
                        "FAKE-NATIVE-KEY",
                        "low",
                        identity=identity,
                        execution=2,
                        instructions="Reply to the user.",
                        fixed_input={"messages": []},
                        resume=True,
                        on_progress=resume_progress,
                    )
                resume_chunks.extend(codex_terminal.output(identity, 2, resume_cursor)["chunks"])
                self.assertIn(
                    "thread/resume",
                    forwarded,
                    str(denial_details) + repr("".join(resume_chunks)[-1800:]),
                )
                self.assertIn("SAFE_NATIVE_REPLY", "".join(resume_chunks))
                self.assertEqual(len(provider.requests), requests_before)

    def test_real_tui_starts_without_any_model_request_and_accepts_native_status_command(self):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")
        with (
            tempfile.TemporaryDirectory() as folder,
            FakeProvider(text="SYNTHETIC") as provider,
        ):
            identity = str(uuid4())
            local = SimpleNamespace(
                ai_cli_work_path=Path(folder), ai_cli_executable=settings.ai_cli_executable
            )
            chunks = []
            cursor = 0
            sent = False
            started = monotonic()
            with patch.object(codex_terminal, "Settings", return_value=local):

                def progress():
                    nonlocal cursor, sent
                    frame = codex_terminal.output(identity, 1, cursor)
                    cursor = frame["next_cursor"]
                    chunks.extend(frame["chunks"])
                    for raw in frame["chunks"]:
                        if "\x1b[6n" in raw:
                            codex_terminal.put_command(
                                identity, 1, {"type": "input", "data": "\x1b[1;1R"}
                            )
                        if "\x1b[c" in raw:
                            codex_terminal.put_command(
                                identity, 1, {"type": "input", "data": "\x1b[?1;2c"}
                            )
                    text = "".join(chunks)
                    if not sent and "OpenAI Codex" in text:
                        codex_terminal.put_command(
                            identity, 1, {"type": "input", "data": "/status\r"}
                        )
                        sent = True
                    if sent and ("Session" in text or "Token" in text):
                        raise AppError(409, "synthetic_terminal_stop")
                    if monotonic() - started > 18:
                        raise AppError(409, "synthetic_terminal_stop")

                with self.assertRaises(AppError):
                    codex_terminal.run(
                        provider.url,
                        "gpt-6.1-sol",
                        "FAKE-NATIVE-KEY",
                        "low",
                        identity=identity,
                        execution=1,
                        instructions="Synthetic Skill",
                        fixed_input={"messages": []},
                        on_progress=progress,
                    )
                chunks.extend(codex_terminal.output(identity, 1, cursor)["chunks"])
                text = "".join(chunks)
                self.assertIn("OpenAI Codex", text)
                self.assertNotIn("Trust and continue", text)
                self.assertTrue(sent)
                self.assertIn("/status", text)
                self.assertEqual(provider.requests, [])
                self.assertTrue((codex_terminal.directory(identity) / "state").is_dir())
                self.assertTrue(
                    (codex_terminal.directory(identity) / "input" / "input.json").is_file()
                )
                self.assertNotIn("FAKE-NATIVE-KEY", text)
