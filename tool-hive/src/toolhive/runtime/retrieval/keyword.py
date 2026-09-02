"""Discover 关键词检索：阶段 4 走 PostgreSQL，阶段 6 接入 Chroma 后作为降级。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import ToolVersionStatus
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.tool_control.service import CallControlService


class KeywordRetrieval:
    """在受控可发现集合内执行有界关键词检索。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self, system_id: str, query: str, limit: int = 20,
    ) -> list[CatalogTool]:
        """检索候选工具（范围 + 发布状态 + 关键词，不扩大可见范围）。"""
        allowed = await CallControlService(self.db).list_discoverable_tools(
            system_id
        )
        if not allowed:
            return []
        allowed_ids = [tool.id for tool in allowed]
        pattern = f"%{query.strip()}%"
        result = await self.db.execute(
            select(CatalogTool)
            .where(
                CatalogTool.id.in_(allowed_ids),
                or_(
                    CatalogTool.tool_code.ilike(pattern),
                    CatalogTool.name.ilike(pattern),
                    CatalogTool.namespace.ilike(pattern),
                    CatalogTool.description.ilike(pattern),
                ),
            )
            .order_by(CatalogTool.namespace, CatalogTool.tool_code)
            .limit(limit)
        )
        return list(result.scalars().all())


async def fetch_default_versions(
    db: AsyncSession, tools: list[CatalogTool],
) -> dict[str, str]:
    """返回工具 → 默认已发布版本号（严格只认默认版本，不回退）。"""
    if not tools:
        return {}
    tool_ids = [tool.id for tool in tools]
    rows = (
        await db.execute(
            select(CatalogToolVersion.tool_id, CatalogToolVersion.version)
            .join(
                CatalogTool,
                CatalogTool.id == CatalogToolVersion.tool_id,
            )
            .where(
                CatalogTool.id.in_(tool_ids),
                CatalogTool.default_version_id == CatalogToolVersion.id,
                CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
            )
        )
    ).all()
    return {tool_id: version for tool_id, version in rows}
