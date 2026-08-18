"""Outbox 投递任务管理 API schemas。"""

from __future__ import annotations

from pydantic import BaseModel

from toolhive.core.time_utils import UTCDateTime


class DeliveryTaskResponse(BaseModel):
    delivery_id: str
    event_id: str
    event_type: str
    object_type: str
    object_id: str
    object_version: str | None
    event_status: str
    target: str
    status: str
    attempts: int
    last_error: str | None
    duration_ms: int | None
    worker_instance: str | None
    next_retry_at: UTCDateTime | None
    locked_by: str | None
    locked_until: UTCDateTime | None
    create_time: UTCDateTime
    update_time: UTCDateTime | None


class DeliveryTaskListResponse(BaseModel):
    items: list[DeliveryTaskResponse]
    total: int
