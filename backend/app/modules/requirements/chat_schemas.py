from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    question: str = Field(min_length=1, max_length=8000)
    last_turn_id: int = Field(default=0, ge=0)
    risk_key: str = Field(default="", max_length=200)

    @field_validator("question")
    @classmethod
    def valid_question(cls, value):
        value = value.strip()
        if not value or "\x00" in value:
            raise ValueError("invalid_question")
        value.encode("utf-8")
        return value

    @field_validator("risk_key")
    @classmethod
    def valid_risk_key(cls, value):
        value = value.strip()
        if "\x00" in value:
            raise ValueError("invalid_risk_key")
        return value
