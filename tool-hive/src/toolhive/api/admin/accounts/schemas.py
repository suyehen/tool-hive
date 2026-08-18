"""管理账号 API schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime


class CreateAccountRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    external_user_id: str | None = Field(None, max_length=256)


class CreateAccountResponse(BaseModel):
    id: str
    username: str
    status: str
    temp_password: str


class AccountResponse(BaseModel):
    id: str
    username: str
    external_user_id: str | None
    status: str
    login_failures: int
    must_change_password: bool
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class AccountListResponse(BaseModel):
    items: list[AccountResponse]
    total: int


class StatusUpdateRequest(BaseModel):
    action: str = Field(description="enable | disable | unlock")


class AssignRoleRequest(BaseModel):
    role_id: str = Field(min_length=1, max_length=32)


class ResetPasswordResponse(BaseModel):
    temp_password: str
