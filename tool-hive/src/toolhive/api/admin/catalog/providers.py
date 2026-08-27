"""Catalog Provider 管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.catalog.schemas import (
    CreateProviderRequest,
    ProviderListResponse,
    ProviderResponse,
    StatusCommentRequest,
    UpdateProviderRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.catalog_provider_service import CatalogProviderService

router = APIRouter(prefix="/providers", tags=["Catalog-Providers"])


def _to_response(provider) -> ProviderResponse:
    """Provider ORM → 响应对象。"""
    return ProviderResponse(
        id=provider.id,
        provider_code=provider.provider_code,
        name=provider.name,
        provider_type=provider.provider_type,
        status=provider.status,
        description=provider.description,
        target_security_config=provider.target_security_config,
        row_version=provider.row_version,
        created_at=provider.create_time,
        updated_at=provider.update_time,
    )


@router.get("", response_model=ProviderListResponse)
async def list_providers(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None),
    provider_type: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_VIEW)),
):
    """分页查询 Provider。"""
    svc = CatalogProviderService(db)
    items, total = await svc.list_providers(
        offset=offset, limit=limit, keyword=keyword,
        status=status, provider_type=provider_type,
    )
    return ProviderListResponse(
        items=[_to_response(p) for p in items], total=total,
    )


@router.post("", response_model=ProviderResponse, status_code=201)
async def create_provider(
    body: CreateProviderRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_CREATE)),
):
    """创建 Provider。"""
    svc = CatalogProviderService(db)
    try:
        provider = await svc.create_provider(
            provider_code=body.provider_code,
            name=body.name,
            provider_type=body.provider_type,
            description=body.description,
            target_security_config=(
                body.target_security_config.model_dump()
                if body.target_security_config is not None
                else None
            ),
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(provider)


@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_VIEW)),
):
    """查询 Provider 详情。"""
    svc = CatalogProviderService(db)
    try:
        provider = await svc.get_provider(provider_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _to_response(provider)


@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    body: UpdateProviderRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_EDIT)),
):
    """更新 Provider 资料与目标安全配置。"""
    svc = CatalogProviderService(db)
    try:
        provider = await svc.update_provider(
            provider_id,
            name=body.name,
            description=body.description,
            target_security_config=(
                body.target_security_config.model_dump()
                if body.target_security_config is not None
                else None
            ),
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(provider)


@router.post("/{provider_id}/enable", response_model=ProviderResponse)
async def enable_provider(
    provider_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_MANAGE)),
):
    """启用 Provider。"""
    return await _set_status(provider_id, "enabled", db)


@router.post("/{provider_id}/disable", response_model=ProviderResponse)
async def disable_provider(
    provider_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_MANAGE)),
):
    """停用 Provider。"""
    return await _set_status(provider_id, "disabled", db)


@router.post("/{provider_id}/archive", response_model=ProviderResponse)
async def archive_provider(
    provider_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.PROVIDER_MANAGE)),
):
    """归档 Provider（终态，不可恢复）。"""
    return await _set_status(provider_id, "archived", db)


async def _set_status(provider_id: str, status: str, db: AsyncSession) -> ProviderResponse:
    """执行 Provider 状态变更并统一错误映射。"""
    svc = CatalogProviderService(db)
    try:
        provider = await svc.set_status(provider_id, status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(provider)
