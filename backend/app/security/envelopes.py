"""Browser Web Crypto envelopes; TLS is still required outside loopback development."""

import base64
import secrets
from dataclasses import dataclass
from threading import Lock
from time import monotonic

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import AppError

_private_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
_public_key = base64.b64encode(
    _private_key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
).decode("ascii")
# ponytail: single-worker, bounded challenge cache. Multi-worker deployment needs
# shared one-time consumption and key management before enabling this protocol there.
_challenges: dict[str, tuple[float, str, str]] = {}
_challenge_lock = Lock()


class EncryptedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    challenge_id: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    wrapped_key: str = Field(min_length=512, max_length=512)
    iv: str = Field(min_length=16, max_length=16)
    ciphertext: str = Field(min_length=24, max_length=65536)


@dataclass(frozen=True)
class EnvelopeContext:
    path: str
    binding: str
    method: str = "POST"


def issue_challenge(path: str, request: EnvelopeContext) -> dict[str, str | int]:
    now = monotonic()
    nonce = secrets.token_urlsafe(32)
    with _challenge_lock:
        for key in [key for key, (expires, _, _) in _challenges.items() if expires <= now]:
            del _challenges[key]
        if len(_challenges) >= 2048:
            raise AppError(429, "too_many_attempts")
        _challenges[nonce] = (now + 120, path, request.binding)
    return {"challenge_id": nonce, "public_key": _public_key, "expires_in": 120}


def decrypt_payload[T: BaseModel](
    envelope: EncryptedRequest, request: EnvelopeContext, model: type[T]
) -> T:
    with _challenge_lock:
        challenge = _challenges.pop(envelope.challenge_id, None)
    if (
        challenge is None
        or challenge[0] <= monotonic()
        or challenge[1] != request.path
        or challenge[2] != request.binding
        or request.method != "POST"
    ):
        raise AppError(400, "invalid_password_envelope")
    aad = f"verity-password-v1\nPOST\n{request.path}\n{envelope.challenge_id}".encode()
    try:
        wrapped_key = base64.b64decode(envelope.wrapped_key, validate=True)
        iv = base64.b64decode(envelope.iv, validate=True)
        ciphertext = base64.b64decode(envelope.ciphertext, validate=True)
        if len(wrapped_key) != 384 or len(iv) != 12:
            raise ValueError("invalid_size")
        key = _private_key.decrypt(
            wrapped_key,
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=aad),
        )
        if len(key) != 32:
            raise ValueError("invalid_key_size")
        plaintext = AESGCM(key).decrypt(iv, ciphertext, aad)
    except (ValueError, InvalidTag):
        raise AppError(400, "invalid_password_envelope") from None
    try:
        return model.model_validate_json(plaintext)
    except ValidationError:
        # Never attach decrypted values or Pydantic's input details to responses.
        raise AppError(422, "invalid_request") from None
