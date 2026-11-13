import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.integrations.ai_client import CallMode
from app.integrations.responses import ReasoningEffort, normalize_base_url


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(min_length=1, max_length=160)
    reasoning_effort: ReasoningEffort = "default"
    api_key: SecretStr = Field(default=SecretStr(""), max_length=1024)
    version: int = Field(ge=0)

    @field_validator("name", "model")
    @classmethod
    def nonempty(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("invalid_text")
        return value

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        key = value.get_secret_value()
        if key and not re.fullmatch(r"[\x21-\x7e]+", key):
            raise ValueError("invalid_key")
        return value

    @field_validator("base_url")
    @classmethod
    def allowed_url(cls, value: str) -> str:
        return normalize_base_url(value)


class ModelDiscoveryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_url: str = Field(min_length=1, max_length=500)
    api_key: SecretStr = Field(default=SecretStr(""), max_length=1024)
    version: int = Field(ge=0)

    @field_validator("base_url")
    @classmethod
    def allowed_url(cls, value: str) -> str:
        return ConnectionInput.allowed_url(value)

    @field_validator("api_key")
    @classmethod
    def valid_key(cls, value: SecretStr) -> SecretStr:
        return ConnectionInput.valid_key(value)


class ConfigurationInput(ConnectionInput):
    call_mode: CallMode
    preference_version: int = Field(ge=0)
    activate: bool = False


class ActivationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_mode: CallMode
    version: int = Field(ge=1)
    preference_version: int = Field(ge=0)


class TestInput(ConnectionInput):
    call_mode: CallMode


class AISelectionInput(BaseModel):
    ai_version: int | None = Field(default=None, gt=0)
    ai_call_mode: CallMode | None = None
    ai_preference_version: int | None = Field(default=None, ge=0)
