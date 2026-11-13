"""Cooperative cancellation shared by model transports and the scheduler."""

import socket
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event, Lock, Thread

from app.core.errors import AppError

_stop: ContextVar[Event | None] = ContextVar("ai_scheduler_stop", default=None)
_control: ContextVar["CallControl | None"] = ContextVar("ai_call_control", default=None)


@contextmanager
def execution_scope(stop):
    token = _stop.set(stop)
    try:
        yield
    finally:
        _stop.reset(token)


def connected(response):
    control = _control.get()
    if control is not None:
        control.response = response
        control.check()


class CallControl:
    def __init__(self, callback):
        self.callback = callback
        self.stop = _stop.get()
        self.finished = Event()
        self.lock = Lock()
        self.error = None
        self.response = None

    def check(self):
        with self.lock:
            if self.error:
                raise self.error
            try:
                if self.stop is not None and self.stop.is_set():
                    raise AppError(409, "ai_worker_interrupted")
                if self.callback:
                    self.callback()
            except Exception as exc:
                self.error = exc
                self.abort()
                raise

    def abort(self):
        # Shutdown unblocks a silent read. Do not release the budget until the caller exits.
        try:
            stream = getattr(self.response, "fp", None)
            raw = getattr(stream, "raw", None)
            sock = getattr(raw, "_sock", None)
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                finally:
                    # Windows may leave a blocked recv pending after shutdown alone. Detach
                    # before closing the native socket to prevent later file cleanup closing a
                    # reused handle. The budget stays held until the transport thread returns.
                    descriptor = sock.detach()
                    if descriptor != -1:
                        socket.close(descriptor)
        except OSError:
            pass

    def monitor(self):
        while not self.finished.wait(1):
            try:
                self.check()
            except Exception:
                return

    def run(self, function, *args, **kwargs):
        self.check()
        token = _control.set(self)
        # Only the scheduler guarantees an independent Session factory for each thread.
        # Direct/offline callers keep synchronous progress checks; never share their connection
        # with a monitoring thread (rollback-only integration tests bind one connection).
        watcher = (
            Thread(target=self.monitor, name="ai-cancel-monitor", daemon=True)
            if self.stop is not None
            else None
        )
        if watcher is not None:
            watcher.start()
        try:
            try:
                result = function(*args, on_progress=self.check, **kwargs)
            except Exception:
                if self.error:
                    raise self.error
                raise
            self.check()
            return result
        finally:
            self.finished.set()
            if watcher is not None:
                watcher.join()
            _control.reset(token)
