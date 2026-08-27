"""Catalog 工具版本管理 API（含执行绑定与审核发布）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.catalog.schemas import (
    CreateVersionRequest,
    ExecutionBindingResponse,
    HistoryItemResponse,
    PublishVersionRequest,
    StatusCommentRequest,
    ToolVersionResponse,
    UpdateVersionRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.catalog_provider_service import CatalogProviderService
from toolhive.services.catalog_version_service import CatalogVersionService

router = APIRouter(prefix="/tools", tags=["Catalog-Versions"])


def _to_response(version, binding=None, provider=None, is_default=False) -> ToolVersionResponse:
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


async def _load_detail(
    db: AsyncSession, version_id: str,
) -> tuple[object, object | None, object | None, bool]:
    """加载版本详情：版本 + 绑定 + Provider + 是否默认。"""
    svc = CatalogVersionService(db)
    version = await svc.get_version(version_id)
    binding = await svc.get_binding(version_id)
    provider = None
    if binding is not None:
        provider = await CatalogProviderService(db).get_provider(binding.provider_id)
    tool = await svc._get_tool(version.tool_id)
    return version, binding, provider, tool.default_version_id == version.id


@router.get("/{tool_id}/versions", response_model=list[ToolVersionResponse])
async def list_versions(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_VIEW)),
):
    """查询工具下的全部版本。"""
    svc = CatalogVersionService(db)
    versions = await svc.list_versions(tool_id)
    tool = await svc._get_tool(tool_id)
    items = []
    for version in versions:
        binding = await svc.get_binding(version.id)
        provider = None
        if binding is not None:
            provider = await CatalogProviderService(db).get_provider(
                binding.provider_id
            )
        items.append(
            _to_response(
                version, binding, provider, version.id == tool.default_version_id,
            )
        )
    return items


@router.post(
    "/{tool_id}/versions", response_model=ToolVersionResponse, status_code=201,
)
async def create_version(
    tool_id: str,
    body: CreateVersionRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_EDIT)),
):
    """创建草稿版本（可同时配置执行绑定）。"""
    svc = CatalogVersionService(db)
    try:
        version = await svc.create_version(
            tool_id,
            body.version,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            release_note=body.release_note,
            binding=(
                body.binding.model_dump() if body.binding is not None else None
            ),
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _build_response(db, version.id)


@router.get(
    "/{tool_id}/versions/{version_id}", response_model=ToolVersionResponse,
)
async def get_version(
    tool_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_VIEW)),
):
    """查询版本详情。"""
    return await _build_response(db, version_id)


@router.patch(
    "/{tool_id}/versions/{version_id}", response_model=ToolVersionResponse,
)
async def update_version(
    tool_id: str,
    version_id: str,
    body: UpdateVersionRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_EDIT)),
):
    """编辑草稿 / 驳回状态版本。"""
    svc = CatalogVersionService(db)
    try:
        await svc.update_version(
            version_id,
            input_schema=body.input_schema,
            output_schema=body.output_schema,
            release_note=body.release_note,
            binding=(
                body.binding.model_dump() if body.binding is not None else None
            ),
            clear_binding=body.clear_binding,
            expected_row_version=body.row_version,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _build_response(db, version_id)


@router.post(
    "/{tool_id}/versions/{version_id}/submit-review",
    response_model=ToolVersionResponse,
)
async def submit_review(
    tool_id: str,
    version_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_EDIT)),
):
    """送审：草稿 / 驳回 → 待审核。"""
    svc = CatalogVersionService(db)
    try:
        await svc.submit_review(version_id, body.comment if body else None)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _build_response(db, version_id)


@router.post(
    "/{tool_id}/versions/{version_id}/publish", response_model=ToolVersionResponse,
)
async def publish_version(
    tool_id: str,
    version_id: str,
    body: PublishVersionRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_PUBLISH)),
):
    """发布版本（首个发布必须设为默认）。"""
    svc = CatalogVersionService(db)
    try:
        await svc.publish(
            version_id, set_default=body.set_default, comment=body.comment,
        )
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _build_response(db, version_id)


@router.post(
    "/{tool_id}/versions/{version_id}/set-default",
    response_model=ToolVersionResponse,
)
async def set_default_version(
    tool_id: str,
    version_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_PUBLISH)),
):
    """切换默认版本（仅已发布版本）。"""
    svc = CatalogVersionService(db)
    try:
        await svc.set_default(tool_id, version_id)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _build_response(db, version_id)


@router.post(
    "/{tool_id}/versions/{version_id}/disable", response_model=ToolVersionResponse,
)
async def disable_version(
    tool_id: str,
    version_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """停用版本（在途请求放行完成）。"""
    return await _transition(
        db, version_id, "disable", body.comment if body else None,
    )


@router.post(
    "/{tool_id}/versions/{version_id}/enable", response_model=ToolVersionResponse,
)
async def enable_version(
    tool_id: str,
    version_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """重新启用版本。"""
    return await _transition(
        db, version_id, "enable", body.comment if body else None,
    )


@router.post(
    "/{tool_id}/versions/{version_id}/withdraw", response_model=ToolVersionResponse,
)
async def withdraw_version(
    tool_id: str,
    version_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """撤回版本（不可直接恢复运行）。"""
    return await _transition(
        db, version_id, "withdraw", body.comment if body else None,
    )


@router.post(
    "/{tool_id}/versions/{version_id}/archive", response_model=ToolVersionResponse,
)
async def archive_version(
    tool_id: str,
    version_id: str,
    body: StatusCommentRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_MANAGE)),
):
    """归档版本（终态，不可恢复）。"""
    return await _transition(
        db, version_id, "archive", body.comment if body else None,
    )


@router.get("/{tool_id}/history", response_model=list[HistoryItemResponse])
async def tool_history(
    tool_id: str,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_VIEW)),
):
    """查询工具审核与发布历史。"""
    svc = CatalogVersionService(db)
    rows = await svc.list_tool_history(tool_id)
    return [
        HistoryItemResponse(
            kind=row["kind"],
            id=row["id"],
            version_id=row["version_id"],
            action=row["action"],
            comment=row["comment"],
            operator_account_id=row["operator_account_id"],
            from_status=row.get("from_status"),
            to_status=row.get("to_status"),
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def _build_response(db: AsyncSession, version_id: str) -> ToolVersionResponse:
    """组装版本响应（含绑定、Provider 与默认标记）。"""
    version, binding, provider, is_default = await _load_detail(db, version_id)
    return _to_response(version, binding, provider, is_default)


async def _transition(
    db: AsyncSession, version_id: str, action: str, comment: str | None,
) -> ToolVersionResponse:
    """执行版本状态动作并统一错误映射。"""
    svc = CatalogVersionService(db)
    try:
        await getattr(svc, action)(version_id, comment)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _build_response(db, version_id)
