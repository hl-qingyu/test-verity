import logging
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.core.logging import LOG_DIRECTORY, configure_logging
from app.main import app


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.logger = logging.getLogger("app")
        self.handlers = self.logger.handlers[:]
        self.level, self.propagate = self.logger.level, self.logger.propagate
        self.logger.handlers = []
        self.logger.propagate = False

    def tearDown(self):
        for handler in self.logger.handlers:
            handler.close()
        self.logger.handlers = self.handlers
        self.logger.setLevel(self.level)
        self.logger.propagate = self.propagate
        self.directory.cleanup()

    def test_rotation_and_reconfiguration_do_not_duplicate_records(self):
        self.assertEqual(LOG_DIRECTORY, Path(__file__).resolve().parents[2] / "log")
        old = configure_logging("analysis-worker", self.root)
        handler = configure_logging("analysis-worker", self.root)
        self.assertIsNone(old.stream)
        self.assertEqual(len(self.logger.handlers), 1)
        handler.maxBytes, handler.backupCount = 250, 2
        for index in range(20):
            self.logger.info("analysis task=%s stage=reading_sources", index)
        handler.flush()
        files = list(self.root.glob("analysis-worker.log*"))
        self.assertEqual(len(files), 3)
        contents = "".join(path.read_text(encoding="utf-8") for path in files)
        self.assertEqual(contents.count("task=19 stage="), 1)
        self.assertNotIn("task=0 stage=", contents)

    def test_exception_values_and_preformatted_tracebacks_are_not_saved(self):
        handler = configure_logging("api", self.root)
        try:
            raise ValueError("PRIVATE_TOKEN_AND_DOCUMENT")
        except ValueError:
            record = self.logger.makeRecord(
                "app.test",
                logging.ERROR,
                __file__,
                1,
                "request_failed",
                (),
                sys.exc_info(),
            )
        record.exc_text = "PRIVATE_CACHED_EXCEPTION"
        handler.handle(record)
        handler.flush()
        content = (self.root / "api.log").read_text(encoding="utf-8")
        self.assertIn("ValueError", content)
        self.assertIn("test_logging.py:", content)
        self.assertNotIn("PRIVATE_", content)

    def test_api_logs_routes_status_and_duration_without_request_or_sql_contents(self):
        def failing():
            raise SQLAlchemyError("PRIVATE_SQL_PARAMETERS")

        app.add_api_route("/__logging_check/{value}", failing)
        route = app.routes[-1]
        try:
            with (
                patch(
                    "app.main.configure_logging",
                    side_effect=lambda service: configure_logging(service, self.root),
                ),
                TestClient(app) as client,
            ):
                self.assertEqual(
                    client.get("/api/health/live?token=PRIVATE_QUERY").status_code, 200
                )
                self.assertEqual(client.get("/PRIVATE_UNKNOWN_PATH").status_code, 404)
                self.assertEqual(
                    client.get(
                        "/__logging_check/PRIVATE_PATH", headers={"Authorization": "PRIVATE_HEADER"}
                    ).status_code,
                    503,
                )
                self.assertEqual(
                    client.post(
                        "/api/auth/login",
                        json={"password": "PRIVATE_BODY"},
                        headers={"Origin": "http://127.0.0.1:5173"},
                    ).status_code,
                    422,
                )
            content = (self.root / "api.log").read_text(encoding="utf-8")
            self.assertIn("route=/api/health/live status=200 elapsed_ms=", content)
            self.assertIn("route=unmatched status=404", content)
            self.assertIn("route=/__logging_check/{value} status=503", content)
            self.assertIn("SQLAlchemyError", content)
            self.assertIn("service_stopped service=api", content)
            self.assertNotIn("PRIVATE_", content)
        finally:
            app.router.routes.remove(route)
