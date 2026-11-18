"""CLI history/streaming checks use synthetic events and never call a model."""

import json
import tempfile
import unittest
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.errors import AppError
from app.db.models import CaseGenerationBatch, CaseGenerationChatTurn
from app.integrations import codex_events
from app.integrations.codex_exec import CLIProgress
from app.modules.case_generation import chat, cli
from app.modules.case_generation.schemas import Chat


class CLIJournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.attempt = str(uuid4())
        self.directory = self.root / self.attempt
        self.directory.mkdir()
        self.cipher = Fernet(Fernet.generate_key())
        self.journal = codex_events.EventJournal(self.directory, self.cipher, ('private-"key',))
        self.settings = patch.object(
            codex_events, "Settings", return_value=SimpleNamespace(ai_cli_work_path=self.root)
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.crypto = patch.object(codex_events, "credential_cipher", return_value=self.cipher)
        self.crypto.start()
        self.addCleanup(self.crypto.stop)

    def test_error_is_readable_before_exit_masked_and_resume_cursor_handles_partial_line(self):
        progress = CLIProgress({}, monotonic(), self.journal.append)
        progress.feed(
            json.dumps({"type": "error", "message": 'retry private-"key'}).encode() + b"\n"
        )
        first = codex_events.read_events(self.attempt)
        self.assertEqual(first["items"][0]["text"], "retry [REDACTED_API_KEY]")
        self.assertEqual(first["next_cursor"], 1)
        self.assertFalse((self.directory / "events.enc").exists())
        self.assertNotIn(b"retry", self.journal.path.read_bytes())
        with self.journal.path.open("ab") as output:
            output.write(b"partial")
        self.assertEqual(codex_events.read_events(self.attempt, 1)["next_cursor"], 1)

    def test_projection_omits_tool_payload_and_reasoning_but_preserves_tool_failure(self):
        event = {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "read_input",
                "status": "failed",
                "arguments": {"offset_bytes": 0, "query": "private-query"},
                "result": {"content": [{"text": "private-source"}]},
                "error": {"message": "Invalid fixed task input request"},
            },
        }
        self.journal.append(event, 1)
        self.journal.append(
            {"type": "item.completed", "item": {"type": "reasoning", "text": "private-reasoning"}},
            2,
        )
        result = json.dumps(codex_events.read_events(self.attempt))
        for private in ("private-query", "private-source", "private-reasoning"):
            self.assertNotIn(private, result)
        self.assertIn("Invalid fixed task input request", result)
        self.assertEqual(codex_events.read_events(self.attempt, limit=1)["has_more"], True)
        self.assertEqual(
            codex_events.read_events(self.attempt, cursor=1)["items"][0]["sequence"], 2
        )

    def test_legacy_archive_replays_errors_without_inventing_timestamps_or_calling_ai(self):
        events = [
            {"type": "error", "message": "Reconnecting... 1/5"},
            {"type": "turn.failed", "error": {"message": "stream disconnected"}},
        ]
        raw = b"\n".join(json.dumps(e).encode() for e in events) + b"\n---stderr---\nprivate stderr"
        (self.directory / "events.enc").write_bytes(self.cipher.encrypt(raw))
        result = codex_events.read_events(self.attempt)
        self.assertEqual(len(result["items"]), 2)
        self.assertIsNone(result["items"][0]["at"])
        self.assertIn("stream disconnected", result["items"][1]["text"])
        with self.assertRaises(AppError):
            codex_events.read_events("../../another-owner")

    def test_failed_append_does_not_skip_the_next_readable_sequence(self):
        with patch.object(Path, "open", side_effect=OSError("synthetic disk error")):
            with self.assertRaises(OSError):
                self.journal.append({"type": "error", "message": "first"}, 1)
        self.journal.append({"type": "error", "message": "second"}, 2)
        self.assertEqual(codex_events.read_events(self.attempt)["items"][0]["sequence"], 1)


class CLIWorkspacePermissionsTests(unittest.TestCase):
    def test_task_identity_owner_and_attempt_are_validated_before_reading_any_file(self):
        actor = SimpleNamespace(id=8)
        row = SimpleNamespace(
            run_id=4,
            actor_id=8,
            status="FAILED",
            attempts=[{"status": "FAILED", "diagnostics": {"cli_attempt_id": str(uuid4())}}],
        )
        db = MagicMock()
        db.get.return_value = row
        with (
            patch.object(cli.service, "own"),
            patch.object(cli.codex_events, "read_events") as read,
        ):
            for change in ({"run_id": 99}, {"actor_id": 99}):
                old = {k: getattr(row, k) for k in change}
                for k, v in change.items():
                    setattr(row, k, v)
                with self.assertRaises(AppError):
                    cli.events(7, 4, "batch", 3, actor, db)
                for k, v in old.items():
                    setattr(row, k, v)
            with self.assertRaises(AppError):
                cli.events(7, 4, "batch", 3, actor, db, attempt=10)
            read.assert_not_called()
            read.return_value = {"items": [], "available": True}
            result = cli.events(7, 4, "batch", 3, actor, db)
            self.assertEqual(result["status"], "FAILED")
            read.assert_called_once_with(row.attempts[0]["diagnostics"]["cli_attempt_id"], 0)
            db.get.assert_called_with(CaseGenerationBatch, 3)

    def test_failed_generation_can_chat_only_with_explicit_cli_and_preserves_history(self):
        actor = SimpleNamespace(id=8)
        run = SimpleNamespace(
            id=4, actor_id=8, metadata_snapshot={"skill": {"version": "fixed"}}, handling={}
        )
        old = SimpleNamespace(question="旧问题", answer="旧回答", context={})
        db = MagicMock()
        db.scalar.return_value = None
        db.scalars.return_value = [old]
        config = {"call_mode": "CODEX_EXEC"}
        with (
            patch.object(chat.service, "own", return_value=run),
            patch.object(chat.service, "reports", return_value=[]),
            patch.object(chat.service, "function_views", return_value=({}, {})),
            patch.object(chat.service, "suggestion_map", return_value={}),
            patch.object(chat.service, "question_map", return_value={}),
            patch.object(
                chat.service,
                "batches",
                return_value=[SimpleNamespace(input_snapshot={"full": "input"})],
            ),
            patch.object(chat.sources, "recheck"),
            patch.object(chat, "analysis_configuration", return_value=(config, "fake")),
            patch.object(chat, "configuration_snapshot", return_value=config),
            patch.object(chat, "view", side_effect=lambda row, actor: row),
        ):
            payload = Chat(request_id=uuid4(), question="新问题", cli_only=True)
            turn = chat.enqueue(7, 4, payload, actor, db)
            self.assertIsInstance(turn, CaseGenerationChatTurn)
            self.assertEqual(
                turn.context["messages"],
                [{"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"}],
            )
            self.assertEqual(turn.context["inputs"], [{"full": "input"}])
            self.assertEqual(turn.context["skill_reference"], {"version": "fixed"})
            db.add.assert_called_once_with(turn)
            config["call_mode"] = "RESPONSES_API"
            with self.assertRaises(AppError):
                chat.enqueue(7, 4, payload, actor, db)
            payload.cli_only = False
            with self.assertRaises(AppError):
                chat.enqueue(7, 4, payload, actor, db)
