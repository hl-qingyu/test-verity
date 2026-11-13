import hashlib

from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import COOKIE_NAME
from app.security import envelopes
from app.security.envelopes import EncryptedRequest


class ChallengeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(
        max_length=100,
        pattern=r"^(/api/auth/login|/api/users|/api/users/[1-9][0-9]*/reset-password|/api/ai-service/(personal(/test|/models)?|configuration|activate|test)|/api/github/connections(/probe)?)$",
    )


def session_binding(request: Request) -> str:
    return hashlib.sha256(request.cookies.get(COOKIE_NAME, "").encode("utf-8")).hexdigest()


def context(request: Request) -> envelopes.EnvelopeContext:
    return envelopes.EnvelopeContext(request.url.path, session_binding(request), request.method)


def issue_challenge(path: str, request: Request) -> dict[str, str | int]:
    return envelopes.issue_challenge(path, context(request))


def decrypt_payload[T: BaseModel](
    envelope: EncryptedRequest, request: Request, model: type[T]
) -> T:
    return envelopes.decrypt_payload(envelope, context(request), model)
