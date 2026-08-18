"""Outbox 投递任务管理接口。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.api.admin.auth.router import _get_current_user
from toolhive.api.admin.system_tasks.schemas import (
    DeliveryTaskListResponse,
    DeliveryTaskResponse,
)
from toolhive.core.exceptions import NotFoundError
from toolhive.infrastructure.database import get_db
from toolhive.models.outbox_delivery import OutboxDelivery
from toolhive.models.outbox_event import OutboxEvent
from toolhive.services.outbox.service import OutboxService

router = APIRouter(prefix="/system-tasks", tags=["system-tasks"])


def _to_response(
    delivery: OutboxDelivery, event: OutboxEvent,
) -> DeliveryTaskResponse:
    return DeliveryTaskResponse(
        delivery_id=delivery.delivery_id,
        event_id=delivery.event_id,
        event_type=event.event_type,
        object_type=event.object_type,
        object_id=event.object_id,
        object_version=event.object_version,
        event_status=event.status,
        target=delivery.target,
        status=delivery.status,
        attempts=delivery.attempts,
        last_error=delivery.last_error,
        duration_ms=delivery.duration_ms,
        worker_instance=delivery.worker_instance,
        next_retry_at=event.next_retry_at,
        locked_by=event.locked_by,
        locked_until=event.locked_until,
        create_time=delivery.create_time,
        update_time=delivery.update_time,
    )


@router.get("", response_model=DeliveryTaskListResponse)
async def list_delivery_tasks(
    db: Annotated[AsyncSession, Depends(get_db)],
    _account=Depends(_get_current_user),
    status: str | None = Query(default=None),
    target: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    object_id: str | None = Query(default=None),
    event_id: str | None = Query(default=None),
    create_time_start: datetime | None = Query(default=None),
    create_time_end: datetime | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
):
    """查询投递任务（支持按状态、目标、事件类型、业务对象、事件 ID 和时间范围过滤）。"""
    svc = OutboxService(db)
    rows, total = await svc.list_deliveries(
        status=status,
        target=target,
        event_type=event_type,
        object_id=object_id,
        event_id=event_id,
        create_time_start=create_time_start,
        create_time_end=create_time_end,
        offset=offset,
        limit=limit,
    )
    return DeliveryTaskListResponse(
        items=[_to_response(d, e) for d, e in rows],
        total=total,
    )


@router.post("/{delivery_id}/retry", response_model=DeliveryTaskResponse)
async def retry_delivery(
    delivery_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    _account=Depends(_get_current_user),
):
    """人工重投指定投递记录（置回 PENDING，由 Worker 重新处理）。"""
    svc = OutboxService(db)
    try:
        delivery, event = await svc.retry_delivery(delivery_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _to_response(delivery, event)
