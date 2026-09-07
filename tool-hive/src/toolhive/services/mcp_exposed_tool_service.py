"""MCP 暴露工具只读查询服务（管理端）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import CatalogObjectStatus, ToolVersionStatus
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion


@dataclass
class ExposedToolItem:
    """MCP 暴露工具条目（只读视图）。"""

    id: str
    full_code: str
    name: str
    risk_level: str
    status: str
    mcp_enabled: bool
    version: str


class McpExposedToolService:
    """查询当前满足 MCP 可发现条件的 Catalog 工具。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_exposed(self) -> list[ExposedToolItem]:
        """返回 mcp_enabled + 启用 + 可发现 + 已发布默认版本的工具。"""
        tools = list(
            (
                await self.db.execute(
                    select(CatalogTool)
                    .where(
                        CatalogTool.status == CatalogObjectStatus.ENABLED,
                        CatalogTool.discoverable.is_(True),
                        CatalogTool.mcp_enabled.is_not(False),
                    )
                    .order_by(CatalogTool.namespace, CatalogTool.tool_code)
                )
            )
            .scalars()
            .all()
        )
        if not tools:
            return []
        tool_ids = [tool.id for tool in tools]
        rows = await self.db.execute(
            select(
                CatalogToolVersion.tool_id,
                CatalogToolVersion.version,
            )
            .join(
                CatalogTool,
                CatalogTool.id == CatalogToolVersion.tool_id,
            )
            .where(
                CatalogTool.id.in_(tuple(tool_ids)),
                CatalogTool.default_version_id == CatalogToolVersion.id,
                CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
            )
        )
        version_map = {row[0]: row[1] for row in rows.all()}
        items = []
        for tool in tools:
            version = version_map.get(tool.id)
            if version is None:
                continue
            items.append(
                ExposedToolItem(
                    id=tool.id,
                    full_code=tool.full_code,
                    name=tool.name,
                    risk_level=tool.risk_level,
                    status=tool.status,
                    mcp_enabled=tool.mcp_enabled,
                    version=version,
                )
            )
        return items
