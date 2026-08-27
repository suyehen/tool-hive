"""Catalog 工具 ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import CatalogObjectStatus, RiskLevel
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogTool(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """工具：Catalog 目录条目，持有多个工具版本。"""

    __tablename__ = "catalog_tool"
    __table_args__ = (
        UniqueConstraint(
            "namespace", "tool_code", name="uq_catalog_tool_namespace_code",
        ),
    )

    namespace: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    tool_code: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RiskLevel.LOW,
    )  # low | medium | high
    discoverable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    executable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CatalogObjectStatus.ENABLED, index=True,
    )  # enabled | disabled | archived
    default_version_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @property
    def full_code(self) -> str:
        """完整工具标识：{namespace}.{tool_code}。"""
        return f"{self.namespace}.{self.tool_code}"
