"""Catalog 能力包 ↔ 调用系统 授权关联 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogCapabilityPackSystem(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """能力包与调用系统的授权关联（能力包侧声明授权）。"""

    __tablename__ = "catalog_capability_pack_system"
    __table_args__ = (
        UniqueConstraint("pack_id", "system_id", name="uq_catalog_pack_system"),
    )

    pack_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_capability_pack.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    system_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("caller_system.system_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
