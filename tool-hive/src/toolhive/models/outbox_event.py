"""Outbox 事件 ORM 模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import OutboxStatus
from toolhive.models.base import AuditMixin, Base


class OutboxEvent(Base, AuditMixin):
    """Outbox 事件：业务数据、审计与派生索引投递的同一事务载体。"""

    __tablename__ = "outbox_event"
    __table_args__ = (
        Index("idx_outbox_event_status_next_retry", "status", "next_retry_at"),
        Index("idx_outbox_event_object", "object_type", "object_id"),
    )

    event_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(32), nullable=False)
    object_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OutboxStatus.PENDING,
    )  # PENDING | PROCESSING | RETRY | SUCCEEDED | DEAD
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
