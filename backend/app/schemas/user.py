import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

UserRole = Literal["operator", "reviewer", "admin"]
UserStatus = Literal["invited", "active", "disabled"]


class UserInvite(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=200)
    role: UserRole = "operator"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        email = value.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise ValueError("Enter a valid email address")
        return email


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    role: UserRole | None = None
    status: UserStatus | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    role: UserRole
    status: UserStatus
    last_login_at: datetime | None
    created_at: datetime


class UserList(BaseModel):
    items: list[UserRead]
