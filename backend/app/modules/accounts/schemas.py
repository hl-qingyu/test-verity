from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from app.modules.auth.schemas import LoginInput, UserView


class UserFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login_name: str = Field(min_length=3, max_length=64)
    display_name: str = Field(min_length=1, max_length=80)
    platform_role: Literal["ADMIN", "TEST", "DEV", "PRODUCT", "MANAGER", "USER"] = "TEST"
    status: Literal["ACTIVE", "DISABLED"] = "ACTIVE"

    @field_validator("login_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return LoginInput.normalize_name(value)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_display_name")
        return value.strip()


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=8, max_length=128)
    confirm_password: SecretStr = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def matching_passwords(self) -> "PasswordInput":
        value = self.password.get_secret_value()
        if value.isspace() or value != self.confirm_password.get_secret_value():
            raise ValueError("password_mismatch")
        value.encode("utf-8")
        return self


class UserCreate(UserFields, PasswordInput):
    pass


class UserUpdate(UserFields):
    updated_at: datetime


class AccountView(UserView):
    status: str
    created_at: datetime
    updated_at: datetime


class AccountPage(BaseModel):
    items: list[AccountView]
    total: int
