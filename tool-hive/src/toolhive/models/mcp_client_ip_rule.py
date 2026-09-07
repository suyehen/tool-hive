"""MCP 客户端来源 IP 规则 ORM 模型。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.core.enums import IPRuleStatus
from toolhive.models.base import AuditMixin, Base, UUIDPrimaryKeyMixin


class McpClientIpRule(Base, UUIDPrimaryKeyMixin, AuditMixin):
    """MCP 客户端来源 IP 白名单规则。"""

    __tablename__ = "mcp_client_ip_rule"

    client_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("mcp_client.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    ip_cidr: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=IPRuleStatus.ACTIVE,
    )  # active | disabled
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
