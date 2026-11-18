"""A dedicated, heartbeating PostgreSQL session for the scheduler advisory lock."""

import logging
from threading import Event, RLock, Thread

from sqlalchemy import Engine, text
from sqlalchemy.exc import InterfaceError, OperationalError

DATABASE_ERRORS = (OperationalError, InterfaceError)
logger = logging.getLogger(__name__)


class SchedulerConnection:
    def __init__(
        self, engine: Engine, *, idle_timeout_ms: int = 60000, heartbeat_seconds: float = 5
    ) -> None:
        self.engine = engine
        self._mutex = RLock()
        self._stop = Event()
        self._error = None
        self._closed = False
        self._connection = engine.connect().execution_options(isolation_level="AUTOCOMMIT")
        try:
            self._connection.execute(
                text(
                    "SELECT set_config('idle_session_timeout', :timeout, false), "
                    "set_config('idle_in_transaction_session_timeout', :timeout, false), "
                    "set_config('statement_timeout', '15000', false)"
                ),
                {"timeout": str(idle_timeout_ms)},
            )
            self._connection.commit()
        except BaseException:
            self._connection.invalidate()
            self._connection.close()
            raise
        self._thread = Thread(
            target=self._heartbeat,
            args=(heartbeat_seconds,),
            name="scheduler-db-heartbeat",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "scheduler_database_session_ready idle_timeout_ms=%s heartbeat_seconds=%s",
            idle_timeout_ms,
            heartbeat_seconds,
        )

    def _call(self, method, *args, **kwargs):
        with self._mutex:
            if self._error is not None:
                raise self._error
            if self._closed:
                raise OperationalError(None, None, RuntimeError("scheduler_connection_closed"))
            try:
                return getattr(self._connection, method)(*args, **kwargs)
            except DATABASE_ERRORS as error:
                # Never let SQLAlchemy silently reconnect a session that has lost
                # its advisory lock. The scheduler must acquire the lock anew.
                self._error = error
                raise

    def scalar(self, statement, *args, **kwargs):
        return self._call("scalar", statement, *args, **kwargs)

    def commit(self):
        return self._call("commit")

    def _heartbeat(self, seconds):
        while not self._stop.wait(seconds):
            try:
                with self._mutex:
                    self.scalar(text("SELECT 1"))
                    self.commit()
            except DATABASE_ERRORS:
                return

    def close(self):
        self._stop.set()
        self._thread.join()
        with self._mutex:
            if not self._closed:
                self._closed = True
                self._connection.invalidate()
                self._connection.close()

    def invalidate(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
