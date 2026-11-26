import copy
import json
import unittest
from unittest.mock import patch

from app.integrations.response_input import TEXT_PART_CHARACTERS, pack_text, prepare_messages
from app.integrations.responses import analyze, converse


def restore(packed):
    envelope = json.loads(packed)
    if envelope.get("$verity_transport") != "text_references_v1":
        return envelope

    def expand(value):
        if isinstance(value, dict):
            if set(value) == {"$verity_text_ref"}:
                return envelope["texts"][value["$verity_text_ref"]]
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return expand(envelope["data"])


class ResponseInputTests(unittest.TestCase):
    def test_large_text_parts_rejoin_exactly_in_place_including_unicode_and_attachment_order(self):
        source = ('你好😀\\"\n' * (TEXT_PART_CHARACTERS // 6 + 1))[: TEXT_PART_CHARACTERS + 1]
        image = {"type": "input_image", "image_url": "data:image/png;base64,synthetic"}
        content = [
            {"type": "input_text", "text": source},
            image,
            {"type": "input_text", "text": "after image"},
        ]
        messages = [{"role": "user", "content": content}]
        original = copy.deepcopy(messages)
        result, note, stats = prepare_messages(messages)
        parts = result[0]["content"]
        self.assertEqual("".join(p["text"] for p in parts[:2]), source)
        self.assertEqual(parts[2:], content[1:])
        self.assertEqual(messages, original)
        self.assertEqual(stats["split_text_count"], 1)
        self.assertEqual(stats["max_input_text_characters"], TEXT_PART_CHARACTERS)
        self.assertIn("无分隔拼接", note)
        self.assertEqual(json.loads(json.dumps(result, ensure_ascii=False)), result)
        for size in (0, TEXT_PART_CHARACTERS, TEXT_PART_CHARACTERS + 1):
            raw = source[:size]
            result, note, stats = prepare_messages([{"role": "user", "content": raw}])
            actual = result[0]["content"]
            self.assertEqual(
                actual if isinstance(actual, str) else "".join(p["text"] for p in actual), raw
            )
            self.assertEqual(bool(note), size > TEXT_PART_CHARACTERS)

    def test_packed_large_json_restores_all_source_versions_after_joining_same_request_parts(self):
        text = "代码😀\\n" * 300000
        data = {
            "before": {"text": text, "version": "old"},
            "after": {"text": text, "version": "new"},
        }
        raw = json.dumps(data, ensure_ascii=False)
        with patch("app.integrations.responses.send_response", return_value="ok") as send:
            for call in (
                lambda: analyze(
                    "https://example.invalid",
                    "m",
                    "fake",
                    "high",
                    "fixed",
                    [{"type": "input_text", "text": raw}],
                ),
                lambda: converse(
                    "https://example.invalid",
                    "m",
                    "fake",
                    "high",
                    "fixed",
                    [{"role": "user", "content": raw}],
                ),
            ):
                send.reset_mock()
                self.assertEqual(call(), "ok")
                payload = send.call_args.args[2]
                parts = payload["input"][0]["content"]
                self.assertGreater(len(parts), 1)
                self.assertLessEqual(max(len(p["text"]) for p in parts), TEXT_PART_CHARACTERS)
                self.assertEqual(restore("".join(p["text"] for p in parts)), data)
                self.assertTrue(payload["instructions"].startswith("fixed\n\n"))
                self.assertIsNone(send.call_args.args[3])
                send.assert_called_once()

    def test_five_contracts_roundtrip_exact_text_identity_and_versions(self):
        text = '源代码原文\n  return "你好\\n";\n' * 1000
        for kind in (
            "REQUIREMENT_ANALYSIS",
            "CASE_GENERATION",
            "CASE_ANALYSIS",
            "CODE_REVIEW",
            "CHANGE_IMPACT",
        ):
            data = {
                "analysis_type": kind,
                "request_id": "fixed-request",
                "before": {"snapshot_ref": "old", "path": "a.py", "start_line": 7, "text": text},
                "after": {"snapshot_ref": "new", "path": "b.py", "start_line": 3, "text": text},
                "changed": {"text": text + "# changed"},
                "number": 123,
                "empty": None,
            }
            original = copy.deepcopy(data)
            raw = json.dumps(data, ensure_ascii=False)
            packed, count, saved = pack_text(raw)
            self.assertEqual(restore(packed), data)
            self.assertEqual(data, original)
            self.assertEqual(count, 1)
            self.assertGreater(saved, 0)
            self.assertEqual(json.loads(packed)["data"]["before"]["snapshot_ref"], "old")
            self.assertEqual(json.loads(packed)["data"]["after"]["start_line"], 3)
            self.assertEqual(saved, len(raw.encode()) - len(packed.encode()))

    def test_nonduplicated_small_invalid_and_instruction_content_stay_unchanged(self):
        for raw in (
            '{"text":"small"}',
            '{"text":"' + "x" * 10000 + '"}',
            "not-json",
            '{"text":1,"text":2}',
            '{"x":NaN}',
        ):
            self.assertEqual(pack_text(raw), (raw, 0, 0))
        source = json.dumps({"a": {"text": "x" * 10000}, "b": {"text": "x" * 10000}})
        rules = {"role": "developer", "content": [{"type": "input_text", "text": source}]}
        image = {"type": "input_image", "image_url": "data:image/png;base64,synthetic"}
        messages = [
            rules,
            {"role": "user", "content": [{"type": "input_text", "text": source}, image]},
        ]
        original = copy.deepcopy(messages)
        result, note, stats = prepare_messages(messages)
        self.assertEqual(messages, original)
        self.assertEqual(result[0], rules)
        self.assertEqual(result[1]["content"][1], image)
        self.assertEqual(restore(result[1]["content"][0]["text"]), json.loads(source))
        self.assertTrue(note)
        self.assertEqual(stats["reused_text_count"], 1)
        conflicted = json.dumps(
            {
                "a": {"text": "x" * 10000},
                "b": {"text": "x" * 10000},
                "text": {"$verity_text_ref": "T1"},
            }
        )
        self.assertEqual(pack_text(conflicted), (conflicted, 0, 0))

    def test_both_model_entrypoints_use_same_packaging_without_modifying_original_skill(self):
        source = json.dumps({"before": {"text": "x" * 10000}, "after": {"text": "x" * 10000}})
        with patch("app.integrations.responses.send_response", return_value="ok") as send:
            analyze(
                "https://example.invalid",
                "model",
                "secret",
                "high",
                "fixed Skill",
                [{"type": "input_text", "text": source}],
            )
            analysis_payload = send.call_args.args[2]
            self.assertIsNone(send.call_args.args[3])
            converse(
                "https://example.invalid",
                "model",
                "secret",
                "high",
                "fixed Skill",
                [{"role": "user", "content": source}],
            )
            chat_payload = send.call_args.args[2]
            self.assertIsNone(send.call_args.args[3])
        self.assertEqual(analysis_payload["instructions"], chat_payload["instructions"])
        self.assertTrue(analysis_payload["instructions"].startswith("fixed Skill\n\n"))
        self.assertEqual(
            restore(analysis_payload["input"][0]["content"][0]["text"]), json.loads(source)
        )
        self.assertEqual(restore(chat_payload["input"][0]["content"]), json.loads(source))
        self.assertEqual(analysis_payload["max_output_tokens"], 32000)
        self.assertEqual(chat_payload["max_output_tokens"], 8192)
