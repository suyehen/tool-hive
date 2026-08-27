"""Catalog 能力包 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import CatalogObjectStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogCapabilityPack(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """能力包：工具的打包与调用系统授权单元。"""

    __tablename__ = "catalog_capability_pack"

    pack_code: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CatalogObjectStatus.ENABLED, index=True,
    )  # enabled | disabled | archived
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
