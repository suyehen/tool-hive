"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class ExecutionBinding(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "execution_binding"
    __table_args__ = (Index("uq_binding_version", "version_id", unique=True),)

    version_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tool_version.id"), nullable=False
    )
    provider_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("provider.id"), nullable=False)
    method: Mapped[str | None] = mapped_column(String(8), nullable=True)
    path_template: Mapped[str | None] = mapped_column(String(512), nullable=True)
    param_mapping: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    timeout_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retry_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
