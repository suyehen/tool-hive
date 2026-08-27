"""Catalog 能力包管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.caller_systems.schemas import CallerSystemResponse
from toolhive.api.admin.catalog.schemas import (
    CapabilityPackListResponse,
    CapabilityPackResponse,
    CreateCapabilityPackRequest,
    ReplaceSystemsRequest,
    ReplaceToolsRequest,
    StatusCommentRequest,
    ToolResponse,
    UpdateCapabilityPackRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.catalog_capability_service import CatalogCapabilityService

router = APIRouter(prefix="/capability-packs", tags=["Catalog-CapabilityPacks"])


def _to_response(pack) -> CapabilityPackResponse:
    """能力包 ORM → 响应对象。"""
    return CapabilityPackResponse(
        id=pack.id,
        pack_code=pack.pack_code,
        name=pack.name,
        description=pack.description,
        status=pack.status,
        row_version=pack.row_version,
        created_at=pack.create_time,
        updated_at=pack.update_time,
    )


def _to_tool_response(tool) -> ToolResponse:
    """工具 ORM → 响应对象。"""
    return ToolResponse(
        id=tool.id,
        namespace=tool.namespace,
        tool_code=tool.tool_code,
        full_code=tool.full_code,
        name=tool.name,
        description=tool.description,
        risk_level=tool.risk_level,
        discoverable=tool.discoverable,
        executable=tool.executable,
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        status=tool.status,
        default_version_id=tool.default_version_id,
        row_version=tool.row_version,
        created_at=tool.create_time,
        updated_at=tool.update_time,
    )


def _to_system_response(system) -> CallerSystemResponse:
    """调用系统 ORM → 响应对象。"""
    return CallerSystemResponse(
        id=system.id,
        system_id=system.system_id,
        name=system.name,
        description=system.description,
        environment=system.environment,
        belonging_party=system.belonging_party,
        code=system.code,
        owner=system.owner,
        contact=system.contact,
        owner_email=system.owner_email,
        tags=system.get_tags(),
        status=system.status,
        effective_state=system.effective_state,
        effective_from=system.effective_from,
        effective_to=system.effective_to,
        deactivated_reason=system.deactivated_reason,
        emergency_disabled=system.emergency_disabled,
        emergency_disabled_reason=system.emergency_disabled_reason,
        emergency_disabled_at=system.emergency_disabled_at,
        row_version=system.row_version,
        created_at=system.create_time,
        updated_at=system.update_time,
    )


@router.get("", response_model=CapabilityPackListResponse)
async def list_capability_packs(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_VIEW)),
):
    """分页查询能力包。"""
    svc = CatalogCapabilityService(db)
    items, total = await svc.list_packs(
        offset=offset, limit=limit, keyword=keyword, status=status,
    )
    return CapabilityPackListResponse(
        items=[_to_response(p) for p in items], total=total,
    )


@router.post("", response_model=CapabilityPackResponse, status_code=201)
async def create_capability_pack(
    body: CreateCapabilityPackRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_CREATE)),
):
    """创建能力包。"""
    svc = CatalogCapabilityService(db)
    try:
        pack = await svc.create_pack(
            pack_code=body.pack_code, name=body.name, description=body.description,
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(pack)


@router.get("/{pack_id}", response_model=CapabilityPackResponse)
async def get_capability_pack(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_VIEW)),
):
    """查询能力包详情。"""
    svc = CatalogCapabilityService(db)
    try:
        pack = await svc.get_pack(pack_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(pack)


@router.patch("/{pack_id}", response_model=CapabilityPackResponse)
async def update_capability_pack(
    pack_id: str,
    body: UpdateCapabilityPackRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_EDIT)),
):
    """更新能力包资料。"""
    svc = CatalogCapabilityService(db)
    try:
        pack = await svc.update_pack(
            pack_id, name=body.name, description=body.description,
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(pack)


@router.post("/{pack_id}/enable", response_model=CapabilityPackResponse)
async def enable_capability_pack(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_MANAGE)),
):
    """启用能力包。"""
    return await _set_status(pack_id, "enabled", db)


@router.post("/{pack_id}/disable", response_model=CapabilityPackResponse)
async def disable_capability_pack(
    pack_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_MANAGE)),
):
    """停用能力包。"""
    return await _set_status(pack_id, "disabled", db)


@router.post("/{pack_id}/archive", response_model=CapabilityPackResponse)
async def archive_capability_pack(
    pack_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_MANAGE)),
):
    """归档能力包（终态，不可恢复）。"""
    return await _set_status(pack_id, "archived", db)


async def _set_status(
    pack_id: str, status: str, db: AsyncSession,
) -> CapabilityPackResponse:
    """执行能力包状态变更并统一错误映射。"""
    svc = CatalogCapabilityService(db)
    try:
        pack = await svc.set_status(pack_id, status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(pack)


# ── 工具关联 ──


@router.get("/{pack_id}/tools", response_model=list[ToolResponse])
async def list_pack_tools(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_VIEW)),
):
    """查询能力包关联的工具。"""
    svc = CatalogCapabilityService(db)
    try:
        tools = await svc.list_pack_tools(pack_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [_to_tool_response(t) for t in tools]


@router.put("/{pack_id}/tools", response_model=list[ToolResponse])
async def replace_pack_tools(
    pack_id: str,
    body: ReplaceToolsRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_EDIT)),
):
    """全量替换能力包的工具关联。"""
    svc = CatalogCapabilityService(db)
    try:
        tools = await svc.replace_pack_tools(pack_id, body.tool_ids)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_to_tool_response(t) for t in tools]


# ── 调用系统授权关联 ──


@router.get("/{pack_id}/systems", response_model=list[CallerSystemResponse])
async def list_pack_systems(
    pack_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_VIEW)),
):
    """查询能力包授权的调用系统。"""
    svc = CatalogCapabilityService(db)
    try:
        systems = await svc.list_pack_systems(pack_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return [_to_system_response(s) for s in systems]


@router.put("/{pack_id}/systems", response_model=list[CallerSystemResponse])
async def replace_pack_systems(
    pack_id: str,
    body: ReplaceSystemsRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.CAPABILITY_EDIT)),
):
    """全量替换能力包的调用系统授权。"""
    svc = CatalogCapabilityService(db)
    try:
        systems = await svc.replace_pack_systems(pack_id, body.system_ids)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return [_to_system_response(s) for s in systems]
