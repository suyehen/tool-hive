"""Catalog 能力包 ↔ 工具 关联 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogCapabilityPackTool(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """能力包与工具的多对多关联。"""

    __tablename__ = "catalog_capability_pack_tool"
    __table_args__ = (
        UniqueConstraint("pack_id", "tool_id", name="uq_catalog_pack_tool"),
    )

    pack_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_capability_pack.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_tool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
