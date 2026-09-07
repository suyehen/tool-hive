"""授权范围展开共享逻辑：调用系统与 MCP 客户端共用的 scope → 工具集合。"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import CatalogObjectStatus, ToolScopeType
from toolhive.models.catalog_capability_pack import CatalogCapabilityPack
from toolhive.models.catalog_capability_pack_tool import CatalogCapabilityPackTool
from toolhive.models.catalog_tool import CatalogTool


async def expand_scope_tool_ids(
    db: AsyncSession, scopes: Sequence[object],
) -> set[str]:
    """将命名空间 / 能力包 / 工具范围编码展开为 Catalog 工具 ID 集合。"""
    tool_codes: list[str] = []
    pack_codes: list[str] = []
    namespace_codes: list[str] = []
    for scope in scopes:
        code = str(getattr(scope, "scope_code")).strip()
        scope_type = getattr(scope, "scope_type")
        if scope_type == ToolScopeType.TOOL:
            tool_codes.append(code)
        elif scope_type == ToolScopeType.CAPABILITY:
            pack_codes.append(code)
        elif scope_type == ToolScopeType.NAMESPACE:
            namespace_codes.append(code)
    allowed_ids: set[str] = set()
    if tool_codes:
        rows = await db.execute(
            select(CatalogTool.id).where(
                (CatalogTool.namespace + "." + CatalogTool.tool_code).in_(
                    tool_codes
                ),
                CatalogTool.status != CatalogObjectStatus.ARCHIVED,
            )
        )
        allowed_ids.update(row[0] for row in rows.all())
    if pack_codes:
        rows = await db.execute(
            select(CatalogCapabilityPackTool.tool_id)
            .join(
                CatalogCapabilityPack,
                CatalogCapabilityPack.id == CatalogCapabilityPackTool.pack_id,
            )
            .where(
                CatalogCapabilityPack.pack_code.in_(tuple(pack_codes)),
                CatalogCapabilityPack.status == CatalogObjectStatus.ENABLED,
            )
        )
        allowed_ids.update(row[0] for row in rows.all())
    if namespace_codes:
        rows = await db.execute(
            select(CatalogTool.id).where(
                CatalogTool.namespace.in_(tuple(namespace_codes)),
                CatalogTool.status != CatalogObjectStatus.ARCHIVED,
            )
        )
        allowed_ids.update(row[0] for row in rows.all())
    return allowed_ids


async def scope_allows_tool(
    db: AsyncSession, scopes: Sequence[object], tool: CatalogTool,
) -> bool:
    """判断单个工具是否命中任一命名空间 / 能力包 / 工具范围。"""
    for scope in scopes:
        code = str(getattr(scope, "scope_code")).strip()
        scope_type = getattr(scope, "scope_type")
        if scope_type == ToolScopeType.TOOL and code == tool.full_code:
            return True
        if scope_type == ToolScopeType.CAPABILITY:
            linked = await db.scalar(
                select(CatalogCapabilityPackTool.id)
                .join(
                    CatalogCapabilityPack,
                    CatalogCapabilityPack.id
                    == CatalogCapabilityPackTool.pack_id,
                )
                .where(
                    CatalogCapabilityPack.pack_code == code,
                    CatalogCapabilityPack.status
                    == CatalogObjectStatus.ENABLED,
                    CatalogCapabilityPackTool.tool_id == tool.id,
                )
                .limit(1)
            )
            if linked is not None:
                return True
        if (
            scope_type == ToolScopeType.NAMESPACE
            and code == tool.namespace
        ):
            return True
    return False
