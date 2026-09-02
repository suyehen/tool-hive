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
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.errors import (
    RUNTIME_SCOPE_NOT_ALLOWED,
    RUNTIME_TOOL_NOT_AVAILABLE,
    RUNTIME_TOOL_NOT_FOUND,
)

_WRITE_METHODS = ("POST", "PUT", "DELETE")


def catalog_object_runnable(status: str | None) -> bool:
    """Catalog 对象是否可运行：仅 ENABLED 状态参与运行时授权与执行。"""
    return status == CatalogObjectStatus.ENABLED


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

    async def resolve_tool(
        self,
        system_id: str,
        full_code: str | None = None,
        *,
        tool_id: str | None = None,
        version: str | None = None,
    ) -> ControlDecision:
        """精确解析工具：按完整标识或工具 ID 查询，支持显式版本。"""
        base = await self._base_resolve_tool(
            system_id, full_code, tool_id=tool_id,
        )
        if not base.allowed:
            return base
        assert base.tool is not None
        tool = base.tool
        selected = await self._select_published_version(tool, version)
        if selected is None:
            message = (
                "工具未配置默认已发布版本，请显式指定版本"
                if version is None
                else f"版本 {version} 未发布或不存在"
            )
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, message,
                discoverable=True, tool=tool,
            )
        decision = ControlDecision(
            allowed=True,
            discoverable=True,
            tool=tool,
            version=selected,
        )
        # 解析边界同步完成执行绑定与确认需求计算（与 Execute 共用同一来源）
        if tool.executable:
            control = await self._binding_control(tool, selected)
            if control is None:
                return self._denied(
                    RUNTIME_TOOL_NOT_AVAILABLE,
                    "工具执行通道不可用：Provider 已停用或不存在",
                    discoverable=True, tool=tool,
                )
            decision.binding, decision.confirmation_required = control
        return decision

    async def _base_resolve_tool(
        self,
        system_id: str,
        full_code: str | None = None,
        *,
        tool_id: str | None = None,
    ) -> ControlDecision:
        """解析工具基础可用性：存在性、状态与范围（不含版本选择）。"""
        if tool_id is not None:
            tool = await self.db.get(CatalogTool, tool_id)
            label = tool_id
        elif full_code:
            tool = await self.db.scalar(
                select(CatalogTool).where(
                    (CatalogTool.namespace + "." + CatalogTool.tool_code) == full_code
                )
            )
            label = full_code
        else:
            return self._denied(RUNTIME_TOOL_NOT_FOUND, "工具不存在")
        if tool is None:
            return self._denied(
                RUNTIME_TOOL_NOT_FOUND, f"工具不存在: {label}",
            )
        if tool.status != CatalogObjectStatus.ENABLED or not tool.discoverable:
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具不可发现", tool=tool,
            )
        if not await self._tool_in_scope(system_id, tool):
            return self._denied(
                RUNTIME_SCOPE_NOT_ALLOWED,
                f"调用系统无权访问工具: {tool.full_code}",
                tool=tool,
            )
        return ControlDecision(
            allowed=True,
            discoverable=True,
            tool=tool,
        )

    async def evaluate_executable(
        self,
        system_id: str,
        full_code: str,
        *,
        version: str | None = None,
    ) -> ControlDecision:
        """执行决策：在可发现基础上校验可执行标志、版本与确认条件。"""
        base = await self._base_resolve_tool(system_id, full_code)
        if not base.allowed:
            return base
        tool = base.tool
        assert tool is not None
        if not tool.executable:
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具不可执行",
                discoverable=True, tool=tool,
            )
        # 版本选择与 Resolve 共用同一决策：未传版本只认默认版本
        selected = await self._select_published_version(tool, version)
        if selected is None:
            message = (
                "工具未配置默认已发布版本，请显式指定版本"
                if version is None
                else f"版本 {version} 未发布或不存在"
            )
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE, message,
                discoverable=True, tool=tool,
            )
        control = await self._binding_control(tool, selected)
        if control is None:
            return self._denied(
                RUNTIME_TOOL_NOT_AVAILABLE,
                "工具执行通道不可用：Provider 已停用或不存在",
                discoverable=True, tool=tool,
            )
        binding, confirmation_required = control
        return ControlDecision(
            allowed=True,
            discoverable=True,
            executable=True,
            confirmation_required=confirmation_required,
            tool=tool,
            version=selected,
            binding=binding,
        )

    async def _binding_control(
        self,
        tool: CatalogTool,
        version: CatalogToolVersion,
    ) -> tuple[CatalogExecutionBinding | None, bool] | None:
        """校验版本执行绑定与 Provider 状态并计算确认需求；通道不可用时返回 None。"""
        binding = await self._get_binding(version.id)
        if binding is None:
            return binding, False
        provider = await self.db.get(CatalogProvider, binding.provider_id)
        if not catalog_object_runnable(getattr(provider, "status", None)):
            return None
        return binding, self._confirmation_required(tool, binding)

    @staticmethod
    def _confirmation_required(
        tool: CatalogTool, binding: CatalogExecutionBinding | None,
    ) -> bool:
        """统一确认需求：高风险或写操作执行需要确认。"""
        return (
            tool.risk_level == RiskLevel.HIGH
            or bool(binding and binding.method in _WRITE_METHODS)
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
                        == CatalogObjectStatus.ENABLED,
                    )
                )
            ).all()
            allowed_ids.update(row[0] for row in rows)
        # 仅默认版本（PUBLISHED）参与 Discover 默认可见性
        published_ids: set[str] = set()
        if allowed_ids:
            version_rows = (
                await self.db.execute(
                    select(CatalogToolVersion.tool_id)
                    .join(
                        CatalogTool,
                        CatalogTool.id == CatalogToolVersion.tool_id,
                    )
                    .where(
                        CatalogTool.id.in_(tuple(allowed_ids)),
                        CatalogTool.default_version_id == CatalogToolVersion.id,
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
            and tool.status == CatalogObjectStatus.ENABLED
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
                        == CatalogObjectStatus.ENABLED,
                        CatalogCapabilityPackTool.tool_id == tool.id,
                    )
                    .limit(1)
                )
                if linked is not None:
                    return True
        return False

    async def _select_published_version(
        self, tool: CatalogTool,
        version: str | None,
    ) -> CatalogToolVersion | None:
        """选择已发布版本：显式版本精确匹配；缺省时只认默认版本，不回退。"""
        if version is not None:
            return await self.db.scalar(
                select(CatalogToolVersion).where(
                    CatalogToolVersion.tool_id == tool.id,
                    CatalogToolVersion.version == version,
                    CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
                )
            )
        if not tool.default_version_id:
            return None
        row = await self.db.get(CatalogToolVersion, tool.default_version_id)
        if row is not None and row.status == ToolVersionStatus.PUBLISHED:
            return row
        return None

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
