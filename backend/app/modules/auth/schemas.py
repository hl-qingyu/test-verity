import re

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

LOGIN_NAME_PATTERN = r"[a-z0-9][a-z0-9_.-]{2,63}"


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_name: str = Field(min_length=3, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("login_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(LOGIN_NAME_PATTERN, value):
            raise ValueError("invalid_login_name")
        return value


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    login_name: str
    display_name: str
    platform_role: str
