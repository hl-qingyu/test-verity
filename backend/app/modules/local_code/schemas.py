from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SourceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: UUID
    name: str = Field(min_length=1, max_length=80)
    directory_name: str = Field(min_length=1, max_length=255)
    kind: Literal["BACKEND", "FLUTTER", "WEB", "PROTOTYPE", "OTHER"]
    version: int = Field(default=0, ge=0)

    @field_validator("name", "directory_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        value = value.strip()
        if not value or value in (".", "..") or any(ord(c) < 32 or c in "/\\:" for c in value):
            raise ValueError("invalid_name")
        return value


class SourceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    owner_id: int
    client_id: str
    name: str
    directory_name: str
    kind: str
    version: int
    created_at: datetime
    updated_at: datetime
