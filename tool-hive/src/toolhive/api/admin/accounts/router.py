"""管理账号 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.accounts.schemas import (
    AccountListResponse,
    AccountResponse,
    AssignRoleRequest,
    CreateAccountRequest,
    CreateAccountResponse,
    ResetPasswordResponse,
    StatusUpdateRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.api.admin.roles.schemas import RoleResponse
from toolhive.api.deps import get_admin_security
from toolhive.config import AdminSecuritySettings
from toolhive.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.account_service import AccountService
from toolhive.services.role_service import RoleService

router = APIRouter(prefix="/accounts", tags=["管理账号"])


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    _account=Depends(require_operation(OperationCode.ADMIN_ACCOUNT_VIEW)),
):
    """账号列表（需 admin_account:view）。"""
    svc = AccountService(db, admin_security)
    items, total = await svc.list_accounts(offset=offset, limit=limit)
    return AccountListResponse(
        items=[
            AccountResponse(
                id=a.id,
                username=a.username,
                external_user_id=a.external_user_id,
                status=a.status,
                login_failures=a.login_failures,
                must_change_password=a.must_change_password,
                row_version=a.row_version,
                created_at=a.create_time,
                updated_at=a.update_time,
            )
            for a in items
        ],
        total=total,
    )


@router.post("", response_model=CreateAccountResponse, status_code=201)
async def create_account(
    body: CreateAccountRequest,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    _account=Depends(require_operation(OperationCode.ADMIN_ACCOUNT_CREATE)),
):
    """创建账号（需 admin_account:create）。"""
    svc = AccountService(db, admin_security)
    try:
        account, temp_pwd = await svc.create_account(
            username=body.username,
            external_user_id=body.external_user_id,
        )
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return CreateAccountResponse(
        id=account.id,
        username=account.username,
        status=account.status,
        temp_password=temp_pwd,
    )


@router.get("/{account_id}", response_model=AccountResponse)
async def get_account(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    _account=Depends(require_operation(OperationCode.ADMIN_ACCOUNT_VIEW)),
):
    """账号详情（需 admin_account:view）。"""
    svc = AccountService(db, admin_security)
    try:
        a = await svc.get_by_id(account_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return AccountResponse(
        id=a.id,
        username=a.username,
        external_user_id=a.external_user_id,
        status=a.status,
        login_failures=a.login_failures,
        must_change_password=a.must_change_password,
        row_version=a.row_version,
        created_at=a.create_time,
        updated_at=a.update_time,
    )


@router.patch("/{account_id}/status")
async def update_account_status(
    account_id: str,
    body: StatusUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    operator=Depends(require_operation(OperationCode.ADMIN_ACCOUNT_MANAGE)),
):
    """启用/禁用/解锁（需 admin_account:manage）。"""
    svc = AccountService(db, admin_security)
    try:
        target = await svc.get_by_id(account_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        if body.action == "enable":
            await svc.enable_account(target)
        elif body.action == "disable":
            await svc.disable_account(target, operator_id=operator.id)
        elif body.action == "unlock":
            await svc.unlock_account(target)
        else:
            raise HTTPException(status_code=400, detail=f"无效操作: {body.action}")
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"detail": "操作成功"}


@router.post("/{account_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    _account=Depends(require_operation(OperationCode.ADMIN_ACCOUNT_MANAGE)),
):
    """重置密码（需 admin_account:manage）。"""
    svc = AccountService(db, admin_security)
    try:
        target = await svc.get_by_id(account_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    try:
        temp_pwd = await svc.reset_password(target)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return ResetPasswordResponse(temp_password=temp_pwd)


@router.post("/{account_id}/force-logout")
async def force_logout(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    admin_security: AdminSecuritySettings = Depends(get_admin_security),
    _account=Depends(require_operation(OperationCode.ADMIN_ACCOUNT_MANAGE)),
):
    """强制下线（需 admin_account:manage）。"""
    svc = AccountService(db, admin_security)
    try:
        target = await svc.get_by_id(account_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    await svc.force_logout(target)
    return {"detail": "已强制下线"}


@router.get("/{account_id}/roles", response_model=list[RoleResponse])
async def get_account_roles(
    account_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_VIEW)),
):
    """查询账号已分配的后台角色（需 role:view）。"""
    svc = RoleService(db)
    roles = await svc.get_account_roles(account_id)
    return [
        RoleResponse(
            id=r.id,
            name=r.name,
            description=r.description,
            is_super_admin=r.is_super_admin,
            status=r.status,
            row_version=r.row_version,
            created_at=r.create_time,
            updated_at=r.update_time,
        )
        for r in roles
    ]


@router.post("/{account_id}/roles")
async def assign_role_to_account(
    account_id: str,
    body: AssignRoleRequest,
    db: AsyncSession = Depends(get_db),
    operator=Depends(require_operation(OperationCode.ROLE_ASSIGN)),
):
    """给账号分配后台角色（需 role:assign）。"""
    svc = RoleService(db)
    try:
        await svc.assign_role_to_account(
            account_id, role_id=body.role_id, operator_id=operator.id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已分配"}


@router.delete("/{account_id}/roles/{role_id}")
async def remove_role_from_account(
    account_id: str,
    role_id: str,
    db: AsyncSession = Depends(get_db),
    operator=Depends(require_operation(OperationCode.ROLE_ASSIGN)),
):
    """从账号移除后台角色（需 role:assign）。"""
    svc = RoleService(db)
    try:
        await svc.remove_role_from_account(
            account_id, role_id=role_id, operator_id=operator.id,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已移除"}
