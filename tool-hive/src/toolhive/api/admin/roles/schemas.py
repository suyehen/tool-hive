"""角色管理 API schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from toolhive.core.time_utils import UTCDateTime


class CreateRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)
    row_version: int | None = Field(None, ge=0, description="乐观锁版本号，可选")


class RoleStatusRequest(BaseModel):
    status: str = Field(description="active | disabled | archived")


class AssignOperationsRequest(BaseModel):
    operation_codes: list[str] = Field(min_length=1)


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str | None
    is_super_admin: bool
    status: str
    row_version: int
    created_at: UTCDateTime
    updated_at: UTCDateTime | None


class RoleListResponse(BaseModel):
    items: list[RoleResponse]
    total: int


class OperationResponse(BaseModel):
    operation_code: str
    display_name: str
    description: str | None
    status: str


class RoleAccountResponse(BaseModel):
    id: str
    account: str
    real_name: str
    status: str


class AccountRoleRequest(BaseModel):
    account_id: str
    role_id: str
