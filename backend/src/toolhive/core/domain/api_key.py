"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class ApiKey(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "api_key"
    __table_args__ = (
        Index("uq_api_key_prefix", "key_prefix", unique=True),
        Index("idx_api_key_principal", "principal_id"),
    )

    principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principal.id"), nullable=False
    )
    key_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    key_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'active'"), default="active", nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
