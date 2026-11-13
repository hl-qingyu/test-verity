from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Save(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    expected_token: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    body: Annotated[str, Field(min_length=1, max_length=200000)]


class Chat(Save):
    question: Annotated[str, Field(min_length=1, max_length=4000)]
    references: list[Annotated[str, Field(pattern=r"^[0-9a-f]{24}$")]] = []
    last_turn_id: Annotated[int, Field(ge=0)] = 0
    include_history: bool = True
