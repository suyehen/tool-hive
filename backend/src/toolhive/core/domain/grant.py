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

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class Grant(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "grant_rule"
    __table_args__ = (
        Index("uq_grant_rule", "principal_id", "scope_type", "scope_value", unique=True),
        Index("idx_grant_rule_scope", "scope_type", "scope_value"),
    )

    principal_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("principal.id"), nullable=False
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_value: Mapped[str] = mapped_column(String(160), nullable=False)
    quota: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'active'"), default="active", nullable=False
    )
