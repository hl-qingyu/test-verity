"""Real PostgreSQL checks roll back; upstream responses are explicitly simulated."""

import io
import json
import os
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import test_auth
from pydantic import ValidationError
from sqlalchemy.orm import Session
from test_password_transport import seal

from app.core.errors import AppError as HTTPException
from app.db.models import AIConnection
from app.integrations.responses import NoRedirect, list_models, probe_model
from app.modules.ai.schemas import ConnectionInput, ModelDiscoveryInput
from app.modules.ai.service import cipher

PAYLOAD = {
    "name": "测试配置",
    "base_url": "https://sub2api.geekuat.com",
    "model": "test-model",
    "api_key": "test-only-secret",
    "version": 0,
}
ORIGIN = test_auth.ORIGIN


class AIProtocolTests(unittest.TestCase):
    def test_model_discovery_protocol(self):
        parsed = ModelDiscoveryInput(base_url=PAYLOAD["base_url"], api_key="secret", version=0)
        self.assertNotIn("secret", repr(parsed))
        with self.assertRaises(ValidationError):
            ModelDiscoveryInput(base_url="http://relay.example", api_key="secret", version=0)
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            {"object": "list", "data": [{"id": "z-model"}, {"id": "a-model"}, {"id": "z-model"}]}
        ).encode()
        with patch("app.integrations.responses.build_opener", return_value=opener) as builder:
            self.assertEqual(list_models(PAYLOAD["base_url"], "secret"), ["a-model", "z-model"])
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, PAYLOAD["base_url"] + "/models")
            self.assertEqual(request.get_method(), "GET")
            self.assertEqual(request.get_header("Authorization"), "Bearer secret")
            self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
            self.assertEqual(type(builder.call_args.args[0]).__name__, "ProxyHandler")
            self.assertEqual(type(builder.call_args.args[1]).__name__, "NoRedirect")
            for body in [
                b"{}",
                b"[]",
                b"not-json",
                b'{"object":"list","data":[{}]}',
                b"x" * 262145,
            ]:
                opener.open.return_value.__enter__.return_value.read.return_value = body
                with self.assertRaises(HTTPException) as caught:
                    list_models(PAYLOAD["base_url"], "secret")
                self.assertEqual(caught.exception.detail, "ai_invalid_response")
            opener.open.side_effect = HTTPError(
                request.full_url, 404, "secret", {}, io.BytesIO(b"secret")
            )
            with self.assertRaises(HTTPException) as caught:
                list_models(PAYLOAD["base_url"], "secret")
            self.assertEqual(caught.exception.detail, "ai_models_unavailable")

    def test_allowed_addresses_and_secret_validation(self):
        for url in [
            "https://sub2api.geekuat.com",
            "https://sub2api.geekuat.com/v1",
            "https://api.openai.com/v1/",
            "https://relay.example/custom/v1/",
        ]:
            parsed = ConnectionInput(**{**PAYLOAD, "base_url": url})
            self.assertEqual(parsed.base_url, url.rstrip("/"))
            self.assertNotIn(PAYLOAD["api_key"], repr(parsed))
            discovery = ModelDiscoveryInput(base_url=url, version=0)
            self.assertEqual(discovery.base_url, parsed.base_url)
        for url in [
            "http://sub2api.geekuat.com",
            "https://127.0.0.1",
            "https://sub2api.geekuat.com@evil.invalid",
            "https://sub2api.geekuat.com?key=secret",
            "https://sub2api.geekuat.com/v1/../admin",
        ]:
            with self.assertRaises(ValidationError):
                ConnectionInput(**{**PAYLOAD, "base_url": url})
        with self.assertRaises(ValidationError):
            ConnectionInput(**{**PAYLOAD, "api_key": "secret\nheader"})

    def test_probe_protocol_failures_and_no_redirect(self):
        success = {
            "status": "completed",
            "output": [{"content": [{"type": "output_text", "text": "OK"}]}],
        }
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(
            success
        ).encode()
        with patch("app.integrations.responses.build_opener", return_value=opener):
            probe_model(PAYLOAD["base_url"], "test-model", "fake-secret")
            request = opener.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://sub2api.geekuat.com/responses")
            body = json.loads(request.data)
            self.assertEqual(body["input"], "请只回复 OK")
            self.assertFalse(body["store"])
            self.assertFalse(body["stream"])
            self.assertEqual(request.get_header("Authorization"), "Bearer fake-secret")
            self.assertNotIn("reasoning", body)
            for effort in ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"]:
                probe_model(PAYLOAD["base_url"], "test-model", "fake-secret", effort)
                self.assertEqual(
                    json.loads(opener.open.call_args.args[0].data)["reasoning"], {"effort": effort}
                )
                self.assertEqual(opener.open.call_args.kwargs["timeout"], 120)
            for status in [301, 400, 401, 403, 404, 422, 429, 500]:
                opener.open.side_effect = HTTPError(
                    request.full_url, status, "secret upstream error", {}, io.BytesIO(b"secret")
                )
                with self.assertRaises(HTTPException) as caught:
                    probe_model(PAYLOAD["base_url"], "test-model", "fake-secret")
                self.assertNotIn("secret", caught.exception.detail)
                if status in (400, 422):
                    self.assertEqual(caught.exception.detail, "ai_request_rejected")
            opener.open.side_effect = TimeoutError()
            with self.assertRaises(HTTPException) as caught:
                probe_model(PAYLOAD["base_url"], "test-model", "fake-secret")
            self.assertEqual(caught.exception.status_code, 504)
            opener.open.side_effect = None
            for body in [
                b"{}",
                b"[]",
                b"not-json",
                b'{"status":"completed","output":[]}',
                b"x" * 262145,
            ]:
                opener.open.return_value.__enter__.return_value.read.return_value = body
                with self.assertRaises(HTTPException):
                    probe_model(PAYLOAD["base_url"], "test-model", "fake-secret")
        self.assertIsNone(
            NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid")
        )


@unittest.skipUnless(os.environ.get("RUN_AUTH_DB_TESTS") == "1", "requires PostgreSQL opt-in")
class AIDatabaseTests(unittest.TestCase):
    setUpClass = classmethod(test_auth.AuthDatabaseTests.setUpClass.__func__)
    setUp = test_auth.AuthDatabaseTests.setUp
    tearDown = test_auth.AuthDatabaseTests.tearDown
    login = test_auth.AuthDatabaseTests.login

    def encrypted(self, path, payload):
        challenge = self.client.post(
            "/api/auth/password-challenge", headers=ORIGIN, json={"path": path}
        )
        self.assertEqual(challenge.status_code, 200)
        response = self.client.post(
            path, headers=ORIGIN, json=seal(challenge.json(), path, payload)
        )
        self.assertNotIn("test-only-secret", response.text)
        return response

    def test_model_discovery_uses_only_own_key_and_does_not_save(self):
        self.assertEqual(
            self.client.post(
                "/api/ai-service/personal/models", headers=ORIGIN, json={}
            ).status_code,
            401,
        )
        self.login(self.member_name)
        path = "/api/ai-service/personal/models"
        with patch(
            "app.integrations.responses.list_models", return_value=["model-one"]
        ) as discover:
            self.assertEqual(
                self.encrypted(path, {"base_url": PAYLOAD["base_url"], "version": 0}).status_code,
                422,
            )
            result = self.encrypted(
                path, {"base_url": PAYLOAD["base_url"], "version": 0, "api_key": PAYLOAD["api_key"]}
            )
            self.assertEqual(result.json(), {"models": ["model-one"]})
            discover.assert_called_once_with(PAYLOAD["base_url"], PAYLOAD["api_key"])
            self.assertIsNone(self.client.get("/api/ai-service").json()["personal"])
            self.assertEqual(self.encrypted("/api/ai-service/personal", PAYLOAD).status_code, 200)
            result = self.encrypted(path, {"base_url": PAYLOAD["base_url"], "version": 1})
            self.assertEqual(result.json(), {"models": ["model-one"]})
            self.assertEqual(discover.call_count, 2)
            self.assertEqual(
                self.encrypted(path, {"base_url": PAYLOAD["base_url"], "version": 0}).status_code,
                409,
            )
            self.assertEqual(discover.call_count, 2)
            self.assertEqual(self.client.get("/api/ai-service").json()["personal"]["version"], 1)

    def test_reasoning_effort_roundtrip_and_invalid_value(self):
        self.assertEqual(self.login(self.member_name).status_code, 200)
        for version, effort in enumerate(
            ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra", "default"]
        ):
            response = self.encrypted(
                "/api/ai-service/personal",
                {**PAYLOAD, "reasoning_effort": effort, "version": version},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                self.client.get("/api/ai-service").json()["personal"]["reasoning_effort"], effort
            )
        response = self.encrypted(
            "/api/ai-service/personal", {**PAYLOAD, "reasoning_effort": "invalid", "version": 9}
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/api/ai-service").json()["personal"]["version"], 9)

    def test_personal_only_storage_isolation_and_retired_platform_routes(self):
        self.assertEqual(self.client.get("/api/ai-service").status_code, 401)
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            legacy = db.get(AIConnection, 0)
            if legacy is None:
                legacy = AIConnection(
                    id=0,
                    owner_id=None,
                    name="历史平台配置",
                    base_url="https://api.openai.com/v1",
                    model="legacy-model",
                    encrypted_key=cipher().encrypt(b"legacy-platform-secret").decode(),
                    version=1,
                    updated_by=self.admin_id,
                )
                db.add(legacy)
            db.commit()
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.encrypted("/api/ai-service/personal", PAYLOAD).status_code, 200)
        for username in [self.admin_name, self.member_name]:
            self.assertEqual(self.login(username).status_code, 200)
            read = self.client.get("/api/ai-service")
            self.assertEqual(read.headers["cache-control"], "no-store")
            self.assertEqual(
                set(read.json()),
                {
                    "personal",
                    "allowed_base_urls",
                    "cli",
                    "call_mode",
                    "preference_version",
                    "cli_runtime",
                },
            )
            for path in [
                "/api/ai-service/platform",
                "/api/ai-service/platform/test",
                "/api/ai-service/source",
            ]:
                self.assertEqual(self.client.post(path, headers=ORIGIN, json={}).status_code, 404)
                self.assertEqual(
                    self.client.post(
                        "/api/auth/password-challenge", headers=ORIGIN, json={"path": path}
                    ).status_code,
                    422,
                )
        self.assertIsNone(self.client.get("/api/ai-service").json()["personal"])
        with patch("app.integrations.responses.probe_model") as probe:
            self.assertEqual(
                self.encrypted(
                    "/api/ai-service/personal/test", {**PAYLOAD, "api_key": ""}
                ).status_code,
                422,
            )
            probe.assert_not_called()
        self.assertEqual(
            self.encrypted(
                "/api/ai-service/personal", {**PAYLOAD, "owner_id": self.admin_id}
            ).status_code,
            422,
        )
        self.assertEqual(
            self.encrypted("/api/ai-service/personal", {**PAYLOAD, "api_key": ""}).status_code, 422
        )
        saved = self.encrypted("/api/ai-service/personal", PAYLOAD)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["version"], 1)
        self.assertNotIn("encrypted_key", saved.json())
        self.assertEqual(self.encrypted("/api/ai-service/personal", PAYLOAD).status_code, 409)
        self.assertEqual(
            self.encrypted(
                "/api/ai-service/personal", {**PAYLOAD, "version": 1, "api_key": ""}
            ).status_code,
            200,
        )
        with Session(self.connection, join_transaction_mode="create_savepoint") as db:
            row = db.get(AIConnection, self.member_id)
            self.assertNotIn(PAYLOAD["api_key"], row.encrypted_key)
            self.assertEqual(
                cipher().decrypt(row.encrypted_key.encode()).decode(), PAYLOAD["api_key"]
            )
            self.assertIsNotNone(db.get(AIConnection, 0))
        self.assertEqual(
            self.encrypted(
                "/api/ai-service/personal",
                {**PAYLOAD, "version": 2, "api_key": "", "base_url": "https://api.openai.com/v1"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.encrypted(
                "/api/ai-service/personal",
                {**PAYLOAD, "version": 2, "api_key": "test-only-replacement"},
            ).status_code,
            200,
        )
        self.login()
        self.assertEqual(self.client.get("/api/ai-service").json()["personal"]["version"], 1)

    def test_test_does_not_save_or_fallback_and_replay_is_rejected(self):
        self.assertEqual(self.login(self.member_name).status_code, 200)
        with patch("app.integrations.responses.probe_model") as probe:
            self.assertEqual(
                self.encrypted("/api/ai-service/personal/test", PAYLOAD).status_code, 200
            )
            probe.assert_called_once_with(
                PAYLOAD["base_url"], PAYLOAD["model"], PAYLOAD["api_key"], "default"
            )
            self.assertIsNone(self.client.get("/api/ai-service").json()["personal"])
        self.assertEqual(self.encrypted("/api/ai-service/personal", PAYLOAD).status_code, 200)
        with patch(
            "app.integrations.responses.probe_model", side_effect=HTTPException(504, "ai_timeout")
        ) as probe:
            result = self.encrypted(
                "/api/ai-service/personal/test", {**PAYLOAD, "version": 1, "api_key": ""}
            )
            self.assertEqual(result.status_code, 504)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(self.client.get("/api/ai-service").json()["personal"]["version"], 1)
        path = "/api/ai-service/personal"
        challenge = self.client.post(
            "/api/auth/password-challenge", headers=ORIGIN, json={"path": path}
        ).json()
        envelope = seal(challenge, path, {**PAYLOAD, "version": 1})
        self.assertEqual(self.client.post(path, headers=ORIGIN, json=envelope).status_code, 200)
        self.assertEqual(self.client.post(path, headers=ORIGIN, json=envelope).status_code, 400)
        self.assertEqual(self.client.post(path, headers=ORIGIN, json=PAYLOAD).status_code, 422)
