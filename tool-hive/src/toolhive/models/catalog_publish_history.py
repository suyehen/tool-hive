"""Catalog 发布历史 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogPublishHistory(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """工具版本发布/停用/撤回/归档/默认切换历史。"""

    __tablename__ = "catalog_publish_history"

    tool_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_tool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_tool_version.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )  # publish | disable | enable | withdraw | archive | set_default
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
