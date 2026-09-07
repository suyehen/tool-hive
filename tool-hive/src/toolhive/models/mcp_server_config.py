"""MCP Server 全局配置 ORM 模型（单实例配置行）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from toolhive.models.base import AuditMixin, Base

# 单实例配置行的固定主键，init.sql 插入默认行
MCP_SERVER_CONFIG_ID = "default"


class McpServerConfig(Base, AuditMixin):
    """MCP Server 接入配置（全局限一行）。"""

    __tablename__ = "mcp_server_config"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    server_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="ToolHive",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    endpoint_path: Mapped[str] = mapped_column(
        String(64), nullable=False, default="/mcp",
    )
    allowed_hosts: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list,
    )
    protocol_versions: Mapped[list[Any] | None] = mapped_column(
        JSONB, nullable=True,
    )
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
