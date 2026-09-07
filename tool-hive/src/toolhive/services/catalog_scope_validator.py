"""Catalog 范围编码的共享引用校验服务（调用系统 / MCP 客户端共用）。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import CatalogObjectStatus, ToolScopeType
from toolhive.core.exceptions import ValidationError
from toolhive.models.catalog_capability_pack import CatalogCapabilityPack
from toolhive.models.catalog_tool import CatalogTool


class CatalogScopeValidator:
    """按 scope_type 批量校验工具 / 能力包 / 命名空间引用的存在性。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def validate_items(self, items: Sequence[Mapping[str, str]]) -> None:
        """校验范围编码在 Catalog 中存在且未归档（批量查询避免 N+1）。"""
        tool_codes = [
            str(item["scope_code"]).strip()
            for item in items
            if item["scope_type"] == ToolScopeType.TOOL
        ]
        pack_codes = [
            str(item["scope_code"]).strip()
            for item in items
            if item["scope_type"] == ToolScopeType.CAPABILITY
        ]
        namespace_codes = [
            str(item["scope_code"]).strip()
            for item in items
            if item["scope_type"] == ToolScopeType.NAMESPACE
        ]
        if tool_codes:
            result = await self.db.execute(
                select(CatalogTool).where(
                    (CatalogTool.namespace + "." + CatalogTool.tool_code).in_(
                        tool_codes
                    )
                )
            )
            tools = {
                (t.namespace + "." + t.tool_code): t
                for t in result.scalars().all()
            }
            for code in tool_codes:
                tool = tools.get(code)
                if tool is None:
                    raise ValidationError(f"工具范围引用了不存在的工具: {code}")
                if tool.status == CatalogObjectStatus.ARCHIVED:
                    raise ValidationError(f"工具范围引用了已归档的工具: {code}")
        if pack_codes:
            result = await self.db.execute(
                select(CatalogCapabilityPack).where(
                    CatalogCapabilityPack.pack_code.in_(pack_codes)
                )
            )
            packs = {p.pack_code: p for p in result.scalars().all()}
            for code in pack_codes:
                pack = packs.get(code)
                if pack is None:
                    raise ValidationError(
                        f"工具范围引用了不存在的能力包: {code}"
                    )
                if pack.status == CatalogObjectStatus.ARCHIVED:
                    raise ValidationError(
                        f"工具范围引用了已归档的能力包: {code}"
                    )
        if namespace_codes:
            result = await self.db.execute(
                select(CatalogTool.namespace)
                .where(
                    CatalogTool.namespace.in_(namespace_codes),
                    CatalogTool.status != CatalogObjectStatus.ARCHIVED,
                )
                .distinct()
            )
            namespaces = {row[0] for row in result.all()}
            for code in namespace_codes:
                if code not in namespaces:
                    raise ValidationError(
                        f"命名空间范围不存在可用（非归档）工具: {code}"
                    )

    async def reference_map(
        self, scopes: Sequence[object],
    ) -> dict[tuple[str, str], tuple[bool, bool]]:
        """返回 (scope_type, scope_code) → (引用存在, 是否全部归档) 映射。"""
        tool_codes: list[str] = []
        pack_codes: list[str] = []
        namespace_codes: list[str] = []
        for scope in scopes:
            scope_type = getattr(scope, "scope_type")
            code = str(getattr(scope, "scope_code")).strip()
            if scope_type == ToolScopeType.TOOL:
                tool_codes.append(code)
            elif scope_type == ToolScopeType.CAPABILITY:
                pack_codes.append(code)
            elif scope_type == ToolScopeType.NAMESPACE:
                namespace_codes.append(code)
        result: dict[tuple[str, str], tuple[bool, bool]] = {}
        if tool_codes:
            rows = await self.db.execute(
                select(CatalogTool).where(
                    (CatalogTool.namespace + "." + CatalogTool.tool_code).in_(
                        tool_codes
                    )
                )
            )
            for tool in rows.scalars().all():
                code = tool.namespace + "." + tool.tool_code
                result[(ToolScopeType.TOOL, code)] = (
                    True,
                    tool.status == CatalogObjectStatus.ARCHIVED,
                )
        if pack_codes:
            rows = await self.db.execute(
                select(CatalogCapabilityPack).where(
                    CatalogCapabilityPack.pack_code.in_(pack_codes)
                )
            )
            for pack in rows.scalars().all():
                result[(ToolScopeType.CAPABILITY, pack.pack_code)] = (
                    True,
                    pack.status == CatalogObjectStatus.ARCHIVED,
                )
        if namespace_codes:
            rows = await self.db.execute(
                select(CatalogTool.namespace, CatalogTool.status).where(
                    CatalogTool.namespace.in_(namespace_codes)
                )
            )
            grouped: dict[str, set[str]] = {}
            for namespace, status in rows.all():
                grouped.setdefault(namespace, set()).add(status)
            for namespace, statuses in grouped.items():
                result[(ToolScopeType.NAMESPACE, namespace)] = (
                    True,
                    all(
                        s == CatalogObjectStatus.ARCHIVED
                        for s in statuses
                    ),
                )
        for scope in scopes:
            key = (
                getattr(scope, "scope_type"),
                str(getattr(scope, "scope_code")).strip(),
            )
            if key not in result:
                result[key] = (False, False)
        return result
