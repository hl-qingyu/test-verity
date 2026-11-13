from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.integrations.github import valid_branch_name


class DeleteRepositoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)
    confirmed: Literal[True]


class DeleteProjectInput(DeleteRepositoryInput):
    pass


class GitVersionsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: int = Field(gt=0)
    kind: Literal["branches", "tags", "commits"] = "branches"
    ref: str = Field(default="", max_length=255)
    page: int = Field(default=1, ge=1, le=1000)

    @field_validator("ref")
    @classmethod
    def valid_ref(cls, value: str) -> str:
        if value and not valid_branch_name(value):
            raise ValueError("invalid_ref")
        return value


class ProjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    identifier: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,59}$")
    description: str = Field(default="", max_length=2000)
    owner_id: int = Field(gt=0)
    version: int = Field(default=0, ge=0)

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_name")
        return value.strip()


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: int = Field(gt=0)
    version: int = Field(gt=0)


class RepositoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    association_id: int | None = Field(default=None, gt=0)
    connection_id: int = Field(gt=0)
    github_id: int = Field(gt=0)
    kind: Literal["BACKEND", "FLUTTER", "WEB", "PROTOTYPE", "OTHER"]
    default_branch: str = Field(min_length=1, max_length=255)
    version: int = Field(default=0, ge=0)

    @field_validator("default_branch")
    @classmethod
    def valid_branch(cls, value: str) -> str:
        if not valid_branch_name(value):
            raise ValueError("invalid_branch")
        return value
