"""Catalog Provider 管理服务。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import CatalogObjectStatus, ProviderType, ToolVersionStatus
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.services.audit_service import AuditService, get_current_operator_id
from toolhive.services.catalog_common import (
    validate_http_target_config,
    validate_object_code,
)
from toolhive.services.catalog_events import emit_catalog_index_event


class CatalogProviderService:
    """Provider 生命周期与目标安全配置管理。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_providers(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        keyword: str | None = None,
        status: str | None = None,
        provider_type: str | None = None,
    ) -> tuple[list[CatalogProvider], int]:
        """分页查询 Provider，支持关键词 / 状态 / 类型过滤。"""
        conditions = []
        kw = keyword.strip() if keyword else ""
        if kw:
            pattern = f"%{kw}%"
            conditions.append(
                or_(
                    CatalogProvider.provider_code.ilike(pattern),
                    CatalogProvider.name.ilike(pattern),
                )
            )
        if status:
            conditions.append(CatalogProvider.status == status)
        if provider_type:
            conditions.append(CatalogProvider.provider_type == provider_type)
        total = await self.db.scalar(
            select(func.count()).select_from(CatalogProvider).where(*conditions)
        )
        result = await self.db.execute(
            select(CatalogProvider)
            .where(*conditions)
            .order_by(CatalogProvider.create_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all()), total or 0

    async def get_provider(self, provider_id: str) -> CatalogProvider:
        """按主键查询 Provider，不存在时抛 404。"""
        provider = await self.db.get(CatalogProvider, provider_id)
        if provider is None:
            raise NotFoundError(f"Provider 不存在: {provider_id}")
        return provider

    @transactional()
    async def create_provider(
        self,
        *,
        provider_code: str,
        name: str,
        provider_type: str,
        description: str | None = None,
        target_security_config: dict | None = None,
    ) -> CatalogProvider:
        """创建 Provider：编码唯一，http 类型校验目标安全配置。"""
        code = validate_object_code(provider_code, "Provider 编码")
        name_value = (name or "").strip()
        if not name_value:
            raise ValidationError("Provider 名称不能为空")
        if provider_type not in tuple(ProviderType):
            raise ValidationError("Provider 类型必须是 builtin 或 http")
        existing = await self.db.scalar(
            select(CatalogProvider).where(CatalogProvider.provider_code == code)
        )
        if existing:
            raise ConflictError(f"Provider 编码 '{code}' 已被使用")
        config = (
            validate_http_target_config(target_security_config)
            if provider_type == ProviderType.HTTP
            else None
        )
        provider = CatalogProvider(
            provider_code=code,
            name=name_value,
            provider_type=provider_type,
            description=description,
            target_security_config=config,
            status=CatalogObjectStatus.ENABLED,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(provider)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_provider.create",
            object_type="catalog_provider",
            object_id=provider.id,
            after_summary={
                "provider_code": code,
                "name": name_value,
                "provider_type": provider_type,
            },
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.provider.changed",
            object_type="catalog_provider",
            object_id=provider.id,
            object_version=str(provider.row_version),
        )
        return provider

    @transactional()
    async def update_provider(
        self,
        provider_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        target_security_config: dict | None = None,
        expected_row_version: int | None = None,
    ) -> CatalogProvider:
        """更新 Provider 资料与目标安全配置（仅更新显式提供的字段）。"""
        provider = await self.get_provider(provider_id)
        if provider.status == CatalogObjectStatus.ARCHIVED:
            raise ConflictError("已归档的 Provider 不可修改")
        if (
            expected_row_version is not None
            and provider.row_version != expected_row_version
        ):
            raise ConflictError("数据已被他人修改，请刷新后重试")
        if name is not None:
            name_value = name.strip()
            if not name_value:
                raise ValidationError("Provider 名称不能为空")
            provider.name = name_value
        if description is not None:
            provider.description = description
        if target_security_config is not None:
            if provider.provider_type != ProviderType.HTTP:
                raise ValidationError("builtin 类型 Provider 不需要目标安全配置")
            provider.target_security_config = validate_http_target_config(
                target_security_config
            )
        provider.update_time = datetime.now(UTC)
        provider.update_by = get_current_operator_id()
        provider.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_provider.update",
            object_type="catalog_provider",
            object_id=provider_id,
            after_summary={
                "name": provider.name,
                "provider_type": provider.provider_type,
            },
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.provider.changed",
            object_type="catalog_provider",
            object_id=provider_id,
            object_version=str(provider.row_version),
        )
        return provider

    @transactional()
    async def set_status(
        self, provider_id: str, status: str,
    ) -> CatalogProvider:
        """启停 / 归档 Provider；归档不可恢复，且存在有效绑定时拒绝。"""
        provider = await self.get_provider(provider_id)
        if status not in tuple(CatalogObjectStatus):
            raise ValidationError("无效的状态")
        if provider.status == CatalogObjectStatus.ARCHIVED:
            raise ConflictError("已归档的 Provider 不可变更状态")
        if provider.status == status:
            raise ConflictError(f"Provider 已处于 {status} 状态")
        if status == CatalogObjectStatus.ARCHIVED:
            binding = await self.db.execute(
                select(CatalogExecutionBinding.id)
                .join(
                    CatalogToolVersion,
                    CatalogToolVersion.id == CatalogExecutionBinding.version_id,
                )
                .where(
                    CatalogExecutionBinding.provider_id == provider_id,
                    CatalogToolVersion.status != ToolVersionStatus.ARCHIVED,
                )
                .limit(1)
            )
            if binding.first() is not None:
                raise ConflictError(
                    "该 Provider 仍被未归档的工具版本绑定，请先归档相关版本"
                )
        provider.status = status
        provider.update_time = datetime.now(UTC)
        provider.update_by = get_current_operator_id()
        provider.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_provider.status",
            object_type="catalog_provider",
            object_id=provider_id,
            after_summary={"status": status},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.provider.changed",
            object_type="catalog_provider",
            object_id=provider_id,
            object_version=str(provider.row_version),
        )
        return provider
