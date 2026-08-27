"""Catalog → Outbox 派生索引事件发布。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.models.base import gen_id
from toolhive.models.outbox_delivery import OutboxDelivery
from toolhive.models.outbox_event import OutboxEvent


def emit_catalog_index_event(
    db: AsyncSession,
    *,
    event_type: str,
    object_type: str,
    object_id: str,
    object_version: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """在当前事务内写入 Catalog 派生索引同步事件（chroma 目标）。

    Chroma 投递目标已由 Outbox Worker 按事件驱动；阶段 6 前投递实现
    仅记录日志，索引 upsert/delete 随阶段 6 接入。
    """
    event_id = gen_id()
    now = datetime.now(UTC)
    event = OutboxEvent(
        event_id=event_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        object_version=object_version,
        payload=payload,
        create_time=now,
    )
    delivery = OutboxDelivery(
        delivery_id=gen_id(),
        event_id=event_id,
        target="chroma",
        create_time=now,
    )
    db.add(event)
    db.add(delivery)
