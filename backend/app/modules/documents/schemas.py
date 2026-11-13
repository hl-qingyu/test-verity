from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RevisionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=0)


class GroupInput(RevisionInput):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        value = value.strip()
        if not value or value == "未分组" or any(ord(c) < 32 for c in value):
            raise ValueError("invalid group name")
        return value


class UploadInput(RevisionInput):
    filename: str = Field(min_length=1, max_length=240)
    group_id: int | None = Field(default=None, gt=0)
    document_id: int | None = Field(default=None, gt=0)
    upload_id: UUID

    @field_validator("filename")
    @classmethod
    def filename_valid(cls, value: str) -> str:
        if value != value.strip() or any(c in value for c in "/\\\x00\r\n"):
            raise ValueError("invalid filename")
        if any(ord(c) < 32 for c in value):
            raise ValueError("invalid filename")
        return value


class MoveInput(RevisionInput):
    document_ids: list[int] = Field(min_length=1, max_length=500)
    group_id: int | None = Field(default=None, gt=0)


class ReorderInput(RevisionInput):
    document_id: int = Field(gt=0)
    direction: int = Field(ge=-1, le=1)


class LinkBindingInput(RevisionInput):
    href: str = Field(min_length=1, max_length=8192)
    target_version_id: int = Field(gt=0)


class DeleteInput(RevisionInput):
    confirmed: Literal[True]
