import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import app


class HealthTests(unittest.TestCase):
    def test_health_and_database_failure_boundary(self) -> None:
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/health/live").status_code, 200)
            with patch("app.main.check_database"):
                self.assertEqual(client.get("/api/health/ready").status_code, 200)
            failure = OperationalError("SELECT 1", {}, Exception("secret connection info"))
            with patch("app.main.check_database", side_effect=failure):
                response = client.get("/api/health/ready")
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json(), {"detail": "database_unavailable"})
            self.assertEqual(client.post("/api/git/push").status_code, 404)


if __name__ == "__main__":
    unittest.main()
