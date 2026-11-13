from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.ai.schemas import AISelectionInput
from app.modules.change_analysis.contract import Mode, Target
from app.modules.code_analysis.schemas import MaterialSelection, SourceSelection


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalFile(Request):
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=2_000_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LocalSnapshot(Request):
    ref: str = Field(min_length=1, max_length=200)
    captured_at: str = Field(min_length=1, max_length=100)
    scope: list[str] = Field(min_length=1)
    files: list[LocalFile]
    skipped: dict[str, str] = Field(default_factory=dict)


class PairSelection(Request):
    kind: Literal[
        "FILE",
        "DIRECTORY_PROTOTYPE",
        "GITHUB_CODE",
        "LOCAL_CODE",
        "GITHUB_PROTOTYPE",
        "LINK_PROTOTYPE",
    ]
    source_id: int = Field(gt=0)
    update_mode: Literal["FULL_REPLACEMENT", "INCREMENTAL_SUPPLEMENT", "CODE_SNAPSHOT"]
    source_version: int | None = Field(default=None, gt=0)
    connection_id: int | None = Field(default=None, gt=0)
    before_ref: str = Field(default="", max_length=200)
    after_ref: str = Field(default="", max_length=200)
    paths: list[str] = Field(default_factory=list)
    before_version_id: int | None = Field(default=None, gt=0)
    after_version_id: int | None = Field(default=None, gt=0)
    after_document_id: int | None = Field(default=None, gt=0)
    baseline_report_id: int | None = Field(default=None, gt=0)
    snapshot: str = Field(default="", max_length=64)
    url: str = Field(default="", max_length=8192)
    before_local: LocalSnapshot | None = None
    after_local: LocalSnapshot | None = None


class HistorySelection(Request):
    module: Literal["REQUIREMENT_ANALYSIS", "CODE_REVIEW"]
    report_id: int = Field(gt=0)
    item_key: str = Field(min_length=1, max_length=200)


class AnalysisRequest(Request, AISelectionInput):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    mode: Mode
    targets: list[Target] = Field(min_length=1, max_length=3)
    focus: str = Field(default="", max_length=10000)
    pairs: list[PairSelection] = Field(min_length=1, max_length=100)
    confirmed: bool
    materials: list[MaterialSelection] = Field(default_factory=list, max_length=100)
    sources: list[SourceSelection] = Field(default_factory=list, max_length=100)
    case_ids: list[int] = Field(default_factory=list, max_length=20000)
    case_versions: dict[str, int] = Field(default_factory=dict)
    historical_items: list[HistorySelection] = Field(default_factory=list, max_length=1000)

    @model_validator(mode="after")
    def valid_scope(self):
        allowed = (
            {"BUG", "REQUIREMENT_DEVIATION", "FRONTEND_BACKEND_MISMATCH"}
            if self.mode == "CODE_CHANGE"
            else {"BUSINESS_IMPACT", "IMPLEMENTATION_FOLLOWUP", "CASE_REGRESSION"}
        )
        if not set(self.targets) <= allowed or len(set(self.targets)) != len(self.targets):
            raise ValueError("invalid change targets")
        if any(c <= 0 for c in self.case_ids) or len(set(self.case_ids)) != len(self.case_ids):
            raise ValueError("invalid case scope")
        if self.case_versions and (
            set(self.case_versions) != {str(c) for c in self.case_ids}
            or any(v <= 0 for v in self.case_versions.values())
        ):
            raise ValueError("invalid case versions")
        return self


class Binding(Request):
    kind: Literal["GITHUB", "LOCAL"] | None = None
    snapshot_ref: str = Field(min_length=1, max_length=200)
    document_id: int | None = Field(default=None, gt=0)
    version_id: int | None = Field(default=None, gt=0)
    source_id: int | None = Field(default=None, gt=0)
    source_version: int | None = Field(default=None, gt=0)
    connection_id: int | None = Field(default=None, gt=0)


class ImportRequest(Request):
    title: str = Field(min_length=1, max_length=200)
    input_filename: str = Field(min_length=1, max_length=255)
    report_filename: str = Field(min_length=1, max_length=255)
    input_json: str
    report_json: str
    bindings: list[Binding] = Field(default_factory=list, max_length=500)


class RetryRequest(Request):
    request_id: UUID


class HandlingRequest(Request):
    revision: int = Field(ge=1)
    item_key: str = Field(min_length=1, max_length=200)
    status: Literal[
        "PENDING",
        "CONFIRMED",
        "RESOLVED",
        "FALSE_POSITIVE",
        "NEEDS_EVIDENCE",
        "ACCEPTED",
        "DEFERRED",
        "REJECTED",
    ]
    note: str = Field(default="", max_length=10000)


class ChatRequest(Request):
    request_id: UUID
    question: str = Field(min_length=1, max_length=10000)
    finding_key: str = Field(default="", max_length=200)
