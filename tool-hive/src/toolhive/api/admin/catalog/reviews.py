"""Catalog 审核处理 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.catalog.schemas import (
    PendingReviewItemResponse,
    PendingReviewListResponse,
    ReviewRequest,
)
from toolhive.api.admin.deps import require_operation
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.core.operation_codes import OperationCode
from toolhive.infrastructure.database import get_db
from toolhive.services.catalog_version_service import CatalogVersionService

router = APIRouter(tags=["Catalog-Reviews"])


@router.get("/reviews/pending", response_model=PendingReviewListResponse)
async def list_pending_reviews(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_REVIEW)),
):
    """查询全部待审核版本。"""
    svc = CatalogVersionService(db)
    rows, total = await svc.list_pending_reviews(offset=offset, limit=limit)
    return PendingReviewListResponse(
        items=[
            PendingReviewItemResponse(
                version_id=version.id,
                tool_id=tool.id,
                tool_name=tool.name,
                full_code=tool.full_code,
                version=version.version,
                release_note=version.release_note,
                input_schema=version.input_schema,
                output_schema=version.output_schema,
                submitter_account_id=version.create_by,
                created_at=version.create_time,
            )
            for version, tool in rows
        ],
        total=total,
    )


@router.post("/reviews/{version_id}/approve")
async def approve_review(
    version_id: str,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_REVIEW)),
):
    """审核通过。"""
    svc = CatalogVersionService(db)
    try:
        await svc.approve(version_id, body.comment)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已通过审核"}


@router.post("/reviews/{version_id}/reject")
async def reject_review(
    version_id: str,
    body: ReviewRequest,
    db: AsyncSession = Depends(get_db),
    _account=Depends(require_operation(OperationCode.TOOL_REVIEW)),
):
    """审核驳回。"""
    svc = CatalogVersionService(db)
    try:
        await svc.reject(version_id, body.comment)
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (ConflictError, ValidationError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"detail": "已驳回"}
