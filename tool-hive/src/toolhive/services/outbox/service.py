"""Outbox 投递任务管理服务。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import OutboxStatus
from toolhive.core.exceptions import NotFoundError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.outbox_delivery import OutboxDelivery
from toolhive.models.outbox_event import OutboxEvent


class OutboxService:
    """Outbox 投递任务的查询与人工重投。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_deliveries(
        self,
        *,
        status: str | None = None,
        target: str | None = None,
        event_type: str | None = None,
        object_id: str | None = None,
        event_id: str | None = None,
        create_time_start: datetime | None = None,
        create_time_end: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[tuple[OutboxDelivery, OutboxEvent]], int]:
        """按条件查询投递记录，返回 (记录列表, 总数)。"""
        conditions = []
        if status:
            conditions.append(OutboxDelivery.status == status)
        if target:
            conditions.append(OutboxDelivery.target == target)
        if event_type:
            conditions.append(OutboxEvent.event_type == event_type)
        if object_id:
            conditions.append(OutboxEvent.object_id == object_id)
        if event_id:
            conditions.append(OutboxDelivery.event_id == event_id)
        if create_time_start is not None:
            conditions.append(OutboxDelivery.create_time >= create_time_start)
        if create_time_end is not None:
            conditions.append(OutboxDelivery.create_time <= create_time_end)

        total = await self.db.scalar(
            select(func.count())
            .select_from(OutboxDelivery)
            .join(OutboxEvent, OutboxEvent.event_id == OutboxDelivery.event_id)
            .where(*conditions)
        )
        result = await self.db.execute(
            select(OutboxDelivery, OutboxEvent)
            .join(OutboxEvent, OutboxEvent.event_id == OutboxDelivery.event_id)
            .where(*conditions)
            .order_by(OutboxDelivery.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all()), total or 0

    @transactional()
    async def retry_delivery(
        self, delivery_id: str,
    ) -> tuple[OutboxDelivery, OutboxEvent]:
        """人工重投指定投递记录：置回 PENDING，由 Worker 重新处理。"""
        row = await self.db.execute(
            select(OutboxDelivery, OutboxEvent)
            .join(OutboxEvent, OutboxEvent.event_id == OutboxDelivery.event_id)
            .where(OutboxDelivery.delivery_id == delivery_id)
        )
        pair = row.first()
        if pair is None:
            raise NotFoundError("投递记录不存在")
        delivery, event = pair
        delivery.status = OutboxStatus.PENDING
        delivery.last_error = None
        event.status = OutboxStatus.PENDING
        event.next_retry_at = None
        await self.db.flush()
        return delivery, event
