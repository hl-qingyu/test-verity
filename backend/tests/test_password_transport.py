import base64
import json
import secrets
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from app.api import encryption as password_transport
from app.core.errors import AppError as HTTPException
from app.main import app
from app.security import envelopes, rate_limit

ORIGIN = {"Origin": "http://127.0.0.1:5173"}


def seal(challenge: dict, path: str, payload: dict) -> dict[str, str]:
    public_key = serialization.load_der_public_key(base64.b64decode(challenge["public_key"]))
    key = AESGCM.generate_key(bit_length=256)
    iv = secrets.token_bytes(12)
    aad = f"verity-password-v1\nPOST\n{path}\n{challenge['challenge_id']}".encode()
    wrapped = public_key.encrypt(
        key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=aad)
    )
    cipher = AESGCM(key).encrypt(iv, json.dumps(payload, ensure_ascii=False).encode(), aad)
    return {
        "challenge_id": challenge["challenge_id"],
        "wrapped_key": base64.b64encode(wrapped).decode(),
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(cipher).decode(),
    }


class EncryptedClient(TestClient):
    """Exercise the wire protocol for all existing login and account integration checks."""

    def post(self, url, **kwargs):
        payload = kwargs.get("json")
        if isinstance(payload, dict) and "password" in payload:
            challenge = super().post(
                "/api/auth/password-challenge", headers=kwargs.get("headers"), json={"path": url}
            )
            if not challenge.is_success:
                return challenge
            kwargs["json"] = seal(challenge.json(), url, payload)
        return super().post(url, **kwargs)


class SecretPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str
    confirm_password: str


class PasswordEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        rate_limit._login_windows.clear()
        envelopes._challenges.clear()
        self.path = "/api/auth/login"
        self.request = self.make_request(self.path)
        self.payload = {"password": "密🔐" * 64, "confirm_password": "密🔐" * 64}

    def make_request(self, path: str, cookie: str = "") -> Request:
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": path,
                "headers": [(b"cookie", cookie.encode())],
            }
        )

    def envelope(self):
        challenge = password_transport.issue_challenge(self.path, self.request)
        return password_transport.EncryptedRequest(**seal(challenge, self.path, self.payload))

    def test_unicode_round_trip_random_ciphertext_and_single_use(self) -> None:
        first, second = self.envelope(), self.envelope()
        self.assertNotEqual(first.ciphertext, second.ciphertext)
        self.assertNotIn(self.payload["password"], first.model_dump_json())
        decoded = password_transport.decrypt_payload(first, self.request, SecretPayload)
        self.assertEqual(decoded.password, self.payload["password"])
        with self.assertRaises(HTTPException) as caught:
            password_transport.decrypt_payload(first, self.request, SecretPayload)
        self.assertEqual(caught.exception.status_code, 400)

    def test_tamper_expiry_context_and_session_are_rejected(self) -> None:
        envelope = self.envelope()
        encrypted = bytearray(base64.b64decode(envelope.ciphertext))
        encrypted[0] ^= 1
        envelope.ciphertext = base64.b64encode(encrypted).decode()
        with self.assertRaises(HTTPException):
            password_transport.decrypt_payload(envelope, self.request, SecretPayload)
        envelope = self.envelope()
        with patch("app.security.envelopes.monotonic", return_value=float("inf")):
            with self.assertRaises(HTTPException):
                password_transport.decrypt_payload(envelope, self.request, SecretPayload)
        for request in (
            self.make_request("/api/users"),
            self.make_request(self.path, "verity_session=other"),
        ):
            with self.assertRaises(HTTPException):
                password_transport.decrypt_payload(self.envelope(), request, SecretPayload)

    def test_bad_encoding_validation_and_restarts_fail_closed(self) -> None:
        envelope = self.envelope()
        envelope.wrapped_key = "!" * 512
        with self.assertRaises(HTTPException):
            password_transport.decrypt_payload(envelope, self.request, SecretPayload)
        self.payload["extra"] = "must not be accepted"
        with self.assertRaises(HTTPException) as caught:
            password_transport.decrypt_payload(self.envelope(), self.request, SecretPayload)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertNotIn("extra", str(caught.exception.detail))
        envelope = self.envelope()
        envelopes._challenges.clear()
        with self.assertRaises(HTTPException):
            password_transport.decrypt_payload(envelope, self.request, SecretPayload)

    def test_public_endpoint_and_plaintext_rejection(self) -> None:
        with TestClient(app) as client:
            response = client.post(
                "/api/auth/password-challenge", headers=ORIGIN, json={"path": self.path}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(set(response.json()), {"challenge_id", "public_key", "expires_in"})
            self.assertEqual(
                client.post(
                    "/api/auth/password-challenge", headers=ORIGIN, json={"path": "/api/git/push"}
                ).status_code,
                422,
            )
            response = client.post(
                self.path,
                headers=ORIGIN,
                json={"login_name": "admin", "password": "not-a-real-password"},
            )
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("not-a-real-password", response.text)

    def test_actual_frontend_webcrypto_interoperates_without_plaintext_requests(self) -> None:
        frontend = Path(__file__).resolve().parents[2] / "frontend"
        if not shutil.which("node") or not (frontend / "node_modules/typescript").exists():
            self.skipTest("requires installed frontend dependencies and Node for Web Crypto check")
        challenge = password_transport.issue_challenge(self.path, self.request)
        script = r"""
const fs = require('fs'), ts = require('typescript');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('src/passwordTransport.ts', 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}
}).outputText;
const exported = {}; new Function('exports', compiled)(exported);
let envelope, calls = 0;
globalThis.fetch = async (url, options) => {
  const body = JSON.parse(options.body); calls++;
  if (url === '/api/auth/password-challenge') {
    if (Object.keys(body).join() !== 'path') throw Error('Unexpected challenge payload');
    return new Response(JSON.stringify(input.challenge), {status: 200});
  }
  if (url !== input.path || options.body.includes(input.payload.password)) {
    throw Error('Plaintext request or wrong destination');
  }
  if (Object.keys(body).sort().join() !== 'challenge_id,ciphertext,iv,wrapped_key') {
    throw Error('Unexpected request fields');
  }
  envelope = body; return new Response('', {status:200});
};
exported.postEncrypted(input.path, input.payload).then(() => {
  if (calls !== 2) throw Error('Unexpected request count');
  process.stdout.write(JSON.stringify(envelope));
}).catch(() => { process.exitCode = 1; });
"""
        completed = subprocess.run(
            [shutil.which("node"), "-e", script],
            input=json.dumps({"challenge": challenge, "path": self.path, "payload": self.payload}),
            cwd=frontend,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=15,
        )
        self.assertEqual(completed.returncode, 0, "Frontend encryption check failed")
        envelope = password_transport.EncryptedRequest.model_validate_json(completed.stdout)
        decoded = password_transport.decrypt_payload(envelope, self.request, SecretPayload)
        self.assertEqual(decoded.password, self.payload["password"])


if __name__ == "__main__":
    unittest.main()
