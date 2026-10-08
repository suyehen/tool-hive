"""M0 domain persistence models (design §4, reviewed initial DDL)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.adapters.db.base import AuditMixin, Base, SnowflakePrimaryKeyMixin


class ToolChannel(SnowflakePrimaryKeyMixin, AuditMixin, Base):
    __tablename__ = "tool_channel"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tool_id", "version_id"],
            ["tool_version.tool_id", "tool_version.id"],
            name="fk_channel_version_owner",
        ),
        Index("uq_tool_channel", "tool_id", "name", unique=True),
    )

    tool_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tool.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(16), nullable=False)
    version_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
