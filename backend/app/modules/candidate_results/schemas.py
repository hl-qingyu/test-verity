from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    base_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_json: str = Field(min_length=1, max_length=16 * 1024 * 1024)
    reason: str = Field(min_length=1, max_length=10000)
    confirmed: Literal[True]

    @field_validator("reason")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("reason_required")
        return value.strip()

    @field_validator("candidate_json", "reason")
    @classmethod
    def valid_unicode(cls, value):
        value.encode("utf-8")
        return value
