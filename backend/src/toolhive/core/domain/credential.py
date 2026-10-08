"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class Credential(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "credential"
    __table_args__ = (
        CheckConstraint(
            "ciphertext IS NOT NULL OR external_ref IS NOT NULL", name="ck_credential_source"
        ),
        Index("uq_credential_name", "name", unique=True),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'active'"), default="active", nullable=False
    )
    ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    kek_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB(none_as_null=True), server_default=text("'{}'::jsonb"), default=dict, nullable=False
    )
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
