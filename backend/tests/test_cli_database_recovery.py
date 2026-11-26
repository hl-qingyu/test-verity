"""Database recovery keeps CLI execution alive and delivers one durable outcome."""

import logging
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy.exc import OperationalError
from test_codex_probe import FakeProvider

from app import chat_worker
from app.core.config import Settings
from app.core.errors import AppError
from app.integrations import ai_client, cli_results, codex_terminal
from app.integrations.call_control import CallControl, execution_scope
from app.modules.ai.recovery import propagate_database_outage


class CLIRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = patch.object(
            cli_results,
            "Settings",
            return_value=SimpleNamespace(ai_cli_work_path=Path(self.folder.name)),
        )
        self.settings.start()
        self.addCleanup(self.settings.stop)
        self.cipher = Fernet(Fernet.generate_key())
        cipher = patch.object(cli_results, "credential_cipher", return_value=self.cipher)
        cipher.start()
        self.addCleanup(cipher.stop)

    def test_progress_database_failure_leaves_cli_running_but_explicit_cancel_still_stops_it(self):
        callback = Mock(
            side_effect=[OperationalError(None, None, RuntimeError()), AppError(409, "cancelled")]
        )
        with execution_scope(Event(), transient_error=lambda e: isinstance(e, OperationalError)):
            control = CallControl(callback, keep_cli_on_outage=True)
            control.check()
            self.assertIsNone(control.error)
            with self.assertRaises(AppError):
                control.check()

    def test_completed_outcome_is_encrypted_and_replayed_without_another_model_call(self):
        identity = str(uuid4())
        called = []

        def model(text, **kwargs):
            called.append(text)
            return "完整JSON结果🌱"

        with execution_scope(Event(), receipt=identity):
            self.assertEqual(cli_results.run(model, "fixed input"), "完整JSON结果🌱")
            self.assertEqual(cli_results.run(model, "fixed input"), "完整JSON结果🌱")
        self.assertEqual(called, ["fixed input"])
        self.assertNotIn("完整JSON结果".encode(), cli_results.path(identity).read_bytes())
        self.assertTrue(cli_results.pending(identity))
        cli_results.acknowledge(identity)
        self.assertFalse(cli_results.pending(identity))

    def test_started_receipt_after_a_crash_never_repeats_the_unknown_model_request(self):
        identity = str(uuid4())

        def model():
            raise KeyboardInterrupt

        with execution_scope(Event(), receipt=identity):
            with self.assertRaises(KeyboardInterrupt):
                cli_results.run(model)
            with self.assertRaises(AppError) as error:
                cli_results.run(model)
        self.assertEqual(error.exception.detail, "ai_cli_result_incomplete")

    def test_database_delivery_retries_only_saved_result_and_releases_after_delivery(self):
        identity = str(uuid4())
        row = SimpleNamespace(ai_config={"call_mode": "CODEX_EXEC"}, status="RUNNING")
        state = {"db": True, "executions": 0, "model_calls": 0, "saved": None}

        @contextmanager
        def factory():
            yield SimpleNamespace(get=lambda *args: row)

        def model():
            state["model_calls"] += 1
            state["db"] = False
            return "FINAL_RESULT"

        def execute(key, factory):
            state["executions"] += 1
            try:
                answer = cli_results.run(model)
                if not state["db"]:
                    raise OperationalError(None, None, RuntimeError())
                state["saved"] = answer
                row.status = "COMPLETED"
            except Exception as error:
                propagate_database_outage(error)
                raise

        stop = Mock()
        stop.is_set.return_value = False
        stop.wait.side_effect = lambda seconds: state.update(db=True) or False
        with patch.object(chat_worker.reservations, "release") as release:
            chat_worker._run_task(
                SimpleNamespace(__tablename__="synthetic"),
                execute,
                1,
                identity,
                factory,
                stop,
                logging.getLogger("test"),
            )
        self.assertEqual(state["model_calls"], 1)
        self.assertEqual(state["executions"], 2)
        self.assertEqual(state["saved"], "FINAL_RESULT")
        release.assert_called_once()

    def test_worker_restart_delivers_a_pending_receipt_before_marking_old_tasks_interrupted(self):
        identity = str(uuid4())
        calls = []

        def model():
            calls.append("called")
            return "persisted-before-worker-exit"

        with execution_scope(Event(), receipt=identity):
            cli_results.run(model)
        reservation = SimpleNamespace(
            id=identity, kind="synthetic", task_id=4, request_id="req", owner_id=2
        )
        row = SimpleNamespace(
            status="RUNNING", request_id="req", actor_id=2, ai_config={"call_mode": "CODEX_EXEC"}
        )
        saved = []

        @contextmanager
        def factory():
            yield SimpleNamespace(scalars=lambda query: [reservation], get=lambda *args: row)

        def execute(key, factory):
            saved.append(cli_results.run(model))
            row.status = "COMPLETED"

        registry = [(SimpleNamespace(__tablename__="synthetic"), execute, {})]
        with (
            patch.object(chat_worker, "_registry", return_value=registry),
            patch.object(chat_worker.reservations, "release"),
        ):
            chat_worker._restore_cli_results(factory, logging.getLogger("test"))
            chat_worker._restore_cli_results(factory, logging.getLogger("test"))
        self.assertEqual(calls, ["called"])
        self.assertEqual(saved, ["persisted-before-worker-exit"])
        self.assertEqual(row.status, "COMPLETED")

    def test_api_progress_failure_remains_distinct_from_cli_outage_tolerance(self):
        callback = Mock(side_effect=OperationalError(None, None, RuntimeError()))
        with execution_scope(Event(), transient_error=lambda e: isinstance(e, OperationalError)):
            with self.assertRaises(OperationalError):
                CallControl(callback).check()

    @unittest.skipUnless(os.name == "nt", "Windows native CLI")
    def test_real_cli_finishes_while_database_is_down_and_same_outcome_is_delivered_after_recovery(
        self,
    ):
        settings = Settings()
        if not settings.ai_cli_executable:
            self.skipTest("Pinned CLI not installed")
        identity, receipt = str(uuid4()), str(uuid4())
        state = {
            "db": True,
            "checks": 0,
            "executions": 0,
            "saved": None,
            "receipt_during_outage": False,
        }
        row = SimpleNamespace(ai_config={"call_mode": "CODEX_EXEC"})

        @contextmanager
        def factory():
            yield SimpleNamespace(get=lambda *args: row)

        def check():
            state["checks"] += 1
            if not state["db"]:
                raise OperationalError(None, None, RuntimeError("synthetic db down"))

        with FakeProvider("gated", '{"complete":true}') as provider:
            local = SimpleNamespace(
                ai_cli_terminal_work_path=Path(self.folder.name) / "interactive",
                ai_cli_work_path=Path(self.folder.name),
                ai_cli_executable=settings.ai_cli_executable,
            )
            original_run = codex_terminal.run

            def during_cli(*args, **kwargs):
                state["db"] = False
                provider.release.set()
                return original_run(*args, **kwargs)

            def execute(key, factory):
                state["executions"] += 1
                answer = ai_client.analyze(
                    provider.url,
                    "gpt-6.1-sol",
                    "FAKE-KEY",
                    "low",
                    "Synthetic fixed Skill",
                    [{"type": "input_text", "text": "Synthetic fixed input"}],
                    call_mode="CODEX_EXEC",
                    terminal_spec={"identity": identity, "execution": -7},
                    on_progress=check,
                )
                if not state["db"]:
                    state["receipt_during_outage"] = cli_results.pending(receipt)
                    raise OperationalError(None, None, RuntimeError("cannot save while down"))
                state["saved"] = answer

            stop = Mock()
            stop.is_set.return_value = False
            stop.wait.side_effect = lambda seconds: state.update(db=True) or False
            with (
                patch.object(codex_terminal, "Settings", return_value=local),
                patch.object(codex_terminal, "run", side_effect=during_cli),
                patch.object(chat_worker.reservations, "release") as release,
            ):
                chat_worker._run_task(
                    SimpleNamespace(__tablename__="synthetic"),
                    execute,
                    7,
                    receipt,
                    factory,
                    stop,
                    logging.getLogger("test"),
                )
            self.assertEqual(state["saved"], '{"complete":true}')
            self.assertTrue(state["receipt_during_outage"])
            self.assertEqual(state["executions"], 2)
            self.assertGreater(state["checks"], 2)
            self.assertEqual(len(provider.requests), 1)
            release.assert_called_once()
