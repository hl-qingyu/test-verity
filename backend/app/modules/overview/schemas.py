from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Module = Literal["requirements", "generate", "coverage", "code", "changes"]
RecentFilter = Literal["all", "running", "completed", "failed"]


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: RecentFilter = "all"


class AttentionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module: Module
    group: str = Field(max_length=30)
    state: str = Field(max_length=30)
    page: int = Field(default=1, ge=1)
