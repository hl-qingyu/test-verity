"""Native terminal websocket transports raw ANSI and keyboard data, never a shell."""

import os
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_codex_probe import FakeProvider

from app.api import terminal_transport
from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import codex_terminal
from app.integrations.terminal_result import TerminalResult
from app.modules.case_generation.schemas import TerminalInput


class TerminalSocketTests(unittest.TestCase):
    def test_native_failure_is_sent_before_large_replay_and_updates_without_process_status_change(
        self,
    ):
        app = FastAPI()
        bound = {
            "session": {
                "id": 7,
                "status": "RUNNING",
                "error_code": "",
                "turn_status": "failed",
                "turn_error": "upstream disconnected",
            }
        }

        def read(binding, cursor):
            return {"chunks": ["old screen"], "next_cursor": cursor + 1, "has_more": True}

        @app.websocket("/terminal")
        async def socket(ws: WebSocket):
            await terminal_transport.serve(
                ws, lambda actor, db: bound, read, MagicMock(), TerminalInput
            )

        with (
            patch.object(
                terminal_transport,
                "Settings",
                return_value=SimpleNamespace(auth_allowed_origins=["http://localhost"]),
            ),
            patch.object(terminal_transport, "Session", return_value=MagicMock()),
            patch.object(terminal_transport, "get_engine"),
            patch.object(
                terminal_transport.auth_service, "authenticate", return_value=SimpleNamespace(id=8)
            ),
            TestClient(app) as client,
        ):
            client.cookies.set("verity_session", "a" * 43)
            with client.websocket_connect(
                "/terminal", headers={"origin": "http://localhost"}
            ) as ws:
                first = ws.receive_json()
                self.assertEqual(first["type"], "state")
                self.assertEqual(first["session"]["turn_status"], "failed")
                self.assertEqual(ws.receive_json()["type"], "output")
                bound["session"]["turn_status"] = "running"
                bound["session"]["turn_error"] = ""
                for _ in range(20):
                    frame = ws.receive_json()
                    if frame["type"] == "state":
                        self.assertEqual(frame["session"]["status"], "RUNNING")
                        self.assertEqual(frame["session"]["turn_status"], "running")
                        break
                else:
                    self.fail("native turn changes must be sent even while process remains RUNNING")

    @unittest.skipUnless(os.name == "nt", "Windows native CLI")
    def test_close_and_reopen_display_while_same_native_turn_finishes_in_background(self):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")
        with (
            tempfile.TemporaryDirectory() as folder,
            FakeProvider("gated", "BACKGROUND_DONE") as provider,
        ):
            identity = str(uuid4())
            spec = SimpleNamespace(
                ai_cli_work_path=Path(folder), ai_cli_executable=settings.ai_cli_executable
            )
            bound = {"session": {"id": 7, "status": "RUNNING", "error_code": ""}}
            captured, done, writes = {}, Event(), []
            deadline = monotonic() + 18

            def progress():
                if monotonic() > deadline:
                    raise AppError(409, "synthetic_deadline")

            def run():
                try:
                    captured.update(
                        codex_terminal.run(
                            provider.url,
                            "gpt-6.1-sol",
                            "FAKE-KEY",
                            "low",
                            identity=identity,
                            execution=7,
                            instructions="Synthetic only",
                            fixed_input={},
                            initial_prompt="Analyze synthetic input",
                            capture=TerminalResult(),
                            on_progress=progress,
                        )
                    )
                    bound["session"]["status"] = "COMPLETED"
                except Exception as error:
                    captured["error"] = error
                    bound["session"]["status"] = "FAILED"
                finally:
                    done.set()

            app = FastAPI()

            def read(binding, cursor):
                return codex_terminal.output(identity, 7, cursor)

            @app.websocket("/terminal")
            async def socket(ws: WebSocket):
                await terminal_transport.serve(
                    ws,
                    lambda actor, db: bound,
                    read,
                    lambda binding, value: writes.append(value),
                    TerminalInput,
                )

            def replay(ws):
                screen = ""
                while True:
                    frame = ws.receive_json()
                    if frame["type"] == "output":
                        screen += "".join(frame["chunks"])
                    if frame["type"] == "ready":
                        return screen

            with (
                patch.object(codex_terminal, "Settings", return_value=spec),
                patch.object(
                    terminal_transport,
                    "Settings",
                    return_value=SimpleNamespace(auth_allowed_origins=["http://localhost"]),
                ),
                patch.object(terminal_transport, "Session", return_value=MagicMock()),
                patch.object(terminal_transport, "get_engine"),
                patch.object(
                    terminal_transport.auth_service,
                    "authenticate",
                    return_value=SimpleNamespace(id=8),
                ),
                TestClient(app) as client,
            ):
                thread = Thread(target=run)
                thread.start()
                try:
                    while not provider.requests and not done.wait(0.05):
                        self.assertLess(monotonic(), deadline)
                    client.cookies.set("verity_session", "a" * 43)
                    with client.websocket_connect(
                        "/terminal", headers={"origin": "http://localhost"}
                    ) as ws:
                        self.assertIn("OpenAI Codex", replay(ws))
                    self.assertFalse(done.is_set(), "display close must leave native turn running")
                    with client.websocket_connect(
                        "/terminal", headers={"origin": "http://localhost"}
                    ) as ws:
                        self.assertIn("OpenAI Codex", replay(ws))
                    provider.release.set()
                    self.assertTrue(done.wait(10), "same native turn must finish without a browser")
                    self.assertEqual(captured.get("answer"), "BACKGROUND_DONE", captured)
                    with client.websocket_connect(
                        "/terminal", headers={"origin": "http://localhost"}
                    ) as ws:
                        self.assertIn("BACKGROUND_DONE", replay(ws))
                    self.assertEqual(len(provider.requests), 1)
                    self.assertEqual(writes, [], "closing/reopening must send no input or cancel")
                finally:
                    provider.release.set()
                    thread.join(20)

    def test_raw_screen_and_keyboard_without_http_per_key_or_model_calls(self):
        app = FastAPI()
        frames = ["\x1b[?1049h\x1b[31mOriginal CLI\x1b[0m"]
        writes = []
        bound = {"session": {"id": 7, "status": "RUNNING", "error_code": ""}}

        def read(binding, cursor):
            chunks = [frames.pop(0)] if frames else []
            return {"chunks": chunks, "next_cursor": cursor + len(chunks), "has_more": False}

        def write(binding, value):
            writes.append(value.data)
            frames.append(value.data)

        @app.websocket("/terminal")
        async def socket(ws: WebSocket):
            await terminal_transport.serve(ws, lambda actor, db: bound, read, write, TerminalInput)

        with (
            patch.object(
                terminal_transport,
                "Settings",
                return_value=SimpleNamespace(auth_allowed_origins=["http://localhost"]),
            ),
            patch.object(terminal_transport, "Session", return_value=MagicMock()),
            patch.object(terminal_transport, "get_engine"),
            patch.object(
                terminal_transport.auth_service, "authenticate", return_value=SimpleNamespace(id=8)
            ),
            TestClient(app) as client,
        ):
            client.cookies.set("verity_session", "a" * 43)
            with client.websocket_connect(
                "/terminal", headers={"origin": "http://localhost"}
            ) as ws:
                self.assertEqual(ws.receive_json()["session"]["id"], 7)
                self.assertEqual(
                    ws.receive_json()["chunks"], ["\x1b[?1049h\x1b[31mOriginal CLI\x1b[0m"]
                )
                self.assertEqual(ws.receive_json(), {"type": "ready"})
                ws.send_json({"type": "input", "data": "\x1b[A\x03中文"})
                self.assertEqual(ws.receive_json()["chunks"], ["\x1b[A\x03中文"])
                self.assertEqual(writes, ["\x1b[A\x03中文"])

    def test_cached_cursor_resumes_only_new_frames_and_invalid_cursor_never_authenticates(self):
        app = FastAPI()
        bound = {"session": {"id": 7, "status": "COMPLETED", "error_code": ""}}
        frames = ["old frame", "cached screen", "new tail"]
        calls = []

        def read(binding, cursor):
            calls.append((binding, cursor))
            return {"chunks": frames[cursor:], "next_cursor": len(frames), "has_more": False}

        @app.websocket("/terminal")
        async def socket(ws: WebSocket):
            await terminal_transport.serve(
                ws, lambda actor, db: bound, read, MagicMock(), TerminalInput
            )

        with (
            patch.object(
                terminal_transport,
                "Settings",
                return_value=SimpleNamespace(auth_allowed_origins=["http://localhost"]),
            ),
            patch.object(terminal_transport, "Session", return_value=MagicMock()),
            patch.object(terminal_transport, "get_engine"),
            patch.object(
                terminal_transport.auth_service, "authenticate", return_value=SimpleNamespace(id=8)
            ) as auth,
            TestClient(app) as client,
        ):
            client.cookies.set("verity_session", "a" * 43)
            with client.websocket_connect(
                "/terminal?cursor=2", headers={"origin": "http://localhost"}
            ) as ws:
                self.assertEqual(ws.receive_json()["session"]["id"], 7)
                self.assertEqual(ws.receive_json()["chunks"], ["new tail"])
                self.assertEqual(ws.receive_json(), {"type": "ready"})
            self.assertEqual(calls, [(bound, 2)])
            auth.reset_mock()
            for cursor in ("-1", "1.5", "NaN", "9007199254740992"):
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect(
                        "/terminal?cursor=" + cursor, headers={"origin": "http://localhost"}
                    ):
                        pass
            auth.assert_not_called()

    def test_cross_origin_connection_never_authenticates_or_accesses_terminal(self):
        app = FastAPI()
        access = MagicMock()

        @app.websocket("/terminal")
        async def socket(ws: WebSocket):
            await terminal_transport.serve(ws, access, MagicMock(), MagicMock(), TerminalInput)

        with (
            patch.object(
                terminal_transport,
                "Settings",
                return_value=SimpleNamespace(auth_allowed_origins=["http://localhost"]),
            ),
            patch.object(terminal_transport.auth_service, "authenticate") as auth,
            TestClient(app) as client,
        ):
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect(
                    "/terminal", headers={"origin": "https://other.example"}
                ):
                    pass
            access.assert_not_called()
            auth.assert_not_called()
