"""Catalog Provider ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import CatalogObjectStatus, ProviderType
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogProvider(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """Provider：工具执行的固定通道（builtin 或 http）。"""

    __tablename__ = "catalog_provider"

    provider_code: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    provider_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProviderType.HTTP,
    )  # builtin | http
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CatalogObjectStatus.ENABLED, index=True,
    )  # enabled | disabled | archived
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_security_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
