import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from cryptography.fernet import Fernet

from app.core.errors import AppError
from app.integrations import response_errors, responses
from app.integrations.response_diagnostics import safe_snapshot


class UpstreamErrorTests(unittest.TestCase):
    def test_no_available_account_is_specific_safe_failure_without_retry(self):
        body = b'{"error":{"message":"no available account"}}'
        for status in (400, 422, 503):
            opener = MagicMock()
            opener.open.side_effect = HTTPError(
                "https://example.invalid/responses", status, "", {}, io.BytesIO(body)
            )
            stats = {}
            with (
                self.subTest(status=status),
                patch("app.integrations.responses.build_opener", return_value=opener),
                patch("app.integrations.response_errors.capture"),
                self.assertLogs("app.integrations.responses", level="WARNING"),
                self.assertRaises(AppError) as caught,
            ):
                responses.analyze(
                    "https://example.invalid",
                    "model",
                    "key",
                    "high",
                    "fixed",
                    [],
                    diagnostics=stats,
                )
            self.assertEqual(caught.exception.detail, "ai_upstream_account_unavailable")
            self.assertEqual(safe_snapshot(stats)["error_category"], "account_unavailable")
            opener.open.assert_called_once()
        stream = io.BytesIO(
            b'data: {"type":"error","error":{"message":"no available account"}}\n\n'
        )
        stream.headers = {"Content-Type": "text/event-stream"}
        opener = MagicMock()
        opener.open.return_value = stream
        with (
            patch("app.integrations.responses.build_opener", return_value=opener),
            patch("app.integrations.response_errors.capture"),
            self.assertLogs("app.integrations.responses", level="WARNING"),
            self.assertRaises(AppError) as caught,
        ):
            responses.analyze("https://example.invalid", "model", "key", "high", "fixed", [])
        self.assertEqual(caught.exception.detail, "ai_upstream_account_unavailable")
        opener.open.assert_called_once()

    def test_long_json_text_and_encoded_error_envelopes_keep_specific_rejection(self):
        cases = (
            (
                json.dumps(
                    {
                        "error": {
                            "code": "context_length_exceeded",
                            "param": "input",
                            "message": "x" * 70000,
                        }
                    }
                ).encode(),
                "ai_context_limit",
            ),
            (b"Input too long", "ai_context_limit"),
            (b"<html><body>Request body too large</body></html>", "ai_input_too_large"),
            (json.dumps("prompt too long").encode(), "ai_context_limit"),
            (json.dumps([{"code": "string_too_long"}]).encode(), "ai_input_too_large"),
            (
                json.dumps(
                    {
                        "error": json.dumps(
                            {
                                "type": "invalid_request_error",
                                "param": "reasoning.effort",
                                "message": "Expected value high",
                            }
                        )
                    }
                ).encode(),
                "ai_parameters_rejected",
            ),
            (
                json.dumps(
                    {"error": {"param": "input[0].content[0].text", "message": "Expected string"}}
                ).encode(),
                "ai_parameters_rejected",
            ),
        )
        for body, expected in cases:
            with self.subTest(expected=expected):
                stats = {}
                stream = io.BytesIO(body)
                opener = MagicMock()
                opener.open.side_effect = HTTPError(
                    "https://example.invalid/responses", 400, "", {}, stream
                )
                with (
                    patch("app.integrations.responses.build_opener", return_value=opener),
                    patch.object(response_errors, "capture") as capture,
                    self.assertLogs("app.integrations.responses", level="WARNING"),
                    self.assertRaises(AppError) as caught,
                ):
                    responses.analyze(
                        "https://example.invalid",
                        "test",
                        "synthetic-key",
                        "high",
                        "fixed",
                        [],
                        diagnostics=stats,
                    )
                self.assertEqual(caught.exception.detail, expected)
                opener.open.assert_called_once()
                capture.assert_called_once()
                self.assertEqual(capture.call_args.args[0], body)
                self.assertEqual(len(safe_snapshot(stats)["error_fingerprint"]), 64)
                self.assertFalse(stats["error_body_truncated"])
                self.assertTrue(stream.closed)

    def test_unknown_error_is_encrypted_redacted_and_correlated_without_public_prose(self):
        with tempfile.TemporaryDirectory() as folder:
            cipher = Fernet(Fernet.generate_key())
            body = json.dumps(
                {
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Precise provider reason synthetic-key private company text",
                    }
                }
            ).encode()
            opener = MagicMock()
            opener.open.side_effect = HTTPError(
                "https://example.invalid/responses", 400, "", {}, io.BytesIO(body)
            )
            stats = {}
            with (
                patch.object(response_errors, "directory", return_value=Path(folder)),
                patch.object(response_errors, "credential_cipher", return_value=cipher),
                patch("app.integrations.responses.build_opener", return_value=opener),
                self.assertLogs("app.integrations.responses", level="WARNING") as logs,
                self.assertRaises(AppError) as caught,
            ):
                responses.analyze(
                    "https://example.invalid",
                    "test",
                    "synthetic-key",
                    "high",
                    "fixed",
                    [],
                    diagnostics=stats,
                )
            self.assertEqual(caught.exception.detail, "ai_request_rejected")
            ref = safe_snapshot(stats)["error_ref"]
            saved = (Path(folder) / f"{ref}.enc").read_bytes()
            self.assertNotIn(b"Precise provider reason", saved)
            self.assertNotIn(b"synthetic-key", saved)
            with (
                patch.object(response_errors, "directory", return_value=Path(folder)),
                patch.object(response_errors, "credential_cipher", return_value=cipher),
            ):
                record = response_errors.read(ref)
            restored = base64.b64decode(record["body_base64"])
            self.assertIn(b"Precise provider reason", restored)
            self.assertIn(b"[REDACTED_API_KEY]", restored)
            self.assertNotIn(b"synthetic-key", restored)
            public = json.dumps(safe_snapshot(stats)) + "\n".join(logs.output)
            self.assertNotIn("Precise provider reason", public)
            self.assertNotIn("private company text", public)
            self.assertIn(ref, public)
            opener.open.assert_called_once()

    def test_error_capture_failure_never_masks_upstream_failure_and_limits_are_explicit(self):
        stats = {}
        with patch.object(
            response_errors,
            "credential_cipher",
            side_effect=AppError(503, "ai_key_storage_unavailable"),
        ):
            response_errors.capture(b"synthetic", stats, "key")
        self.assertTrue(safe_snapshot(stats)["error_capture_failed"])
        with self.assertRaises(ValueError):
            response_errors.read("../../escape")

    def test_stream_error_is_retained_once_with_its_original_failure(self):
        event = {
            "type": "response.failed",
            "response": {"error": {"message": "precise stream reason"}},
        }
        stream = io.BytesIO(("data: " + json.dumps(event) + "\n\n").encode())
        stream.headers = {"Content-Type": "text/event-stream"}
        opener = MagicMock()
        opener.open.return_value = stream
        with (
            patch("app.integrations.responses.build_opener", return_value=opener),
            patch.object(response_errors, "capture") as capture,
            self.assertLogs("app.integrations.responses", level="WARNING"),
            self.assertRaises(AppError) as caught,
        ):
            responses.analyze(
                "https://example.invalid", "test", "synthetic-key", "high", "fixed", []
            )
        self.assertEqual(caught.exception.detail, "ai_stream_failed")
        capture.assert_called_once()
        self.assertEqual(json.loads(capture.call_args.args[0]), event)
        self.assertTrue(stream.closed)
        opener.open.assert_called_once()

    def test_capture_limit_and_write_failure_are_explicit_without_plaintext_files(self):
        with tempfile.TemporaryDirectory() as folder:
            cipher = Fernet(Fernet.generate_key())
            stats = {}
            with (
                patch.object(response_errors, "directory", return_value=Path(folder)),
                patch.object(response_errors, "credential_cipher", return_value=cipher),
                patch.object(response_errors, "MAX_ERROR_BYTES", 8),
            ):
                response_errors.capture(b"1234567890", stats, "")
            self.assertTrue(stats["error_body_truncated"])
            record = json.loads(
                cipher.decrypt((Path(folder) / f"{stats['error_ref']}.enc").read_bytes())
            )
            self.assertEqual(base64.b64decode(record["body_base64"]), b"12345678")
            before = set(Path(folder).iterdir())
            failed = {}
            with (
                patch.object(response_errors, "directory", return_value=Path(folder)),
                patch.object(response_errors, "credential_cipher", return_value=cipher),
                patch.object(response_errors.os, "replace", side_effect=OSError),
            ):
                response_errors.capture(b"precise original error", failed, "")
            self.assertTrue(failed["error_capture_failed"])
            self.assertEqual(set(Path(folder).iterdir()), before)
