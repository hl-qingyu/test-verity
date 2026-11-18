"""Real PostgreSQL idle-session recovery; independent keys and no business writes."""

import os
import unittest
from contextlib import ExitStack
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app import chat_worker as worker
from app.db.scheduler import DATABASE_ERRORS, SchedulerConnection
from app.db.session import get_engine, get_scheduler_engine


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class SchedulerConnectionDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = get_scheduler_engine()
        self.key = 1000000000 + uuid4().int % 900000000

    def test_heartbeat_keeps_lock_during_long_non_database_work_and_close_releases_it(self):
        self.assertIsInstance(self.engine.pool, NullPool)
        owner = SchedulerConnection(self.engine, idle_timeout_ms=1000, heartbeat_seconds=0.1)
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            try:
                self.assertTrue(
                    owner.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
                )
                owner.commit()
                Event().wait(2.2)
                self.assertEqual(
                    owner.scalar(text("SELECT current_setting('idle_session_timeout')")), "1s"
                )
                self.assertEqual(
                    owner.scalar(
                        text("SELECT current_setting('idle_in_transaction_session_timeout')")
                    ),
                    "1s",
                )
                self.assertFalse(
                    observer.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
                )
                owner.close()
                self.assertTrue(
                    observer.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key})
                )
            finally:
                owner.close()
                observer.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": self.key})

    def test_new_worker_waits_for_dead_heartbeat_session_to_expire_without_terminating_it(self):
        old = SchedulerConnection(self.engine, idle_timeout_ms=1000, heartbeat_seconds=0.1)
        self.assertTrue(old.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}))
        old_pid = old.scalar(text("SELECT pg_backend_pid()"))
        old.commit()
        waits, owners = [], []

        def pause(seconds):
            waits.append(seconds)
            # Simulate a dead client's lost heartbeat, without closing its DB
            # connection or calling pg_terminate_backend/pg_advisory_unlock.
            old._stop.set()
            old._thread.join()
            Event().wait(0.1)
            self.assertLess(len(waits), 40, "server must release the orphan automatically")

        def ready(lock, factory, logger):
            owners.append(lock.scalar(text("SELECT pg_backend_pid()")))
            raise KeyboardInterrupt

        try:
            with ExitStack() as stack:
                stack.enter_context(patch.object(worker, "configure_logging"))
                stack.enter_context(patch.object(worker, "get_engine", return_value=get_engine()))
                stack.enter_context(
                    patch.object(worker, "get_scheduler_engine", return_value=self.engine)
                )
                stack.enter_context(patch.object(worker, "SCHEDULER_LOCK_ID", self.key))
                stack.enter_context(
                    patch.object(
                        worker,
                        "SchedulerConnection",
                        side_effect=lambda engine: SchedulerConnection(
                            engine, idle_timeout_ms=1000, heartbeat_seconds=0.1
                        ),
                    )
                )
                session = stack.enter_context(patch.object(worker, "Session"))
                session.return_value.__enter__.return_value.scalar.return_value = None
                stack.enter_context(patch.object(worker.reservations, "recover_exited"))
                stack.enter_context(patch.object(worker, "_restore_cli_results"))
                recoveries = []
                for module in (
                    worker.chat_execution,
                    worker.risk_analysis_execution,
                    worker.code_analysis_execution,
                    worker.change_analysis_execution,
                    worker.generation_execution,
                    worker.case_analysis_execution,
                    worker.skills_execution,
                ):
                    recoveries.append(stack.enter_context(patch.object(module, "recover")))
                schedule = stack.enter_context(patch.object(worker, "_schedule", side_effect=ready))
                stack.enter_context(patch.object(worker.time, "sleep", side_effect=pause))
                worker.main()
                self.assertGreater(len(waits), 0)
                self.assertEqual(schedule.call_count, 1)
                self.assertNotEqual(owners, [old_pid])
                for recovery in recoveries:
                    recovery.assert_called_once()
            with self.assertRaises(DATABASE_ERRORS) as first_error:
                old.scalar(text("SELECT 1"))
            with self.assertRaises(DATABASE_ERRORS) as repeated_error:
                old.scalar(text("SELECT 1"))
            self.assertIs(
                first_error.exception,
                repeated_error.exception,
                "a lost advisory-lock session must not silently reconnect",
            )
        finally:
            old.close()

    def test_scheduler_timeouts_do_not_change_business_connection_settings(self):
        owner = SchedulerConnection(self.engine)
        try:
            self.assertEqual(
                owner.scalar(text("SELECT current_setting('idle_session_timeout')")), "1min"
            )
            self.assertEqual(
                owner.scalar(text("SELECT current_setting('application_name')")),
                "test-verity-scheduler",
            )
            with get_engine().connect() as business:
                self.assertEqual(
                    business.scalar(text("SELECT current_setting('idle_session_timeout')")), "0"
                )
                self.assertEqual(
                    business.scalar(
                        text("SELECT current_setting('idle_in_transaction_session_timeout')")
                    ),
                    "0",
                )
        finally:
            owner.close()
