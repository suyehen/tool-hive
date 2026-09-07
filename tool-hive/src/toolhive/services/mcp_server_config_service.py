"""MCP Server 接入配置管理服务（单实例配置行）。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.exceptions import ConflictError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.mcp_server_config import (
    MCP_SERVER_CONFIG_ID,
    McpServerConfig,
)
from toolhive.services.audit_service import AuditService, get_current_operator_id


class McpServerConfigService:
    """MCP Server 全局配置的查询与更新。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_config(self) -> McpServerConfig:
        """返回配置行；init.sql 未初始化时自动补齐默认行。"""
        config = await self.db.get(McpServerConfig, MCP_SERVER_CONFIG_ID)
        if config is None:
            config = McpServerConfig(
                id=MCP_SERVER_CONFIG_ID,
                server_name="ToolHive",
                enabled=True,
                endpoint_path="/mcp",
                allowed_hosts=["127.0.0.1", "localhost"],
                create_time=datetime.now(UTC),
                create_by=None,
            )
            self.db.add(config)
            await self.db.flush()
        return config

    @transactional()
    async def update_config(
        self,
        *,
        server_name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        endpoint_path: str | None = None,
        allowed_hosts: list[str] | None = None,
        protocol_versions: list[str] | None = None,
        expected_row_version: int | None = None,
    ) -> McpServerConfig:
        """更新接入配置（仅更新显式提供的字段）。"""
        config = await self.get_config()
        if expected_row_version is not None:
            await self.db.refresh(config, with_for_update=True)
            if config.row_version != expected_row_version:
                raise ConflictError("数据已被他人修改，请刷新后重试")
        if server_name is not None:
            value = server_name.strip()
            if not value:
                raise ValidationError("Server 名称不能为空")
            config.server_name = value
        if description is not None:
            config.description = description
        if enabled is not None:
            config.enabled = enabled
        if endpoint_path is not None:
            value = endpoint_path.strip()
            if not value.startswith("/"):
                raise ValidationError("端点路径必须以 / 开头")
            config.endpoint_path = value
        if allowed_hosts is not None:
            hosts = [host.strip() for host in allowed_hosts if host.strip()]
            if not hosts:
                raise ValidationError("Host 白名单不能为空")
            config.allowed_hosts = hosts
        if protocol_versions is not None:
            config.protocol_versions = protocol_versions or None
        config.update_time = datetime.now(UTC)
        config.update_by = get_current_operator_id()
        config.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="mcp_server_config.update",
            object_type="mcp_server_config",
            object_id=MCP_SERVER_CONFIG_ID,
            after_summary={
                "server_name": config.server_name,
                "enabled": config.enabled,
                "endpoint_path": config.endpoint_path,
            },
        )
        return config
