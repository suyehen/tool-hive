"""Catalog 工具版本 ORM 模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import ToolVersionStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class CatalogToolVersion(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """工具版本：唯一走完整审核发布流程的可执行内容单元。"""

    __tablename__ = "catalog_tool_version"
    __table_args__ = (
        UniqueConstraint("tool_id", "version", name="uq_catalog_tool_version"),
    )

    tool_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("catalog_tool.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=ToolVersionStatus.DRAFT, index=True,
    )  # draft | pending_review | approved | rejected | published | disabled | withdrawn | archived
    input_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    output_schema: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    release_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
