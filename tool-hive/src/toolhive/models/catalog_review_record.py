"""Catalog 审核记录 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogReviewRecord(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """工具版本送审/审核记录（提交、通过、驳回）。"""

    __tablename__ = "catalog_review_record"

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
    )  # submit_review | approve | reject
    from_status: Mapped[str] = mapped_column(String(24), nullable=False)
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_account_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
