"""MCP 客户端工具/能力包范围 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import ToolScopeStatus, ToolScopeType
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class McpClientScope(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """MCP 客户端可访问的工具/能力包/命名空间范围条目。"""

    __tablename__ = "mcp_client_scope"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "scope_type", "scope_code",
            name="uq_mcp_client_scope",
        ),
    )

    client_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("mcp_client.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scope_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ToolScopeType.TOOL,
    )  # capability | namespace | tool
    scope_code: Mapped[str] = mapped_column(
        String(256), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ToolScopeStatus.ACTIVE,
    )  # active | disabled
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
