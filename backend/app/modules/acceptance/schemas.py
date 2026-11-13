from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Module = Literal["requirements", "generate", "coverage", "code", "changes"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Judgment(Input):
    verdict: Literal["UNREVIEWED", "VALID", "INVALID", "DISMISSED", "NEEDS_REVIEW"] = "UNREVIEWED"
    reason: Literal["", "FALSE_POSITIVE", "UNSUPPORTED", "DUPLICATE", "OUT_OF_SCOPE", "OTHER"] = ""
    evidence: Literal["UNREVIEWED", "SUFFICIENT", "INSUFFICIENT"] = "UNREVIEWED"
    usable: bool | None = None
    note: str = Field(default="", max_length=3000)


class Criterion(Input):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    basis: str = Field(min_length=1, max_length=3000)
    critical: bool = True
    baseline: bool = False
    result: Literal["UNREVIEWED", "COVERED", "MISSING"] = "UNREVIEWED"
    matched_key: str = Field(default="", max_length=500)
    scope_confirmed: Literal[True]


class State(Input):
    items: dict[str, Judgment] = Field(default_factory=dict, max_length=20000)
    criteria: list[Criterion] = Field(default_factory=list, max_length=2000)
    scope_reviewed: bool = False
    conclusion: Literal["UNREVIEWED", "ACCEPTED", "NEEDS_REVIEW", "REJECTED"] = "UNREVIEWED"
    note: str = Field(default="", max_length=3000)


class Save(Input):
    revision: int = Field(ge=0)
    source_token: str = Field(min_length=1, max_length=64)
    state: State
