from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.github import valid_branch_name, valid_material_path
from app.modules.documents.schemas import RevisionInput, UploadInput


class GitScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: int = Field(gt=0)
    repository_id: int = Field(gt=0)
    branch: str = Field(min_length=1, max_length=255)
    path: str = Field(default="", max_length=500)
    comparison: bool = False

    @field_validator("branch")
    @classmethod
    def branch_valid(cls, value: str) -> str:
        if not valid_branch_name(value):
            raise ValueError("invalid branch")
        return value

    @field_validator("path")
    @classmethod
    def path_valid(cls, value: str) -> str:
        value = value.strip()
        if value and not valid_material_path(value):
            raise ValueError("invalid path")
        return value


class CheckInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connection_id: int = Field(gt=0)


class LiveInput(RevisionInput):
    kind: Literal["GITHUB", "LINK"]
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    group_id: int | None = Field(default=None, gt=0)
    url: str | None = Field(default=None, max_length=8192)
    git: GitScope | None = None
    selected_paths: list[str] = Field(default_factory=list)
    commit: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")

    @field_validator("name")
    @classmethod
    def name_valid(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError("invalid name")
        return value

    @model_validator(mode="after")
    def source_valid(self):
        if self.kind == "LINK":
            try:
                parsed = urlsplit(self.url or "")
                if (
                    parsed.scheme not in {"https", "http"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                ):
                    raise ValueError("invalid URL")
                _ = parsed.port
                if any(ord(c) <= 32 or c == "\\" for c in self.url or ""):
                    raise ValueError("invalid URL")
            except ValueError:
                raise ValueError("invalid URL") from None
            if self.git or self.selected_paths or self.commit:
                raise ValueError("unexpected GitHub configuration")
        elif (
            self.git is None
            or self.url is not None
            or not self.commit
            or not self.selected_paths
            or len(set(self.selected_paths)) != len(self.selected_paths)
            or any(not valid_material_path(p) for p in self.selected_paths)
        ):
            raise ValueError("invalid GitHub configuration")
        return self


class ImageUpload(UploadInput):
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=2000)
