from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.ai.schemas import AISelectionInput
from app.modules.code_analysis.contract import SourceKind, Target, safe_path


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SelectedFile(Request):
    path: str = Field(min_length=1, max_length=512)
    content: str | None = Field(default=None, max_length=2_000_000)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def valid_path(cls, value):
        if not safe_path(value):
            raise ValueError("excluded code path")
        return value


class SourceSelection(Request):
    kind: SourceKind
    source_id: int = Field(gt=0)
    connection_id: int | None = Field(default=None, gt=0)
    commit: str = Field(default="", max_length=40)
    source_version: int = Field(gt=0)
    files: list[SelectedFile] = Field(min_length=1)


class MaterialSelection(Request):
    document_id: int = Field(gt=0)
    version_id: int | None = Field(default=None, gt=0)
    commit: str = Field(default="", max_length=40)
    paths: list[str] = Field(default_factory=list)
    snapshot: str = Field(default="", pattern=r"^$|^[0-9a-f]{64}$")
    url: str = Field(default="", max_length=8192)


class CodeAnalysisRequest(Request, AISelectionInput):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    focus: str = Field(default="", max_length=10000)
    targets: list[Target] = Field(min_length=1, max_length=3)
    sources: list[SourceSelection] = Field(min_length=1, max_length=100)
    materials: list[MaterialSelection] = Field(default_factory=list, max_length=100)


class ImportBinding(Request):
    source_id: str = Field(min_length=1, max_length=200)
    document_id: int = Field(gt=0)
    version_id: int | None = Field(default=None, gt=0)


class ImportRequest(Request):
    title: str = Field(min_length=1, max_length=200)
    input_filename: str = Field(min_length=1, max_length=255)
    report_filename: str = Field(min_length=1, max_length=255)
    input_json: str
    report_json: str
    bindings: list[ImportBinding] = Field(default_factory=list, max_length=1000)


class RetryRequest(Request):
    request_id: UUID


class HandlingRequest(Request):
    revision: int = Field(ge=1)
    finding_key: str = Field(min_length=1, max_length=200)
    status: Literal["PENDING", "CONFIRMED", "RESOLVED", "FALSE_POSITIVE", "NEEDS_EVIDENCE"]
    note: str = Field(default="", max_length=10000)


class ChatRequest(Request):
    request_id: UUID
    question: str = Field(min_length=1, max_length=10000)
    finding_key: str = Field(default="", max_length=200)
