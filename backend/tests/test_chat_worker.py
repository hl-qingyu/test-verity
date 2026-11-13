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
        self.sleep = self.patches.enter_context(patch.object(worker.time, "sleep"))
        self.patches.enter_context(patch.object(worker.reservations, "recover_exited"))
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
            with self.assertRaisesRegex(SystemExit, "Worker已运行"):
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

    def test_lost_lock_stops_running_call_before_returning(self):
        lock = MagicMock()
        lock.scalar.side_effect = [True, False]
        entered, ended = Event(), Event()

        def execute(key, factory):
            from app.integrations.call_control import CallControl

            entered.set()
            control = CallControl(None)
            try:
                control.stop.wait(3)
            finally:
                ended.set()

        def claim(*args, **kwargs):
            return None if entered.is_set() else (1, "test-reservation")

        with (
            patch.object(worker, "Settings", return_value=MagicMock(ai_max_concurrent=1)),
            patch.object(worker.scheduling, "claim", side_effect=claim),
            patch.object(worker.skills_execution, "execute", side_effect=execute),
            patch.object(worker.reservations, "release") as release,
        ):
            self.sleep.side_effect = lambda _: entered.wait(2)
            with self.assertRaises(OperationalError):
                worker._schedule(lock, self.session, logging.getLogger("test"))
            self.assertTrue(ended.is_set())
            release.assert_called_once()
            self.assertTrue(release.call_args.kwargs["interrupted"])

    def test_unknown_live_call_blocks_recovery_and_new_work(self):
        context, conn = self.connection()
        self.engine.connect.return_value = context
        self.session.return_value.__enter__.return_value.scalar.return_value = "unknown-call"
        with patch.object(worker, "_schedule") as schedule:
            with self.assertRaisesRegex(SystemExit, "尚未核验结束"):
                worker.main()
        worker.skills_execution.recover.assert_not_called()
        schedule.assert_not_called()
        conn.invalidate.assert_called_once()

    def test_two_slots_run_together_without_claiming_a_third(self):
        lock = MagicMock()
        lock.scalar.side_effect = [True, True, False]
        entered = [Event(), Event()]
        ended = [Event(), Event()]
        claims = []

        def execute(key, factory):
            from app.integrations.call_control import CallControl

            entered[key - 1].set()
            try:
                CallControl(None).stop.wait(3)
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
            patch.object(worker.skills_execution, "execute", side_effect=execute),
            patch.object(worker.case_analysis_execution, "execute", side_effect=execute),
            patch.object(worker.reservations, "release") as release,
        ):
            self.sleep.side_effect = cycle
            with self.assertRaises(OperationalError):
                worker._schedule(lock, self.session, logging.getLogger("test"))
            self.assertEqual(claims, [1, 2])
            self.assertTrue(all(event.is_set() for event in ended))
            self.assertEqual(release.call_count, 2)
