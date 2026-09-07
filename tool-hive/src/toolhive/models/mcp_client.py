"""MCP 客户端 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import McpClientStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class McpClient(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """MCP 客户端：调用 MCP 端点的授权主体（独立于调用系统）。"""

    __tablename__ = "mcp_client"

    client_code: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=McpClientStatus.DRAFT, index=True,
    )  # draft | enabled | disabled | revoked
    deactivated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
