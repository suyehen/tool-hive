"""Catalog 工具管理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.catalog.schemas import (
    CreateToolRequest,
    ExecutionBindingResponse,
    StatusCommentRequest,
    ToolDetailResponse,
    ToolListResponse,
    ToolResponse,
    ToolVersionResponse,
    UpdateToolRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.services.catalog_tool_service import CatalogToolService
from toolhive.services.catalog_version_service import CatalogVersionService

router = APIRouter(prefix="/tools", tags=["Catalog-Tools"])


def _to_response(tool) -> ToolResponse:
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


async def _load_bindings(
    db: AsyncSession, version_ids: list[str],
) -> dict[str, CatalogExecutionBinding]:
    """批量加载版本的执行绑定（避免逐条查询）。"""
    if not version_ids:
        return {}
    result = await db.execute(
        select(CatalogExecutionBinding).where(
            CatalogExecutionBinding.version_id.in_(version_ids)
        )
    )
    return {b.version_id: b for b in result.scalars()}


async def _load_providers(
    db: AsyncSession, provider_ids: list[str],
) -> dict[str, CatalogProvider]:
    """批量加载 Provider（避免逐条查询）。"""
    if not provider_ids:
        return {}
    result = await db.execute(
        select(CatalogProvider).where(CatalogProvider.id.in_(provider_ids))
    )
    return {p.id: p for p in result.scalars()}


def _to_version_response(
    version, binding: CatalogExecutionBinding | None,
    provider: CatalogProvider | None, is_default: bool,
) -> ToolVersionResponse:
    """版本 ORM → 响应对象（含执行绑定与 Provider 信息）。"""
    binding_response = None
    if binding is not None and provider is not None:
        binding_response = ExecutionBindingResponse(
            id=binding.id,
            version_id=binding.version_id,
            provider_id=binding.provider_id,
            provider_code=provider.provider_code,
            provider_name=provider.name,
            method=binding.method,
            path_template=binding.path_template,
            parameter_mapping=binding.parameter_mapping,
            allowed_headers=binding.allowed_headers,
            response_handling=binding.response_handling,
            timeout_seconds=binding.timeout_seconds,
            retry_max=binding.retry_max,
            idempotent=binding.idempotent,
            row_version=binding.row_version,
            created_at=binding.create_time,
            updated_at=binding.update_time,
        )
    return ToolVersionResponse(
        id=version.id,
        tool_id=version.tool_id,
        version=version.version,
        status=version.status,
        input_schema=version.input_schema,
        output_schema=version.output_schema,
        release_note=version.release_note,
        review_comment=version.review_comment,
        row_version=version.row_version,
        is_default=is_default,
        created_at=version.create_time,
        updated_at=version.update_time,
        binding=binding_response,
    )


@router.get("", response_model=ToolListResponse)
async def list_tools(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    keyword: str | None = Query(default=None, max_length=128),
    namespace: str | None = Query(default=None),
    status: str | None = Query(default=None),
    risk_level: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_VIEW)),
):
    """分页查询工具。"""
    svc = CatalogToolService(db)
    items, total = await svc.list_tools(
        offset=offset, limit=limit, keyword=keyword, namespace=namespace,
        status=status, risk_level=risk_level,
    )
    return ToolListResponse(
        items=[_to_response(t) for t in items], total=total,
    )


@router.post("", response_model=ToolResponse, status_code=201)
async def create_tool(
    body: CreateToolRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_CREATE)),
):
    """创建工具。"""
    svc = CatalogToolService(db)
    try:
        tool = await svc.create_tool(
            namespace=body.namespace,
            tool_code=body.tool_code,
            name=body.name,
            description=body.description,
            risk_level=body.risk_level,
            discoverable=body.discoverable,
            executable=body.executable,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
        )
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(tool)


@router.get("/{tool_id}", response_model=ToolDetailResponse)
async def get_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_VIEW)),
):
    """查询工具详情（含版本与执行绑定）。"""
    tool_svc = CatalogToolService(db)
    version_svc = CatalogVersionService(db)
    try:
        tool = await tool_svc.get_tool(tool_id)
        versions = await version_svc.list_versions(tool_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    bindings = await _load_bindings(db, [v.id for v in versions])
    providers = await _load_providers(
        db, [b.provider_id for b in bindings.values() if b.provider_id]
    )
    detail = _to_response(tool).model_dump()
    detail["versions"] = [
        _to_version_response(
            version,
            bindings.get(version.id),
            providers.get(bindings.get(version.id).provider_id)
            if bindings.get(version.id) else None,
            version.id == tool.default_version_id,
        )
        for version in versions
    ]
    return ToolDetailResponse(**detail)


@router.patch("/{tool_id}", response_model=ToolResponse)
async def update_tool(
    tool_id: str,
    body: UpdateToolRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_EDIT)),
):
    """更新工具资料与 Schema。"""
    svc = CatalogToolService(db)
    try:
        tool = await svc.update_tool(
            tool_id,
            name=body.name,
            description=body.description,
            risk_level=body.risk_level,
            discoverable=body.discoverable,
            executable=body.executable,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(tool)


@router.post("/{tool_id}/enable", response_model=ToolResponse)
async def enable_tool(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """启用工具。"""
    return await _set_status(tool_id, "enabled", db)


@router.post("/{tool_id}/disable", response_model=ToolResponse)
async def disable_tool(
    tool_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """停用工具。"""
    return await _set_status(tool_id, "disabled", db)


@router.post("/{tool_id}/archive", response_model=ToolResponse)
async def archive_tool(
    tool_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """归档工具（终态，不可恢复）。"""
    return await _set_status(tool_id, "archived", db)


async def _set_status(tool_id: str, status: str, db: AsyncSession) -> ToolResponse:
    """执行工具状态变更并统一错误映射。"""
    svc = CatalogToolService(db)
    try:
        tool = await svc.set_status(tool_id, status)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _to_response(tool)
