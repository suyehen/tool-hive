"""Catalog 能力包管理服务。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import CatalogObjectStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.base import gen_id
from toolhive.models.caller_system import CallerSystem
from toolhive.models.catalog_capability_pack import CatalogCapabilityPack
from toolhive.models.catalog_capability_pack_system import (
    CatalogCapabilityPackSystem,
)
from toolhive.models.catalog_capability_pack_tool import CatalogCapabilityPackTool
from toolhive.models.catalog_tool import CatalogTool
from toolhive.services.audit_service import AuditService, get_current_operator_id
from toolhive.services.catalog_common import validate_object_code
from toolhive.services.catalog_events import emit_catalog_index_event


class CatalogCapabilityService:
    """能力包 CRUD、工具关联与调用系统授权关联管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_packs(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        keyword: str | None = None,
        status: str | None = None,
    ) -> tuple[list[CatalogCapabilityPack], int]:
        """分页查询能力包，支持关键词 / 状态过滤。"""
        conditions = []
        kw = keyword.strip() if keyword else ""
        if kw:
            pattern = f"%{kw}%"
            conditions.append(
                or_(
                    CatalogCapabilityPack.pack_code.ilike(pattern),
                    CatalogCapabilityPack.name.ilike(pattern),
                )
            )
        if status:
            conditions.append(CatalogCapabilityPack.status == status)
        total = await self.db.scalar(
            select(func.count())
            .select_from(CatalogCapabilityPack)
            .where(*conditions)
        )
        result = await self.db.execute(
            select(CatalogCapabilityPack)
            .where(*conditions)
            .order_by(CatalogCapabilityPack.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_pack(self, pack_id: str) -> CatalogCapabilityPack:
        """按主键查询能力包，不存在时抛 404。"""
        pack = await self.db.get(CatalogCapabilityPack, pack_id)
        if pack is None:
            raise NotFoundError(f"能力包不存在: {pack_id}")
        return pack

    @transactional()
    async def create_pack(
        self, *, pack_code: str, name: str, description: str | None = None,
    ) -> CatalogCapabilityPack:
        """创建能力包：编码全局唯一。"""
        code = validate_object_code(pack_code, "能力包编码")
        name_value = (name or "").strip()
        if not name_value:
            raise ValidationError("能力包名称不能为空")
        existing = await self.db.scalar(
            select(CatalogCapabilityPack).where(
                CatalogCapabilityPack.pack_code == code
            )
        )
        if existing:
            raise ConflictError(f"能力包编码 '{code}' 已被使用")
        pack = CatalogCapabilityPack(
            pack_code=code,
            name=name_value,
            description=description,
            status=CatalogObjectStatus.ENABLED,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(pack)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_capability.create",
            object_type="capability_pack",
            object_id=pack.id,
            after_summary={"pack_code": code, "name": name_value},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.capability.changed",
            object_type="capability_pack",
            object_id=pack.id,
            object_version=str(pack.row_version),
        )
        return pack

    @transactional()
    async def update_pack(
        self,
        pack_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        expected_row_version: int | None = None,
    ) -> CatalogCapabilityPack:
        """更新能力包资料（仅更新显式提供的字段）。"""
        pack = await self.get_pack(pack_id)
        if pack.status == CatalogObjectStatus.ARCHIVED:
            raise ConflictError("已归档的能力包不可修改")
        if (
            expected_row_version is not None
            and pack.row_version != expected_row_version
        ):
            raise ConflictError("数据已被他人修改，请刷新后重试")
        if name is not None:
            name_value = name.strip()
            if not name_value:
                raise ValidationError("能力包名称不能为空")
            pack.name = name_value
        if description is not None:
            pack.description = description
        pack.update_time = datetime.now(UTC)
        pack.update_by = get_current_operator_id()
        pack.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_capability.update",
            object_type="capability_pack",
            object_id=pack_id,
            after_summary={"name": pack.name},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.capability.changed",
            object_type="capability_pack",
            object_id=pack_id,
            object_version=str(pack.row_version),
        )
        return pack

    @transactional()
    async def set_status(self, pack_id: str, status: str) -> CatalogCapabilityPack:
        """启停 / 归档能力包；归档不可恢复。"""
        pack = await self.get_pack(pack_id)
        if status not in tuple(CatalogObjectStatus):
            raise ValidationError("无效的状态")
        if pack.status == CatalogObjectStatus.ARCHIVED:
            raise ConflictError("已归档的能力包不可变更状态")
        if pack.status == status:
            raise ConflictError(f"能力包已处于 {status} 状态")
        pack.status = status
        pack.update_time = datetime.now(UTC)
        pack.update_by = get_current_operator_id()
        pack.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_capability.status",
            object_type="capability_pack",
            object_id=pack_id,
            after_summary={"status": status},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.capability.changed",
            object_type="capability_pack",
            object_id=pack_id,
            object_version=str(pack.row_version),
        )
        return pack

    async def list_pack_tools(self, pack_id: str) -> list[CatalogTool]:
        """查询能力包关联的工具列表。"""
        await self.get_pack(pack_id)
        result = await self.db.execute(
            select(CatalogTool)
            .join(
                CatalogCapabilityPackTool,
                CatalogCapabilityPackTool.tool_id == CatalogTool.id,
            )
            .where(CatalogCapabilityPackTool.pack_id == pack_id)
            .order_by(CatalogTool.namespace, CatalogTool.tool_code)
        )
        return list(result.scalars().all())

    @transactional()
    async def replace_pack_tools(
        self, pack_id: str, tool_ids: list[str],
    ) -> list[CatalogTool]:
        """全量替换能力包的工具关联（先校验后写入）。"""
        await self.get_pack(pack_id)
        unique_ids = list(dict.fromkeys(tool_ids))
        if unique_ids:
            result = await self.db.execute(
                select(CatalogTool).where(CatalogTool.id.in_(unique_ids))
            )
            tools = list(result.scalars().all())
            found = {tool.id for tool in tools}
            missing = [tid for tid in unique_ids if tid not in found]
            if missing:
                raise ValidationError(f"以下工具不存在: {', '.join(missing)}")
            archived = [
                tool.full_code
                for tool in tools
                if tool.status == CatalogObjectStatus.ARCHIVED
            ]
            if archived:
                raise ValidationError(
                    f"以下工具已归档，不能关联: {', '.join(archived)}"
                )
        else:
            tools = []
        await self.db.execute(
            delete(CatalogCapabilityPackTool).where(
                CatalogCapabilityPackTool.pack_id == pack_id
            )
        )
        now = datetime.now(UTC)
        operator_id = get_current_operator_id()
        rows = [
            {
                "id": gen_id(),
                "pack_id": pack_id,
                "tool_id": tool_id,
                "create_time": now,
                "create_by": operator_id,
            }
            for tool_id in unique_ids
        ]
        if rows:
            await self.db.execute(
                insert(CatalogCapabilityPackTool).values(rows)
            )
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_capability.replace_tools",
            object_type="capability_pack",
            object_id=pack_id,
            after_summary={"tool_count": len(unique_ids)},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.capability.changed",
            object_type="capability_pack",
            object_id=pack_id,
        )
        return tools

    async def list_pack_systems(self, pack_id: str) -> list[CallerSystem]:
        """查询能力包授权的调用系统列表。"""
        await self.get_pack(pack_id)
        result = await self.db.execute(
            select(CallerSystem)
            .join(
                CatalogCapabilityPackSystem,
                CatalogCapabilityPackSystem.system_id == CallerSystem.system_id,
            )
            .where(CatalogCapabilityPackSystem.pack_id == pack_id)
            .order_by(CallerSystem.system_id)
        )
        return list(result.scalars().all())

    @transactional()
    async def replace_pack_systems(
        self, pack_id: str, system_ids: list[str],
    ) -> list[CallerSystem]:
        """全量替换能力包的调用系统授权（先校验后写入）。"""
        await self.get_pack(pack_id)
        unique_ids = list(dict.fromkeys(system_ids))
        if unique_ids:
            result = await self.db.execute(
                select(CallerSystem).where(CallerSystem.system_id.in_(unique_ids))
            )
            systems = list(result.scalars().all())
            found = {system.system_id for system in systems}
            missing = [sid for sid in unique_ids if sid not in found]
            if missing:
                raise ValidationError(f"以下调用系统不存在: {', '.join(missing)}")
        else:
            systems = []
        await self.db.execute(
            delete(CatalogCapabilityPackSystem).where(
                CatalogCapabilityPackSystem.pack_id == pack_id
            )
        )
        now = datetime.now(UTC)
        operator_id = get_current_operator_id()
        rows = [
            {
                "id": gen_id(),
                "pack_id": pack_id,
                "system_id": system_id,
                "create_time": now,
                "create_by": operator_id,
            }
            for system_id in unique_ids
        ]
        if rows:
            await self.db.execute(
                insert(CatalogCapabilityPackSystem).values(rows)
            )
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_capability.replace_systems",
            object_type="capability_pack",
            object_id=pack_id,
            after_summary={"system_count": len(unique_ids)},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.capability.changed",
            object_type="capability_pack",
            object_id=pack_id,
        )
        return systems
