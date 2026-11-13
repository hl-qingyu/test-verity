from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", check_fields=False)
    @classmethod
    def safe_text(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("invalid text")
        return value


class Revision(Input):
    revision: int = Field(ge=0)


class CategoryInput(Revision):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = Field(default=None, gt=0)

    @field_validator("name")
    @classmethod
    def name_valid(cls, value):
        if value in ("全部功能", "待归类", "未分类") or any(ord(c) < 32 for c in value):
            raise ValueError("reserved name")
        return value


class Move(Revision):
    category_id: int = Field(gt=0)
    parent_id: int = Field(gt=0)
    before_id: int | None = Field(default=None, gt=0)


class Assign(Revision):
    rule_id: int = Field(gt=0)
    category_id: int | None = Field(default=None, gt=0)


class DeleteCategory(Revision):
    confirmed: Literal[True]
    target_id: int | None = Field(default=None, gt=0)
    mode: Literal["MOVE", "UNCLASSIFIED", "DELETE"] = "MOVE"

    @model_validator(mode="after")
    def target_matches_mode(self):
        if self.mode != "MOVE" and self.target_id is not None:
            raise ValueError("target only allowed when moving")
        return self


class Source(Input):
    document_version_id: int = Field(gt=0)
    role: Literal["DOCUMENT", "PROTOTYPE"]
    location: str = Field(default="", max_length=1000)
    excerpt: str = Field(default="", max_length=10000)


class RuleInput(Revision):
    request_id: UUID
    category_id: int | None = Field(default=None, gt=0)
    title: str = Field(min_length=1, max_length=500)
    role: str = Field(default="", max_length=1000)
    preconditions: str = Field(default="", max_length=10000)
    action: str = Field(min_length=1, max_length=10000)
    expected: str = Field(min_length=1, max_length=10000)
    question: str = Field(default="", max_length=10000)
    resolution: str = Field(default="", max_length=10000)
    status: Literal["NEEDS_INFO", "REVIEW", "CONFIRMED"]
    sources: list[Source] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def review_ready(self):
        if self.status == "NEEDS_INFO" and not self.question:
            raise ValueError("question required")
        if self.status != "NEEDS_INFO" and self.question and not self.resolution:
            raise ValueError("unresolved question")
        if len({s.document_version_id for s in self.sources}) != len(self.sources):
            raise ValueError("duplicate source")
        return self
