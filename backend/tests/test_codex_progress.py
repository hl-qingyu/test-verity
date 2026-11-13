"""JSONL progress remains factual, private and independent of final report validity."""

import json
import unittest
from time import monotonic

from app.core.errors import AppError
from app.integrations.codex_exec import CLIProgress
from app.integrations.response_diagnostics import safe_snapshot
from app.modules.requirements.risk_service import json_object


class CLIProgressTests(unittest.TestCase):
    def test_small_partial_utf8_events_update_stages_without_exposing_text(self):
        stats = {}
        progress = CLIProgress(stats, monotonic())
        event = {"type": "thread.started", "thread_id": "12345678-1234-1234-1234-123456789abc"}
        progress.feed(json.dumps(event).encode() + b"\n")
        self.assertEqual(stats["phase"], "cli_waiting")
        private = "合成私有正文不能成为公开诊断"
        message = {
            "type": "item.completed",
            "item": {"id": "i1", "type": "agent_message", "text": private},
        }
        raw = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        for byte in raw:
            progress.feed(bytes([byte]))
        self.assertEqual(stats["output_characters"], len(private))
        self.assertNotIn(private, json.dumps(safe_snapshot(stats), ensure_ascii=False))
        self.assertEqual(safe_snapshot(stats)["cli_thread_id"], event["thread_id"])
        self.assertEqual(safe_snapshot(stats)["cli_event_count"], 2)

    def test_updates_are_not_counted_as_new_output_and_completion_is_not_report_success(self):
        stats = {}
        progress = CLIProgress(stats, monotonic())
        for event in (
            {"type": "item.started", "item": {"type": "reasoning"}},
            {"type": "item.updated", "item": {"type": "mcp_tool_call"}},
        ):
            progress.feed(json.dumps(event).encode() + b"\n")
        self.assertEqual(stats["phase"], "cli_reading")
        for kind, text in (("item.updated", "O"), ("item.completed", "OK")):
            progress.feed(
                json.dumps(
                    {"type": kind, "item": {"id": "same", "type": "agent_message", "text": text}}
                ).encode()
                + b"\n"
            )
        self.assertEqual(stats["output_characters"], 2)
        progress.feed(b'{"type":"turn.completed"}\n')
        self.assertEqual(stats["phase"], "validating_response")
        self.assertNotIn("outcome", stats)

    def test_conflicting_duplicate_priority_remains_rejected(self):
        with self.assertRaises(AppError) as caught:
            json_object('{"cases":[{"design":{"priority":"P2","priority":"P1"}}]}')
        self.assertEqual(caught.exception.detail, "risk_json_invalid")
