"""MCP 客户端可发现工具计算：A2 授权 × Catalog 实时状态 × mcp_enabled。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import (
    CatalogObjectStatus,
    ToolScopeStatus,
    ToolVersionStatus,
)
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.models.mcp_client_scope import McpClientScope
from toolhive.runtime.tool_control.scope_expansion import expand_scope_tool_ids


@dataclass
class McpToolListing:
    """MCP tools/list 条目（Schema 取自默认已发布版本）。"""

    full_code: str
    name: str
    description: str
    input_schema: dict[str, object]


class McpCatalogService:
    """按 MCP 客户端授权范围计算当前可发现工具集合。"""

    def __init__(self, db: AsyncSession, client_id: str):
        self.db = db
        self.client_id = client_id

    async def list_authorized(self) -> list[McpToolListing]:
        """返回授权内且实时可用的工具清单（默认只认已发布默认版本）。"""
        scopes = await self._load_active_scopes()
        if not scopes:
            return []
        allowed_ids = await expand_scope_tool_ids(self.db, scopes)
        if not allowed_ids:
            return []
        tools = list(
            (
                await self.db.execute(
                    select(CatalogTool)
                    .where(
                        CatalogTool.id.in_(tuple(allowed_ids)),
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
        versions = await self._load_default_published_versions(tools)
        listings: list[McpToolListing] = []
        for tool in tools:
            version_schema = versions.get(tool.id)
            if tool.id in versions:
                schema = version_schema or tool.input_schema or {"type": "object"}
                listings.append(
                    McpToolListing(
                        full_code=tool.full_code,
                        name=tool.name,
                        description=tool.description or tool.name,
                        input_schema=schema,
                    )
                )
        return listings

    async def _load_active_scopes(self) -> list[McpClientScope]:
        """查询客户端 ACTIVE 授权范围。"""
        result = await self.db.execute(
            select(McpClientScope).where(
                McpClientScope.client_id == self.client_id,
                McpClientScope.status == ToolScopeStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def _load_default_published_versions(
        self, tools: list[CatalogTool],
    ) -> dict[str, dict[str, object] | None]:
        """返回工具 → 默认已发布版本 input_schema（缺失不回退）。"""
        if not tools:
            return {}
        tool_ids = [tool.id for tool in tools]
        rows = await self.db.execute(
            select(
                CatalogToolVersion.tool_id,
                CatalogToolVersion.input_schema,
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
        return {row[0]: row[1] for row in rows.all()}
