"""ToolCall / IndexOutbox 审计和索引模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import Base, TimestampMixin, UUIDPrimaryKey


class ToolCall(Base, UUIDPrimaryKey):
    __tablename__ = "tool_call"

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    caller_id: Mapped[str | None] = mapped_column(String(128))
    request_context: Mapped[str | None] = mapped_column(Text)  # JSON 脱敏摘要
    discover_decision: Mapped[str | None] = mapped_column(String(32))
    execute_decision: Mapped[str | None] = mapped_column(String(32))
    params_hash: Mapped[str | None] = mapped_column(String(64))
    confirmation_status: Mapped[str | None] = mapped_column(String(32))
    provider_name: Mapped[str | None] = mapped_column(String(128))
    provider_duration_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_code: Mapped[str | None] = mapped_column(String(32))
    coverage_result: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IndexOutbox(Base, UUIDPrimaryKey):
    __tablename__ = "index_outbox"

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)  # upsert, delete
    tool_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text)  # JSON 摘要
    index_version: Mapped[int] = mapped_column(Integer, default=1)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending, synced, failed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
