"""Catalog 工具管理服务。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import CatalogObjectStatus, RiskLevel, ToolVersionStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.services.audit_service import AuditService, get_current_operator_id
from toolhive.services.catalog_common import validate_namespace, validate_tool_code
from toolhive.services.catalog_events import emit_catalog_index_event


def split_full_code(full_code: str) -> tuple[str, str]:
    """解析完整工具标识 ``{namespace}.{tool_code}``。"""
    parts = (full_code or "").rsplit(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValidationError(f"无效的工具完整标识: {full_code}")
    return parts[0], parts[1]


class CatalogToolService:
    """工具 CRUD、唯一性与启停 / 归档管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_tools(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        keyword: str | None = None,
        namespace: str | None = None,
        status: str | None = None,
        risk_level: str | None = None,
    ) -> tuple[list[CatalogTool], int]:
        """分页查询工具，支持关键词 / 命名空间 / 状态 / 风险等级过滤。"""
        conditions = []
        kw = keyword.strip() if keyword else ""
        if kw:
            pattern = f"%{kw}%"
            conditions.append(
                or_(
                    CatalogTool.name.ilike(pattern),
                    CatalogTool.tool_code.ilike(pattern),
                    CatalogTool.namespace.ilike(pattern),
                    CatalogTool.description.ilike(pattern),
                )
            )
        if namespace:
            conditions.append(CatalogTool.namespace == namespace)
        if status:
            conditions.append(CatalogTool.status == status)
        if risk_level:
            conditions.append(CatalogTool.risk_level == risk_level)
        total = await self.db.scalar(
            select(func.count()).select_from(CatalogTool).where(*conditions)
        )
        result = await self.db.execute(
            select(CatalogTool)
            .where(*conditions)
            .order_by(CatalogTool.namespace, CatalogTool.tool_code)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_tool(self, tool_id: str) -> CatalogTool:
        """按主键查询工具，不存在时抛 404。"""
        tool = await self.db.get(CatalogTool, tool_id)
        if tool is None:
            raise NotFoundError(f"工具不存在: {tool_id}")
        return tool

    async def get_by_full_code(self, full_code: str) -> CatalogTool | None:
        """按完整工具标识查询（用于调用系统范围引用校验）。"""
        namespace, tool_code = split_full_code(full_code)
        return await self.db.scalar(
            select(CatalogTool).where(
                CatalogTool.namespace == namespace,
                CatalogTool.tool_code == tool_code,
            )
        )

    @transactional()
    async def create_tool(
        self,
        *,
        namespace: str,
        tool_code: str,
        name: str,
        description: str | None = None,
        risk_level: str = RiskLevel.LOW,
        discoverable: bool = True,
        executable: bool = True,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
    ) -> CatalogTool:
        """创建工具：命名空间 + 工具编码唯一。"""
        ns = validate_namespace(namespace)
        code = validate_tool_code(tool_code)
        name_value = (name or "").strip()
        if not name_value:
            raise ValidationError("工具名称不能为空")
        if risk_level not in tuple(RiskLevel):
            raise ValidationError("风险等级必须是 low / medium / high")
        if input_schema is not None and not isinstance(input_schema, dict):
            raise ValidationError("input_schema 必须是 JSON 对象")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise ValidationError("output_schema 必须是 JSON 对象")
        existing = await self.db.scalar(
            select(CatalogTool).where(
                CatalogTool.namespace == ns,
                CatalogTool.tool_code == code,
            )
        )
        if existing:
            raise ConflictError(f"工具 '{ns}.{code}' 已存在")
        tool = CatalogTool(
            namespace=ns,
            tool_code=code,
            name=name_value,
            description=description,
            risk_level=risk_level,
            discoverable=discoverable,
            executable=executable,
            input_schema=input_schema,
            output_schema=output_schema,
            status=CatalogObjectStatus.ENABLED,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(tool)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_tool.create",
            object_type="catalog_tool",
            object_id=tool.id,
            after_summary={
                "namespace": ns,
                "tool_code": code,
                "name": name_value,
                "risk_level": risk_level,
            },
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.tool.changed",
            object_type="catalog_tool",
            object_id=tool.id,
            object_version=str(tool.row_version),
            payload={"namespace": ns, "tool_code": code},
        )
        return tool

    @transactional()
    async def update_tool(
        self,
        tool_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        risk_level: str | None = None,
        discoverable: bool | None = None,
        executable: bool | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        expected_row_version: int | None = None,
    ) -> CatalogTool:
        """更新工具资料与 Schema（仅更新显式提供的字段）。"""
        tool = await self.get_tool(tool_id)
        if tool.status == CatalogObjectStatus.ARCHIVED:
            raise ConflictError("已归档的工具不可修改")
        if (
            expected_row_version is not None
            and tool.row_version != expected_row_version
        ):
            raise ConflictError("数据已被他人修改，请刷新后重试")
        if name is not None:
            name_value = name.strip()
            if not name_value:
                raise ValidationError("工具名称不能为空")
            tool.name = name_value
        if description is not None:
            tool.description = description
        if risk_level is not None:
            if risk_level not in tuple(RiskLevel):
                raise ValidationError("风险等级必须是 low / medium / high")
            tool.risk_level = risk_level
        if discoverable is not None:
            tool.discoverable = discoverable
        if executable is not None:
            tool.executable = executable
        if input_schema is not None:
            if not isinstance(input_schema, dict):
                raise ValidationError("input_schema 必须是 JSON 对象")
            tool.input_schema = input_schema
        if output_schema is not None:
            if not isinstance(output_schema, dict):
                raise ValidationError("output_schema 必须是 JSON 对象")
            tool.output_schema = output_schema
        tool.update_time = datetime.now(UTC)
        tool.update_by = get_current_operator_id()
        tool.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_tool.update",
            object_type="catalog_tool",
            object_id=tool_id,
            after_summary={"name": tool.name, "risk_level": tool.risk_level},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.tool.changed",
            object_type="catalog_tool",
            object_id=tool_id,
            object_version=str(tool.row_version),
        )
        return tool

    @transactional()
    async def set_status(self, tool_id: str, status: str) -> CatalogTool:
        """启停 / 归档工具；归档前要求版本均处于草稿 / 驳回 / 已归档。"""
        tool = await self.get_tool(tool_id)
        if status not in tuple(CatalogObjectStatus):
            raise ValidationError("无效的状态")
        if tool.status == CatalogObjectStatus.ARCHIVED:
            raise ConflictError("已归档的工具不可变更状态")
        if tool.status == status:
            raise ConflictError(f"工具已处于 {status} 状态")
        if status == CatalogObjectStatus.ARCHIVED:
            active = await self.db.execute(
                select(CatalogToolVersion.id)
                .where(
                    CatalogToolVersion.tool_id == tool_id,
                    CatalogToolVersion.status.notin_(
                        (
                            ToolVersionStatus.DRAFT,
                            ToolVersionStatus.REJECTED,
                            ToolVersionStatus.ARCHIVED,
                        )
                    ),
                )
                .limit(1)
            )
            if active.first() is not None:
                raise ConflictError(
                    "存在审核中 / 已发布 / 已停用 / 已撤回的版本，"
                    "请先撤回、停用或归档这些版本"
                )
        tool.status = status
        tool.update_time = datetime.now(UTC)
        tool.update_by = get_current_operator_id()
        tool.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_tool.status",
            object_type="catalog_tool",
            object_id=tool_id,
            after_summary={"status": status},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.tool.changed",
            object_type="catalog_tool",
            object_id=tool_id,
            object_version=str(tool.row_version),
        )
        return tool
