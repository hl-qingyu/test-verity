"""Singleton recovery and bounded scheduling; model calls are simulated."""

import logging
import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import OperationalError

from app import chat_worker as worker


class ChatWorkerTests(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(worker, "configure_logging"))
        self.session = self.patches.enter_context(patch.object(worker, "Session"))
        self.session.return_value.__enter__.return_value.scalar.return_value = None
        self.engine = self.patches.enter_context(patch.object(worker, "get_engine")).return_value
        self.patches.enter_context(
            patch.object(worker, "get_scheduler_engine", return_value=self.engine)
        )
        self.patches.enter_context(
            patch.object(worker, "SchedulerConnection", side_effect=lambda engine: engine.connect())
        )
        self.sleep = self.patches.enter_context(patch.object(worker.time, "sleep"))
        self.patches.enter_context(patch.object(worker.reservations, "recover_exited"))
        self.patches.enter_context(patch.object(worker, "_restore_cli_results"))
        self.patches.enter_context(
            patch.object(worker.case_analysis_execution, "claim_application", return_value=None)
        )
        self.patches.enter_context(
            patch.object(worker.generation_execution, "claim_application", return_value=None)
        )
        for module in (
            worker.chat_execution,
            worker.risk_analysis_execution,
            worker.code_analysis_execution,
            worker.change_analysis_execution,
            worker.generation_execution,
            worker.case_analysis_execution,
            worker.skills_execution,
        ):
            self.patches.enter_context(patch.object(module, "recover"))

    def connection(self, owned=True):
        connection = MagicMock()
        connection.scalar.return_value = owned
        context = MagicMock()
        context.__enter__.return_value = connection
        return context, connection

    def test_duplicate_start_never_recovers_or_claims(self):
        context, conn = self.connection(False)
        self.engine.connect.return_value = context
        with patch.object(worker, "_schedule") as schedule:
            self.sleep.side_effect = KeyboardInterrupt
            worker.main()
            schedule.assert_not_called()
        self.session.assert_not_called()
        conn.invalidate.assert_called_once()

    def test_disconnect_reacquires_singleton_before_recovery(self):
        contexts, connections = zip(
            self.connection(), self.connection(False), self.connection(), strict=True
        )
        self.engine.connect.side_effect = contexts
        with patch.object(
            worker,
            "_schedule",
            side_effect=[
                OperationalError(None, None, RuntimeError()),
                KeyboardInterrupt,
            ],
        ) as schedule:
            worker.main()
        self.assertEqual(schedule.call_count, 2)
        self.assertEqual(worker.skills_execution.recover.call_count, 2)
        self.assertEqual(self.sleep.call_count, 2)
        for conn in connections:
            conn.invalidate.assert_called_once()

    def test_lost_lock_reconnects_without_stopping_running_call(self):
        lock = MagicMock()
        lock.scalar.side_effect = [True, False]
        replacement = MagicMock()
        replacement.scalar.side_effect = [True, True, KeyboardInterrupt]
        lock.engine.connect.return_value = replacement
        entered, ended = Event(), Event()
        stop = Event()
        original_wait = stop.wait

        def wait(seconds):
            if seconds == 5:
                self.assertFalse(stop.is_set(), "database outage must not set CLI stop")
                return False
            return original_wait(seconds)

        def execute(model, execute, key, reservation, factory, stop, logger):
            entered.set()
            try:
                stop.wait(3)
            finally:
                ended.set()

        def claim(*args, **kwargs):
            return None if entered.is_set() else (1, "test-reservation")

        with (
            patch.object(worker, "Settings", return_value=MagicMock(ai_max_concurrent=1)),
            patch.object(worker.scheduling, "claim", side_effect=claim),
            patch.object(worker, "_run_task", side_effect=execute),
            patch.object(worker, "Event", return_value=stop),
            patch.object(stop, "wait", side_effect=wait),
        ):
            self.sleep.side_effect = lambda _: entered.wait(2)
            with self.assertRaises(KeyboardInterrupt):
                worker._schedule(lock, self.session, logging.getLogger("test"))
            self.assertTrue(ended.is_set())
            replacement.scalar.assert_any_call(unittest.mock.ANY, {"key": worker.SCHEDULER_LOCK_ID})
            self.assertEqual(replacement.scalar.call_count, 3)

    def test_unknown_live_call_blocks_recovery_and_new_work(self):
        context, conn = self.connection()
        self.engine.connect.return_value = context
        self.session.return_value.__enter__.return_value.scalar.return_value = "unknown-call"
        with patch.object(worker, "_schedule") as schedule:
            self.sleep.side_effect = KeyboardInterrupt
            worker.main()
            schedule.assert_not_called()
        worker.skills_execution.recover.assert_not_called()
        schedule.assert_not_called()
        conn.invalidate.assert_called_once()

    def test_application_error_keeps_scheduling_and_database_errors_propagate(self):
        logger = logging.getLogger("test")
        with (
            patch.object(worker.case_analysis_execution, "claim_application", return_value=1),
            patch.object(worker.case_analysis_apply, "execute", side_effect=RuntimeError) as first,
            patch.object(worker.generation_execution, "claim_application", return_value=2),
            patch.object(worker.generation_apply, "execute") as second,
        ):
            with self.assertLogs(logger, level="WARNING") as logs:
                worker._run_applications(self.session, logger)
            self.assertEqual(
                logs.output, ["WARNING:test:analysis_application_failed type=RuntimeError"]
            )
            second.assert_called_once_with(2, self.session)

            first.side_effect = OperationalError(None, None, RuntimeError())
            with self.assertRaises(OperationalError):
                worker._run_applications(self.session, logger)
            second.assert_called_once()

    def test_two_slots_run_together_without_claiming_a_third(self):
        lock = MagicMock()
        lock.scalar.side_effect = [True, True, KeyboardInterrupt]
        entered = [Event(), Event()]
        ended = [Event(), Event()]
        claims = []

        def execute(model, execute, key, reservation, factory, stop, logger):
            entered[key - 1].set()
            try:
                stop.wait(3)
            finally:
                ended[key - 1].set()

        def claim(*args, **kwargs):
            key = len(claims) + 1
            claims.append(key)
            return key, f"reservation-{key}"

        def cycle(_):
            self.assertTrue(all(event.wait(2) for event in entered))

        with (
            patch.object(worker, "Settings", return_value=MagicMock(ai_max_concurrent=2)),
            patch.object(worker.scheduling, "claim", side_effect=claim),
            patch.object(worker, "_run_task", side_effect=execute),
            patch.object(worker, "_run_applications", return_value=True) as apply,
        ):
            self.sleep.side_effect = cycle
            with self.assertRaises(KeyboardInterrupt):
                worker._schedule(lock, self.session, logging.getLogger("test"))
            self.assertEqual(claims, [1, 2])
            self.assertTrue(all(event.is_set() for event in ended))
            self.assertEqual(apply.call_count, 2)

    def test_idle_backoff_resets_when_application_is_claimed(self):
        lock = MagicMock()
        lock.scalar.side_effect = [True] * 6 + [KeyboardInterrupt]
        with (
            patch.object(worker.scheduling, "claim", return_value=None),
            patch.object(worker, "_run_applications", side_effect=[False] * 4 + [True, False]),
            self.assertRaises(KeyboardInterrupt),
        ):
            worker._schedule(lock, self.session, logging.getLogger("test"))
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [1, 2, 4, 5, 1, 1])
