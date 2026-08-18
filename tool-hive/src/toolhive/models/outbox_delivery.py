"""Outbox 投递记录 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import OutboxStatus
from toolhive.models.base import AuditMixin, Base


class OutboxDelivery(Base, AuditMixin):
    """Outbox 投递记录：按目标（redis/chroma）分别记录成功与失败。"""

    __tablename__ = "outbox_delivery"
    __table_args__ = (
        UniqueConstraint("event_id", "target", name="uq_outbox_delivery_event_target"),
        Index("idx_outbox_delivery_event_id", "event_id"),
        Index("idx_outbox_delivery_status", "status"),
    )

    delivery_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )  # redis | chroma
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OutboxStatus.PENDING,
    )  # PENDING | PROCESSING | RETRY | SUCCEEDED | DEAD
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_instance: Mapped[str | None] = mapped_column(String(64), nullable=True)
