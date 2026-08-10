"""角色管理 API schemas。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateRoleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)


class UpdateRoleRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    description: str | None = Field(None, max_length=512)


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
    created_at: str
    updated_at: str | None


class RoleListResponse(BaseModel):
    items: list[RoleResponse]
    total: int


class OperationResponse(BaseModel):
    operation_code: str
    display_name: str
    description: str | None
    status: str


class AccountRoleRequest(BaseModel):
    account_id: str
    role_id: str
