"""MCP 客户端访问令牌 ORM 模型（仅存哈希）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import McpTokenStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class McpClientToken(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """MCP 客户端令牌：一次签发一条记录，同一客户端同时最多一条 ACTIVE。"""

    __tablename__ = "mcp_client_token"

    client_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("mcp_client.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_key: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=McpTokenStatus.ACTIVE,
    )  # active | revoked
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
