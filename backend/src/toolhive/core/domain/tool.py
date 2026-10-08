"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, RowVersionMixin, SnowflakePrimaryKeyMixin


class Tool(SnowflakePrimaryKeyMixin, AuditMixin, RowVersionMixin, Base):
    __tablename__ = "tool"
    __table_args__ = (
        CheckConstraint("side_effect IN ('read', 'write', 'unknown')", name="ck_tool_side_effect"),
        Index("uq_tool_code", "code", unique=True),
        Index("uq_tool_source_ref", "source_ref", unique=True),
        Index("idx_tool_domain_system", "domain", "system"),
        Index("idx_tool_provider", "provider_id"),
        Index("idx_tool_status_exec", "status", "executable"),
        Index("idx_tool_tags", "tags", postgresql_using="gin"),
        Index(
            "idx_tool_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "idx_tool_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
        Index(
            "idx_tool_code_trgm",
            "code",
            postgresql_using="gin",
            postgresql_ops={"code": "gin_trgm_ops"},
        ),
    )

    code: Mapped[str] = mapped_column(String(160), nullable=False)
    source_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    provider_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("provider.id"), nullable=True
    )
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
    review_required: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB(none_as_null=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(16), server_default=text("'enabled'"), default="enabled", nullable=False
    )
    owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
