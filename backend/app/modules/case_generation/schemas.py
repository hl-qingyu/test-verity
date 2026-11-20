from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.integrations.ai_client import CallMode
from app.modules.ai.terminal_schemas import TerminalInput as TerminalInput
from app.modules.ai.terminal_schemas import TerminalStart as TerminalStart
from app.modules.cases.schemas import DESIGN_FIELDS, CaseDesign


class Request(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", check_fields=False)
    @classmethod
    def no_nul(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("invalid text")
        return value


class MaterialSelection(Request):
    document_id: int = Field(gt=0)
    version: str = Field(min_length=1, max_length=200)
    before: str = Field(default="", max_length=200)
    update: Literal["", "完整替换", "增量补充"] = ""
    paths: list[str] = Field(default_factory=list)
    before_paths: list[str] = Field(default_factory=list)
    connection_id: int | None = Field(default=None, gt=0)
    baseline_run_id: int | None = Field(default=None, gt=0)


class Prepare(Request):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["INITIAL", "UPDATE"]
    scope: str = Field(min_length=1, max_length=2000)
    focus: str = Field(default="", max_length=10000)
    materials: list[MaterialSelection] = Field(min_length=1, max_length=100)
    case_ids: list[int] = Field(max_length=20000)
    case_versions: dict[str, int]
    case_scope: str = Field(max_length=2000)
    case_library_revision: int | None = Field(default=None, ge=0)
    full_scope: bool = True
    baseline_run_id: int | None = Field(default=None, gt=0)
    risk_report_ids: list[int] = Field(default_factory=list, max_length=100)


class Revision(Request):
    revision: int = Field(ge=1)


class Confirm(Revision):
    confirmed: Literal[True]
    ai_version: int | None = Field(default=None, gt=0)
    ai_call_mode: CallMode | None = None
    ai_preference_version: int | None = Field(default=None, ge=0)


class Retry(Request):
    request_id: UUID


class Handling(Revision):
    key: str = Field(min_length=1, max_length=200)
    draft: CaseDesign
    note: str = Field(default="", max_length=10000)
    ignored: bool = False
    evidence_checked: bool
    resolved: bool
    target_version: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, ge=0)
    edited_fields: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("edited_fields")
    @classmethod
    def valid_fields(cls, values):
        if len(set(values)) != len(values) or not set(values) <= set(DESIGN_FIELDS):
            raise ValueError("invalid fields")
        return values


class Decision(Revision):
    question_key: str = Field(min_length=1, max_length=200)
    conclusion: str = Field(min_length=1, max_length=10000)
    basis: str = Field(min_length=1, max_length=10000)
    affected: str = Field(min_length=1, max_length=2000)
    confirmed: Literal[True]


class CandidateResolution(Revision):
    request_id: UUID
    corrected_json: str = Field(default="", max_length=1_048_576)
    ignored: bool = False
    reason: str = Field(min_length=1, max_length=10000)
    confirmed: Literal[True]

    @field_validator("reason")
    @classmethod
    def nonempty_reason(cls, value):
        if not value.strip():
            raise ValueError("reason_required")
        return value.strip()


class Supplement(Revision):
    request_id: UUID
    decision_key: str = Field(min_length=1, max_length=200)


class ApplicationItem(Request):
    key: str = Field(min_length=1, max_length=200)
    draft_revision: int = Field(ge=0)
    action: Literal["apply", "reuse", "include", "ignore", "restore"] = "apply"
    target_id: int | None = Field(default=None, gt=0)
    target_version: int | None = Field(default=None, gt=0)
    reason: str = Field(default="", max_length=10000)
    category_mode: Literal["KEEP", "SET", "CLEAR"] = "KEEP"
    category_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def category_setting(self):
        if (self.category_mode == "SET") != (self.category_id is not None):
            raise ValueError("category ID required only when setting a category")
        return self


class Application(Request):
    request_id: UUID
    confirmed: Literal[True]
    items: list[ApplicationItem] = Field(min_length=1, max_length=20000)


class Preview(Request):
    keys: list[str] = Field(min_length=1, max_length=20000)


class Binding(Request):
    snapshot_ref: str = Field(min_length=1, max_length=200)
    document_id: int = Field(gt=0)
    version_id: int | None = Field(default=None, gt=0)


class Import(Request):
    title: str = Field(min_length=1, max_length=200)
    input_json: str
    report_json: str
    bindings: list[Binding] = Field(max_length=500)


class Chat(Request):
    cli_only: bool = False
    request_id: UUID
    function_key: str = Field(default="", max_length=200)
    finding_key: str = Field(default="", max_length=200)
    question: str = Field(min_length=1, max_length=10000)


class TerminalResultSave(Request):
    request_id: UUID
    confirmed: Literal[True]


class ChatDraft(Request):
    request_id: UUID
    design: CaseDesign
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    note: str = Field(min_length=1, max_length=10000)
    confirmed: Literal[True]
