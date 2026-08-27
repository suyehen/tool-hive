"""工具调用控制：可发现 / 可执行决策与确认条件判断。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import (
    CatalogObjectStatus,
    RiskLevel,
    ToolScopeStatus,
    ToolScopeType,
    ToolVersionStatus,
)
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.models.catalog_capability_pack import CatalogCapabilityPack
from toolhive.models.catalog_capability_pack_tool import CatalogCapabilityPackTool
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.errors import (
    RUNTIME_SCOPE_NOT_ALLOWED,
    RUNTIME_TOOL_NOT_AVAILABLE,
    RUNTIME_TOOL_NOT_FOUND,
)

_WRITE_METHODS = ("POST", "PUT", "DELETE")


@dataclass
class ControlDecision:
    """一次调用控制决策结果（默认拒绝）。"""

    allowed: bool = False
    discoverable: bool = False
    executable: bool = False
    confirmation_required: bool = False
    tool: CatalogTool | None = None
    version: CatalogToolVersion | None = None
    binding: CatalogExecutionBinding | None = None
    error_code: str | None = None
    error_message: str | None = None


class CallControlService:
    """按调用系统 × 工具范围 × Catalog 状态计算可发现 / 可执行集合。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_tool(self, system_id: str, full_code: str) -> ControlDecision:
        """精确解析工具：存在性、可发现性、调用系统范围与发布状态。"""
        tool = await self.db.scalar(
            select(CatalogTool).where(
                (CatalogTool.namespace + "." + CatalogTool.tool_code) == full_code
            )
        )
        if tool is None:
            return self._denied(
                RUNTIME_TOOL_NOT_FOUND, f"工具不存在: {full_code}",
            )
        if tool.status == CatalogObjectStatus.ARCHIVED or not tool.discoverable:
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具不可发现", tool=tool,
            )
        if not await self._tool_in_scope(system_id, tool):
            return self._denied(
                RUNTIME_SCOPE_NOT_ALLOWED,
                f"调用系统无权访问工具: {full_code}",
                tool=tool,
            )
        default_version = await self._default_published_version(tool)
        if default_version is None:
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具暂无已发布版本", tool=tool,
            )
        return ControlDecision(
            allowed=True,
            discoverable=True,
            tool=tool,
            version=default_version,
        )

    async def evaluate_executable(
        self,
        system_id: str,
        full_code: str,
        *,
        version: str | None = None,
    ) -> ControlDecision:
        """执行决策：在可发现基础上校验可执行标志、版本与确认条件。"""
        base = await self.resolve_tool(system_id, full_code)
        if not base.allowed:
            return base
        tool = base.tool
        assert tool is not None
        if not tool.executable:
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具不可执行",
                discoverable=True, tool=tool,
            )
        if version is not None:
            selected = await self.db.scalar(
                select(CatalogToolVersion).where(
                    CatalogToolVersion.tool_id == tool.id,
                    CatalogToolVersion.version == version,
                    CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
                )
            )
            if selected is None:
                return self._denied(
                    RUNTIME_TOOL_NOT_AVAILABLE,
                    f"版本 {version} 未发布或不存在",
                    discoverable=True, tool=tool,
                )
        else:
            selected = base.version
            if selected is None or selected.id != tool.default_version_id:
                return self._denied(
                    RUNTIME_TOOL_NOT_AVAILABLE,
                    "工具未配置默认版本，请显式指定版本",
                    discoverable=True, tool=tool,
                )
        binding = await self._get_binding(selected.id)
        confirmation_required = (
            tool.risk_level == RiskLevel.HIGH
            or bool(binding and binding.method in _WRITE_METHODS)
        )
        return ControlDecision(
            allowed=True,
            discoverable=True,
            executable=True,
            confirmation_required=confirmation_required,
            tool=tool,
            version=selected,
            binding=binding,
        )

    async def list_discoverable_tools(
        self, system_id: str,
    ) -> list[CatalogTool]:
        """计算调用系统当前可发现工具集合（范围 × 发布状态 × 可发现标志）。"""
        result = await self.db.execute(
            select(CallerToolScope).where(
                CallerToolScope.system_id == system_id,
                CallerToolScope.status == ToolScopeStatus.ACTIVE,
            )
        )
        scopes = list(result.scalars().all())
        tool_codes = {
            s.scope_code for s in scopes if s.scope_type == ToolScopeType.TOOL
        }
        pack_codes = {
            s.scope_code for s in scopes if s.scope_type == ToolScopeType.CAPABILITY
        }
        all_tools = list(
            (
                await self.db.execute(
                    select(CatalogTool).where(
                        CatalogTool.status != CatalogObjectStatus.ARCHIVED
                    )
                )
            )
            .scalars()
            .all()
        )
        allowed_ids = {
            tool.id for tool in all_tools if tool.full_code in tool_codes
        }
        if pack_codes:
            rows = (
                await self.db.execute(
                    select(CatalogCapabilityPackTool.tool_id)
                    .join(
                        CatalogCapabilityPack,
                        CatalogCapabilityPack.id
                        == CatalogCapabilityPackTool.pack_id,
                    )
                    .where(
                        CatalogCapabilityPack.pack_code.in_(tuple(pack_codes)),
                        CatalogCapabilityPack.status
                        != CatalogObjectStatus.ARCHIVED,
                    )
                )
            ).all()
            allowed_ids.update(row[0] for row in rows)
        published_ids: set[str] = set()
        if allowed_ids:
            version_rows = (
                await self.db.execute(
                    select(CatalogToolVersion.tool_id).where(
                        CatalogToolVersion.tool_id.in_(tuple(allowed_ids)),
                        CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
                    )
                )
            ).all()
            published_ids = {row[0] for row in version_rows}
        return [
            tool
            for tool in all_tools
            if tool.id in allowed_ids
            and tool.id in published_ids
            and tool.discoverable
        ]

    async def _tool_in_scope(self, system_id: str, tool: CatalogTool) -> bool:
        """判断工具是否在调用系统的工具 / 能力包范围内。"""
        result = await self.db.execute(
            select(CallerToolScope).where(
                CallerToolScope.system_id == system_id,
                CallerToolScope.status == ToolScopeStatus.ACTIVE,
            )
        )
        scopes = list(result.scalars().all())
        for scope in scopes:
            if (
                scope.scope_type == ToolScopeType.TOOL
                and scope.scope_code == tool.full_code
            ):
                return True
            if scope.scope_type == ToolScopeType.CAPABILITY:
                linked = await self.db.scalar(
                    select(CatalogCapabilityPackTool.id)
                    .join(
                        CatalogCapabilityPack,
                        CatalogCapabilityPack.id
                        == CatalogCapabilityPackTool.pack_id,
                    )
                    .where(
                        CatalogCapabilityPack.pack_code == scope.scope_code,
                        CatalogCapabilityPack.status
                        != CatalogObjectStatus.ARCHIVED,
                        CatalogCapabilityPackTool.tool_id == tool.id,
                    )
                    .limit(1)
                )
                if linked is not None:
                    return True
        return False

    async def _default_published_version(
        self, tool: CatalogTool,
    ) -> CatalogToolVersion | None:
        """返回工具默认版本（必须已发布），未配置时回退最新已发布版本。"""
        if tool.default_version_id:
            version = await self.db.get(CatalogToolVersion, tool.default_version_id)
            if (
                version is not None
                and version.status == ToolVersionStatus.PUBLISHED
            ):
                return version
        return await self.db.scalar(
            select(CatalogToolVersion)
            .where(
                CatalogToolVersion.tool_id == tool.id,
                CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
            )
            .order_by(CatalogToolVersion.create_time.desc())
            .limit(1)
        )

    async def _get_binding(
        self, version_id: str,
    ) -> CatalogExecutionBinding | None:
        """查询版本执行绑定。"""
        return await self.db.scalar(
            select(CatalogExecutionBinding).where(
                CatalogExecutionBinding.version_id == version_id
            )
        )

    @staticmethod
    def _denied(
        error_code: str,
        error_message: str,
        *,
        tool: CatalogTool | None = None,
        discoverable: bool = False,
    ) -> ControlDecision:
        """构造默认拒绝决策。"""
        return ControlDecision(
            allowed=False,
            discoverable=discoverable,
            tool=tool,
            error_code=error_code,
            error_message=error_message,
        )
