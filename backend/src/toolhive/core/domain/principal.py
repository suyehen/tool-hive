"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, RowVersionMixin, SnowflakePrimaryKeyMixin


class Principal(SnowflakePrimaryKeyMixin, AuditMixin, RowVersionMixin, Base):
    __tablename__ = "principal"
    __table_args__ = (Index("uq_principal_name", "name", unique=True),)

    type: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'enabled'"), default="enabled", nullable=False
    )
