"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, RowVersionMixin, SnowflakePrimaryKeyMixin


class ToolVersion(SnowflakePrimaryKeyMixin, AuditMixin, RowVersionMixin, Base):
    __tablename__ = "tool_version"
    __table_args__ = (
        CheckConstraint(
            "side_effect IN ('read', 'write', 'unknown')", name="ck_tool_version_side_effect"
        ),
        Index("uq_tool_version", "tool_id", "version", unique=True),
        Index("uq_tool_version_owner", "tool_id", "id", unique=True),
        Index("idx_tool_version_status", "status"),
    )

    tool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tool.id"), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    domain: Mapped[str | None] = mapped_column(String(64), nullable=True)
    system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), default=list, nullable=False
    )
    risk: Mapped[str] = mapped_column(
        String(16), server_default=text("'low'"), default="low", nullable=False
    )
    side_effect: Mapped[str] = mapped_column(
        String(16), server_default=text("'unknown'"), default="unknown", nullable=False
    )
    retry_safe: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    executable: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    discoverable: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), server_default=text("'draft'"), default="draft", nullable=False
    )
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
