from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.integrations.ai_client import CallMode
from app.modules.case_generation.schemas import MaterialSelection, Request
from app.modules.cases.schemas import CaseDesign, Search


class Prepare(Request):
    request_id: UUID
    title: str = Field(min_length=1, max_length=200)
    mode: Literal["COMPARE", "QUALITY"]
    materials: list[MaterialSelection] = Field(default_factory=list, max_length=100)
    search: Search = Field(default_factory=Search)
    case_ids: list[int] | None = Field(default=None, max_length=20000)
    case_versions: dict[str, int] | None = None
    library_revision: int | None = Field(default=None, ge=0)
    zero_confirmed: bool = False
    focus: str = Field(default="", max_length=10000)
    parent_id: int | None = Field(default=None, gt=0)


class Confirm(Request):
    revision: int = Field(ge=1)
    confirmed: Literal[True]
    ai_version: int | None = Field(default=None, gt=0)
    ai_call_mode: CallMode | None = None
    ai_preference_version: int | None = Field(default=None, ge=0)


class Handling(Request):
    revision: int = Field(ge=1)
    key: str = Field(min_length=1, max_length=200)
    state: Literal["待确认", "已确认待处理", "已解决", "不适用"] = "待确认"
    comment: str = Field(default="", max_length=10000)
    draft: CaseDesign | None = None
    category_id: int | None = Field(default=None, ge=0)
    evidence_checked: bool = False
    target_version: int | None = Field(default=None, gt=0)


class ApplyItem(Request):
    key: str = Field(min_length=1, max_length=200)
    draft_revision: int = Field(ge=1)
    action: Literal["apply", "reuse", "include"] = "apply"
    target_id: int | None = Field(default=None, gt=0)
    target_version: int | None = Field(default=None, gt=0)
    category_id: int | None = Field(default=None, ge=0)
    reason: str = Field(default="", max_length=2000)


class Application(Request):
    request_id: UUID
    confirmed: Literal[True]
    items: list[ApplyItem] = Field(min_length=1, max_length=20000)


class Chat(Request):
    request_id: UUID
    question: str = Field(min_length=1, max_length=10000)
    finding_key: str = Field(default="", max_length=200)
    function_key: str = Field(default="", max_length=200)


class Quote(Request):
    source: str = Field(min_length=1, max_length=200)
    quote: str = Field(default="", max_length=1000)
    observation: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def one_evidence(self):
        if bool(self.quote.strip()) == bool(self.observation.strip()):
            raise ValueError("provide original quote or attachment observation")
        return self


class Finding(Request):
    key: str = Field(min_length=1, max_length=200)
    kind: Literal["MISMATCH", "MISSING", "QUALITY", "SETUP", "QUESTION"]
    title: str = Field(min_length=1, max_length=500)
    severity: Literal["高", "中", "低"]
    reason: str = Field(min_length=1, max_length=2000)
    description: str = Field(min_length=1, max_length=10000)
    impact: str = Field(default="", max_length=5000)
    suggestion: str = Field(min_length=1, max_length=10000)
    case_ids: list[int] = Field(default_factory=list, max_length=20000)
    fields: list[str] = Field(default_factory=list, max_length=12)
    evidence: list[Quote] = Field(default_factory=list, max_length=5)


class Report(Request):
    findings: list[Finding] = Field(max_length=20000)
    notes: list[Finding] = Field(max_length=20000)
    checked_case_ids: list[int] = Field(max_length=20000)
    complete: bool


class Import(Request):
    input: dict
    report: dict


class FromChat(Request):
    revision: int = Field(ge=1)
    turn_id: int = Field(gt=0)
    finding: Finding
