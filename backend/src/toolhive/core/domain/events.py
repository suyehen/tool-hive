"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class ReviewRecord(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "review_record"
    __table_args__ = (Index("idx_review_record_version", "version_id"),)

    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tool_version.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    from_status: Mapped[str] = mapped_column(String(24), nullable=False)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class Invocation(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "invocation"
    __table_args__ = (
        Index("idx_invocation_trace", "trace_id"),
        Index("idx_invocation_principal", "principal_id", text("create_time DESC")),
        Index("idx_invocation_tool", "tool_id", text("create_time DESC")),
    )

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    principal_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider_row_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    binding_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider_config_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    protocol: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AuditLog(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_object", "object_type", "object_id"),
        Index("idx_audit_time", text("create_time DESC")),
    )

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    result: Mapped[str] = mapped_column(
        String(16), server_default=text("'success'"), default="success", nullable=False
    )
    before_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    after_summary: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class SearchEvent(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "search_event"
    __table_args__ = (
        Index("idx_search_event_principal", "principal_id", text("create_time DESC")),
        Index("idx_search_event_time", text("create_time DESC")),
    )

    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    principal_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    query: Mapped[str] = mapped_column(String(512), nullable=False)
    scope: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    top_k: Mapped[int] = mapped_column(Integer, nullable=False)
    returned: Mapped[int] = mapped_column(Integer, nullable=False)
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False)
    degraded: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class OutboxEvent(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "outbox_event"
    __table_args__ = (Index("idx_outbox_pending", "status", "next_retry_at"),)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_type: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'PENDING'"), default="PENDING", nullable=False
    )
    attempts: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), default=0, nullable=False
    )
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
