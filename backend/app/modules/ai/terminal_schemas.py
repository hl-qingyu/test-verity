from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TerminalStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    resume: bool = True
    rows: int = Field(default=30, ge=8, le=120)
    cols: int = Field(default=110, ge=20, le=300)


class TerminalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["input", "resize"]
    data: str | None = Field(default=None, max_length=8192)
    rows: int | None = Field(default=None, ge=8, le=120)
    cols: int | None = Field(default=None, ge=20, le=300)

    @model_validator(mode="after")
    def correct_command(self):
        if self.type == "input" and (
            not self.data or "\x00" in self.data or self.rows is not None or self.cols is not None
        ):
            raise ValueError("invalid terminal input")
        if self.type == "resize" and (
            self.rows is None or self.cols is None or self.data is not None
        ):
            raise ValueError("invalid terminal dimensions")
        return self
