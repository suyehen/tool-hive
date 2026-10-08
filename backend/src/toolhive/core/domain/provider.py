"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, RowVersionMixin, SnowflakePrimaryKeyMixin


class Provider(SnowflakePrimaryKeyMixin, AuditMixin, RowVersionMixin, Base):
    __tablename__ = "provider"
    __table_args__ = (Index("uq_provider_code", "code", unique=True),)

    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_ref: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("credential.id"), nullable=True
    )
    tls_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    limits: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'enabled'"), default="enabled", nullable=False
    )
