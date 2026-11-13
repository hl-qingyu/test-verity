"""Application-only rotating logs; exclude request contents and exception values."""

import copy
import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Literal

LOG_DIRECTORY = Path(__file__).resolve().parents[3] / "log"


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record = copy.copy(record)
        record.exc_text = None  # Discard exception text cached by other handlers.
        record.stack_info = None
        return super().format(record)

    def formatException(
        self, ei: tuple[type[BaseException], BaseException, TracebackType | None]
    ) -> str:
        # Exception messages/SQL parameters and source lines may contain private data.
        frames = [
            f"  {Path(frame.f_code.co_filename).name}:{line} in {frame.f_code.co_name}"
            for frame, line in traceback.walk_tb(ei[2])
        ]
        return "\n".join([ei[0].__name__, *frames])


def configure_logging(
    service: Literal["api", "analysis-worker", "chat-worker"], directory: Path = LOG_DIRECTORY
) -> RotatingFileHandler:
    if service not in ("api", "analysis-worker", "chat-worker"):
        raise ValueError("Unknown log service")
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / f"{service}.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.name = "verity-file"
    handler.setFormatter(
        SafeFormatter("%(asctime)s %(levelname)s pid=%(process)d %(name)s %(message)s")
    )
    logger = logging.getLogger("app")
    for previous in logger.handlers[:]:
        if previous.name == handler.name:
            logger.removeHandler(previous)
            previous.close()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Libraries such as SQLAlchemy/httpx are deliberately not attached to this file.
    logger.info("service_started service=%s", service)
    return handler
