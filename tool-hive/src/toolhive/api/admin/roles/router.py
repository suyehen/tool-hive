"""角色管理 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.deps import require_operation
from toolhive.api.admin.roles.schemas import (
    AssignOperationsRequest,
    CreateRoleRequest,
    OperationResponse,
    RoleAccountResponse,
    RoleListResponse,
    RoleResponse,
    RoleStatusRequest,
    UpdateRoleRequest,
)
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.role_service import RoleService

router = APIRouter(prefix="/roles", tags=["后台角色"])

_ops_router = APIRouter(prefix="/operations", tags=["管理操作项"])


# ── 角色 CRUD ──


@router.get("", response_model=RoleListResponse)
async def list_roles(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_VIEW)),
):
    """角色列表（需 role:view）。"""
    svc = RoleService(db)
    items, total = await svc.list_roles(offset=offset, limit=limit)
    return RoleListResponse(
        items=[
            RoleResponse(
                id=r.id, name=r.name, description=r.description,
                is_super_admin=r.is_super_admin, status=r.status,
                row_version=r.row_version,
                created_at=r.create_time,
                updated_at=r.update_time,
            )
            for r in items
        ],
        total=total,
    )


@router.post("", response_model=RoleResponse, status_code=201)
async def create_role(
    body: CreateRoleRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_CREATE)),
):
    """创建角色（需 role:create）。"""
    svc = RoleService(db)
    try:
        role = await svc.create_role(name=body.name, description=body.description)
    except ConflictError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RoleResponse(
        id=role.id, name=role.name, description=role.description,
        is_super_admin=role.is_super_admin, status=role.status,
        row_version=role.row_version,
        created_at=role.create_time,
        updated_at=role.update_time,
    )


@router.get("/{role_id}", response_model=RoleResponse)
async def get_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_VIEW)),
):
    """角色详情（需 role:view）。"""
    svc = RoleService(db)
    try:
        r = await svc.get_role(role_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return RoleResponse(
        id=r.id, name=r.name, description=r.description,
                is_super_admin=r.is_super_admin, status=r.status,
                row_version=r.row_version,
                created_at=r.create_time,
                updated_at=r.update_time,
    )


@router.patch("/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    body: UpdateRoleRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_EDIT)),
):
    """修改角色（需 role:edit）。"""
    svc = RoleService(db)
    try:
        r = await svc.update_role(
            role_id,
            name=body.name,
            description=body.description,
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RoleResponse(
        id=r.id, name=r.name, description=r.description,
        is_super_admin=r.is_super_admin, status=r.status,
        row_version=r.row_version,
        created_at=r.create_time,
        updated_at=r.update_time,
    )


@router.patch("/{role_id}/status")
async def update_role_status(
    role_id: str,
    body: RoleStatusRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_MANAGE)),
):
    """启用/停用/归档角色（需 role:manage）。"""
    svc = RoleService(db)
    try:
        await svc.update_role_status(role_id, body.status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "操作成功"}


# ── 操作项分配 ──


@router.get("/{role_id}/operations", response_model=list[OperationResponse])
async def get_role_operations(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_VIEW)),
):
    """查询角色的操作项（需 role:view）。"""
    svc = RoleService(db)
    try:
        ops = await svc.get_role_operations(role_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [
        OperationResponse(
            operation_code=o.operation_code,
            display_name=o.display_name,
            category=o.category,
            sort_order=o.sort_order,
            description=o.description,
            status=o.status,
        )
        for o in ops
    ]


@router.get("/{role_id}/accounts", response_model=list[RoleAccountResponse])
async def get_role_accounts(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_VIEW)),
):
    """查询分配了该角色的账号列表（需 role:view）。"""
    svc = RoleService(db)
    try:
        accounts = await svc.get_role_accounts(role_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [
        RoleAccountResponse(
            id=a.id,
            account=a.account,
            real_name=a.real_name,
            status=a.status,
        )
        for a in accounts
    ]


@router.post("/{role_id}/operations")
async def assign_operations(
    role_id: str,
    body: AssignOperationsRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_EDIT)),
):
    """分配操作项（需 role:edit）。"""
    svc = RoleService(db)
    try:
        await svc.assign_operations(role_id, body.operation_codes)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "操作成功"}


@router.delete("/{role_id}/operations")
async def remove_operations(
    role_id: str,
    body: AssignOperationsRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_EDIT)),
):
    """移除操作项（需 role:edit）。"""
    svc = RoleService(db)
    try:
        await svc.remove_operations(role_id, body.operation_codes)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "操作成功"}


# ── 操作项查询 ──


@_ops_router.get("", response_model=list[OperationResponse])
async def list_operations(
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.ROLE_VIEW)),
):
    """查询全部操作项定义（需 role:view）。"""
    from sqlalchemy import select

    from toolhive.models.management_operation import ManagementOperation

    result = await db.execute(
        select(ManagementOperation).order_by(ManagementOperation.operation_code)
    )
    ops = result.scalars().all()
    return [
        OperationResponse(
            operation_code=o.operation_code,
            display_name=o.display_name,
            category=o.category,
            sort_order=o.sort_order,
            description=o.description,
            status=o.status,
        )
        for o in ops
    ]
