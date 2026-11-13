from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

COLUMNS = [
    ("serial", "序号"),
    ("number", "用例编号"),
    ("module", "功能模块"),
    ("structure", "功能结构"),
    ("case_type", "用例类型"),
    ("priority", "优先级"),
    ("description", "用例描述"),
    ("title", "验证用例子项"),
    ("preconditions", "前置条件"),
    ("steps", "操作步骤"),
    ("expected", "预期结果"),
    ("result", "测试结果"),
    ("tester", "测试人员"),
    ("remark", "备注"),
]
PRIORITIES = ["", "P0", "P1", "P2", "P3", "P4"]
RESULTS = ["", "未测", "通过", "失败", "阻塞", "跳过", "废弃"]
DESIGN_FIELDS = [
    "module",
    "structure",
    "case_type",
    "priority",
    "description",
    "title",
    "preconditions",
    "steps",
    "expected",
    "remark",
    "data_requirements",
    "cleanup",
]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", check_fields=False)
    @classmethod
    def no_nul(cls, value):
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("NUL is not valid text")
        return value


class Revision(Input):
    revision: int = Field(ge=0)


class CategoryInput(Revision):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def valid_name(cls, name: str) -> str:
        name = name.strip()
        if not name or name in ("未分类", "全部分类") or any(ord(c) < 32 for c in name):
            raise ValueError("invalid name")
        return name


class DeleteCategory(Revision):
    target_id: int | None = Field(default=None, gt=0)
    confirmed: Literal[True]


class AssignCategory(Revision):
    case_ids: list[int] = Field(min_length=1, max_length=2000)
    category_id: int | None = Field(default=None, gt=0)


class CaseDesign(Input):
    module: str = Field(default="", max_length=500)
    structure: str = Field(default="", max_length=1000)
    case_type: str = Field(default="", max_length=200)
    priority: str = ""
    description: str = Field(default="", max_length=4000)
    title: str = Field(default="", max_length=4000)
    preconditions: str = Field(default="", max_length=30000)
    steps: str = Field(default="", max_length=30000)
    expected: str = Field(default="", max_length=30000)
    remark: str = Field(default="", max_length=10000)
    data_requirements: str = Field(default="", max_length=10000)
    cleanup: str = Field(default="", max_length=10000)

    @field_validator("priority")
    @classmethod
    def enum_value(cls, value: str) -> str:
        value = value.strip().upper()
        if value not in PRIORITIES:
            raise ValueError("invalid enum")
        return value


class CaseValues(CaseDesign):
    category_id: int | None = Field(default=None, gt=0)
    result: str = ""
    tester: str = Field(default="", max_length=200)
    review_status: Literal["待审核", "已审核"] = "待审核"

    @field_validator("result")
    @classmethod
    def valid_result(cls, value: str) -> str:
        value = value.strip()
        if value not in RESULTS:
            raise ValueError("invalid result")
        return value


class CaseInput(CaseValues, Revision):
    request_id: UUID


class CasePatch(Input):
    id: int = Field(gt=0)
    changes: CaseValues


class DeleteCase(Revision):
    confirmed: Literal[True]


class LifecycleInput(Revision):
    confirmed: Literal[True]
    lifecycle: Literal["ACTIVE", "RETIRED"]
    reason: str = Field(min_length=1, max_length=10000)


class SearchCondition(Input):
    field: str
    operator: Literal["contains", "equals", "notContains"] = "contains"
    value: str = Field(default="", max_length=1000)

    @field_validator("field")
    @classmethod
    def valid_field(cls, value: str) -> str:
        if value not in dict(COLUMNS):
            raise ValueError("invalid field")
        return value


class Search(Input):
    lifecycle: Literal["ACTIVE", "RETIRED", "ALL"] = "ACTIVE"
    page: int = Field(default=1, ge=1)
    page_size: Literal[10, 20, 50, 100] = 10
    category_id: int | None = Field(default=None, ge=0)
    conditions: list[SearchCondition] = Field(default_factory=list, max_length=20)


class EditScope(Search):
    case_ids: list[PositiveInt] | None = Field(default=None, min_length=1, max_length=20000)

    @field_validator("case_ids")
    @classmethod
    def unique_ids(cls, value):
        if value is not None and len(set(value)) != len(value):
            raise ValueError("duplicate IDs")
        return value


class BatchEdit(Revision):
    confirmed: Literal[True]
    mode: Literal["rows", "uniform"]
    search: EditScope
    rows: list[CasePatch] = Field(default_factory=list, max_length=20000)
    changes: CaseValues | None = None

    @model_validator(mode="after")
    def valid_mode(self):
        if self.mode == "rows":
            if not self.rows or self.changes is not None:
                raise ValueError("rows required")
            if len({r.id for r in self.rows}) != len(self.rows):
                raise ValueError("duplicate IDs")
            if any(not r.changes.model_fields_set for r in self.rows):
                raise ValueError("empty changes")
        elif self.rows or self.changes is None or not self.changes.model_fields_set:
            raise ValueError("uniform changes required")
        return self


class ImportUpload(Input):
    filename: str = Field(min_length=1, max_length=240)
    request_id: UUID

    @field_validator("filename")
    @classmethod
    def valid_filename(cls, value: str) -> str:
        if any(c in value for c in "/\\") or any(ord(c) < 32 for c in value):
            raise ValueError("invalid filename")
        return value


class ImportReview(Input):
    category_id: int | None = Field(default=None, gt=0)
    preview_revision: int = Field(ge=0)


class ImportConfirm(Revision):
    preview_revision: int = Field(gt=0)
    duplicate_decisions: dict[str, Literal["skip", "include"]] = Field(
        default_factory=dict, max_length=20000
    )
