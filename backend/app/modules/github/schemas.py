import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

Owner = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")]


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: int | None = Field(default=None, gt=0)
    version: int = Field(default=0, ge=0)
    name: str = Field(min_length=1, max_length=80)
    # Legacy clients may still submit an owner filter; new clients discover all owners.
    kind: Literal["personal", "organization"] | None = None
    resource_owner: Owner | None = None
    token_type: Literal["classic", "fine_grained"] | None = None
    api_url: Literal["https://api.github.com"] = "https://api.github.com"
    token: SecretStr = Field(default=SecretStr(""), max_length=512)

    @model_validator(mode="after")
    def paired_legacy_filter(self):
        if (self.kind is None) != (self.resource_owner is None):
            raise ValueError("incomplete_owner_filter")
        return self

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 for char in value):
            raise ValueError("invalid_name")
        return value.strip()

    @field_validator("token")
    @classmethod
    def personal_access_token(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() and not re.fullmatch(
            r"(?:github_pat_[A-Za-z0-9_]{20,500}|ghp_[A-Za-z0-9]{20,255}|[A-Fa-f0-9]{40})",
            value.get_secret_value(),
        ):
            raise ValueError("personal_access_token_required")
        return value


class ProbeInput(ConnectionInput):
    page: int = Field(default=1, ge=1, le=1000)


class SaveInput(ConnectionInput):
    repository_ids: list[Annotated[int, Field(gt=0)]] = Field(min_length=1, max_length=20)
    receipts: list[Annotated[str, Field(max_length=4096)]] = Field(min_length=1, max_length=20)


class DeleteConnectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)
    confirmed: Literal[True]
