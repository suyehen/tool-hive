"""Catalog 工具版本管理服务：版本状态机、执行绑定、审核与发布历史。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import (
    CatalogHistoryAction,
    ProviderType,
    ToolVersionStatus,
)
from toolhive.core.exceptions import ConflictError, NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_publish_history import CatalogPublishHistory
from toolhive.models.catalog_review_record import CatalogReviewRecord
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.services.audit_service import AuditService, get_current_operator_id
from toolhive.services.catalog_common import validate_version
from toolhive.services.catalog_events import emit_catalog_index_event

logger = logging.getLogger(__name__)


class CatalogVersionService:
    """工具版本全生命周期：草稿 → 送审 → 审核 → 发布 → 停用/撤回/归档。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ═════════════════════════════════════════════════════════════
    # 查询
    # ═════════════════════════════════════════════════════════════

    async def list_versions(self, tool_id: str) -> list[CatalogToolVersion]:
        """查询工具下全部版本（按创建时间升序）。"""
        result = await self.db.execute(
            select(CatalogToolVersion)
            .where(CatalogToolVersion.tool_id == tool_id)
            .order_by(CatalogToolVersion.create_time.asc())
        )
        return list(result.scalars().all())

    async def get_version(self, version_id: str) -> CatalogToolVersion:
        """按主键查询版本，不存在时抛 404。"""
        version = await self.db.get(CatalogToolVersion, version_id)
        if version is None:
            raise NotFoundError(f"工具版本不存在: {version_id}")
        return version

    async def get_binding(
        self, version_id: str,
    ) -> CatalogExecutionBinding | None:
        """查询版本对应的执行绑定（可能为空）。"""
        return await self.db.scalar(
            select(CatalogExecutionBinding).where(
                CatalogExecutionBinding.version_id == version_id
            )
        )

    async def list_pending_reviews(
        self, *, offset: int = 0, limit: int = 50,
    ) -> tuple[list[tuple[CatalogToolVersion, CatalogTool]], int]:
        """查询全部待审核版本（含所属工具），按送审时间升序。"""
        base = (
            select(CatalogToolVersion, CatalogTool)
            .join(CatalogTool, CatalogTool.id == CatalogToolVersion.tool_id)
            .where(CatalogToolVersion.status == ToolVersionStatus.PENDING_REVIEW)
        )
        total = await self.db.scalar(
            select(func.count())
            .select_from(CatalogToolVersion)
            .join(CatalogTool, CatalogTool.id == CatalogToolVersion.tool_id)
            .where(CatalogToolVersion.status == ToolVersionStatus.PENDING_REVIEW)
        )
        result = await self.db.execute(
            base.order_by(CatalogToolVersion.create_time.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.all()), total or 0

    async def list_tool_history(self, tool_id: str) -> list[dict[str, Any]]:
        """合并返回工具下的审核记录与发布历史（按时间倒序）。"""
        reviews = (
            await self.db.execute(
                select(CatalogReviewRecord)
                .where(CatalogReviewRecord.tool_id == tool_id)
                .order_by(CatalogReviewRecord.create_time.desc())
            )
        ).scalars().all()
        histories = (
            await self.db.execute(
                select(CatalogPublishHistory)
                .where(CatalogPublishHistory.tool_id == tool_id)
                .order_by(CatalogPublishHistory.create_time.desc())
            )
        ).scalars().all()
        merged: list[dict[str, Any]] = [
            {
                "kind": "review",
                "id": r.id,
                "version_id": r.version_id,
                "action": r.action,
                "from_status": r.from_status,
                "to_status": r.to_status,
                "comment": r.comment,
                "operator_account_id": r.operator_account_id,
                "created_at": r.create_time,
            }
            for r in reviews
        ]
        merged.extend(
            {
                "kind": "history",
                "id": h.id,
                "version_id": h.version_id,
                "action": h.action,
                "comment": h.comment,
                "operator_account_id": h.operator_account_id,
                "created_at": h.create_time,
            }
            for h in histories
        )
        merged.sort(key=lambda item: item["created_at"], reverse=True)
        return merged

    # ═════════════════════════════════════════════════════════════
    # 版本与执行绑定维护
    # ═════════════════════════════════════════════════════════════

    @transactional()
    async def create_version(
        self,
        tool_id: str,
        version: str,
        *,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        release_note: str | None = None,
        binding: dict[str, Any] | None = None,
    ) -> CatalogToolVersion:
        """创建草稿版本；可同时创建执行绑定。"""
        tool = await self.db.get(CatalogTool, tool_id)
        if tool is None:
            raise NotFoundError(f"工具不存在: {tool_id}")
        ver = validate_version(version)
        existing = await self.db.scalar(
            select(CatalogToolVersion).where(
                CatalogToolVersion.tool_id == tool_id,
                CatalogToolVersion.version == ver,
            )
        )
        if existing:
            raise ConflictError(f"版本 '{ver}' 已存在")
        self._validate_schemas(input_schema, output_schema)
        new_version = CatalogToolVersion(
            tool_id=tool_id,
            version=ver,
            status=ToolVersionStatus.DRAFT,
            input_schema=input_schema,
            output_schema=output_schema,
            release_note=release_note,
            create_time=datetime.now(UTC),
            create_by=get_current_operator_id(),
        )
        self.db.add(new_version)
        await self.db.flush()
        if binding is not None:
            await self._create_binding(new_version.id, binding)
        AuditService(self.db).add_record(
            action="catalog_version.create",
            object_type="tool_version",
            object_id=new_version.id,
            after_summary={"tool_id": tool_id, "version": ver},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.version.changed",
            object_type="tool_version",
            object_id=new_version.id,
            object_version=str(new_version.row_version),
            payload={"tool_id": tool_id, "version": ver, "status": new_version.status},
        )
        logger.info("catalog version created tool_id=%s version=%s", tool_id, ver)
        return new_version

    @transactional()
    async def update_version(
        self,
        version_id: str,
        *,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        release_note: str | None = None,
        binding: dict[str, Any] | None = None,
        clear_binding: bool = False,
        expected_row_version: int | None = None,
    ) -> CatalogToolVersion:
        """编辑草稿 / 驳回状态版本；可更新或清除执行绑定。"""
        version = await self.get_version(version_id)
        if version.status not in (
            ToolVersionStatus.DRAFT,
            ToolVersionStatus.REJECTED,
        ):
            raise ConflictError("只有草稿或驳回状态的版本可以编辑")
        if (
            expected_row_version is not None
            and version.row_version != expected_row_version
        ):
            raise ConflictError("数据已被他人修改，请刷新后重试")
        self._validate_schemas(input_schema, output_schema)
        if input_schema is not None:
            version.input_schema = input_schema
        if output_schema is not None:
            version.output_schema = output_schema
        if release_note is not None:
            version.release_note = release_note
        if clear_binding:
            existing = await self.get_binding(version_id)
            if existing is not None:
                await self.db.delete(existing)
        elif binding is not None:
            existing = await self.get_binding(version_id)
            if existing is None:
                await self._create_binding(version_id, binding)
            else:
                await self._update_binding(existing, binding)
        version.update_time = datetime.now(UTC)
        version.update_by = get_current_operator_id()
        version.row_version += 1
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_version.update",
            object_type="tool_version",
            object_id=version_id,
            after_summary={"version": version.version, "status": version.status},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.version.changed",
            object_type="tool_version",
            object_id=version_id,
            object_version=str(version.row_version),
        )
        return version

    # ═════════════════════════════════════════════════════════════
    # 审核发布状态机
    # ═════════════════════════════════════════════════════════════

    @transactional()
    async def submit_review(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """送审：草稿 / 驳回 → 待审核；要求 Schema 与执行绑定齐全。"""
        version = await self.get_version(version_id)
        if version.status not in (
            ToolVersionStatus.DRAFT,
            ToolVersionStatus.REJECTED,
        ):
            raise ConflictError("只有草稿或驳回状态的版本可以送审")
        if not version.input_schema or not version.output_schema:
            raise ValidationError("送审前必须填写输入与输出 Schema")
        binding = await self.get_binding(version_id)
        if binding is None:
            raise ValidationError("送审前必须配置执行绑定")
        old_status = version.status
        version.status = ToolVersionStatus.PENDING_REVIEW
        version.review_comment = None
        self._bump(version)
        self._add_review_record(
            version, CatalogHistoryAction.SUBMIT_REVIEW, old_status, comment,
        )
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.submit_review", old_status, comment,
        )
        return version

    @transactional()
    async def approve(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """审核通过：待审核 → 已通过。"""
        version = await self.get_version(version_id)
        if version.status != ToolVersionStatus.PENDING_REVIEW:
            raise ConflictError("只有待审核状态的版本可以审核通过")
        old_status = version.status
        version.status = ToolVersionStatus.APPROVED
        version.review_comment = comment
        self._bump(version)
        self._add_review_record(
            version, CatalogHistoryAction.APPROVE, old_status, comment,
        )
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.approve", old_status, comment,
        )
        return version

    @transactional()
    async def reject(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """审核驳回：待审核 → 驳回（可修改后重新送审）。"""
        version = await self.get_version(version_id)
        if version.status != ToolVersionStatus.PENDING_REVIEW:
            raise ConflictError("只有待审核状态的版本可以驳回")
        old_status = version.status
        version.status = ToolVersionStatus.REJECTED
        version.review_comment = comment
        self._bump(version)
        self._add_review_record(
            version, CatalogHistoryAction.REJECT, old_status, comment,
        )
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.reject", old_status, comment,
        )
        return version

    @transactional()
    async def publish(
        self, version_id: str, *, set_default: bool, comment: str | None = None,
    ) -> CatalogToolVersion:
        """发布版本；首个发布必须 set_default=True，默认版本唯一。"""
        version = await self.get_version(version_id)
        if version.status != ToolVersionStatus.APPROVED:
            raise ConflictError("只有已通过审核的版本可以发布")
        tool = await self._get_tool(version.tool_id)
        if set_default:
            if tool.default_version_id != version.id:
                tool.default_version_id = version.id
                tool.update_time = datetime.now(UTC)
                tool.update_by = get_current_operator_id()
                tool.row_version += 1
                self._add_history(
                    version, CatalogHistoryAction.SET_DEFAULT, None,
                )
        elif tool.default_version_id is None:
            raise ValidationError("首个发布版本必须设置为默认版本")
        old_status = version.status
        version.status = ToolVersionStatus.PUBLISHED
        self._bump(version)
        self._add_history(version, CatalogHistoryAction.PUBLISH, comment)
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.publish", old_status, comment,
        )
        return version

    @transactional()
    async def set_default(self, tool_id: str, version_id: str) -> CatalogToolVersion:
        """切换工具默认版本（仅已发布版本可设为默认）。"""
        version = await self.get_version(version_id)
        if version.tool_id != tool_id:
            raise NotFoundError("版本不属于该工具")
        if version.status != ToolVersionStatus.PUBLISHED:
            raise ValidationError("只有已发布版本可以设为默认")
        tool = await self._get_tool(tool_id)
        if tool.default_version_id == version.id:
            raise ConflictError("该版本已是默认版本")
        tool.default_version_id = version.id
        tool.update_time = datetime.now(UTC)
        tool.update_by = get_current_operator_id()
        tool.row_version += 1
        self._add_history(version, CatalogHistoryAction.SET_DEFAULT, None)
        await self.db.flush()
        AuditService(self.db).add_record(
            action="catalog_version.set_default",
            object_type="tool_version",
            object_id=version_id,
            after_summary={"tool_id": tool_id, "version": version.version},
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.version.changed",
            object_type="tool_version",
            object_id=version_id,
            object_version=str(version.row_version),
        )
        return version

    @transactional()
    async def disable(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """停用版本：已发布 → 已停用（在途请求放行完成）。"""
        version = await self.get_version(version_id)
        if version.status != ToolVersionStatus.PUBLISHED:
            raise ConflictError("只有已发布状态的版本可以停用")
        old_status = version.status
        version.status = ToolVersionStatus.DISABLED
        self._bump(version)
        self._add_history(version, CatalogHistoryAction.DISABLE, comment)
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.disable", old_status, comment,
        )
        return version

    @transactional()
    async def enable(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """重新启用版本：已停用 → 已发布。"""
        version = await self.get_version(version_id)
        if version.status != ToolVersionStatus.DISABLED:
            raise ConflictError("只有已停用状态的版本可以重新启用")
        old_status = version.status
        version.status = ToolVersionStatus.PUBLISHED
        self._bump(version)
        self._add_history(version, CatalogHistoryAction.ENABLE, comment)
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.enable", old_status, comment,
        )
        return version

    @transactional()
    async def withdraw(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """撤回版本：已发布 / 已停用 → 已撤回；若为默认版本则清除默认。"""
        version = await self.get_version(version_id)
        if version.status not in (
            ToolVersionStatus.PUBLISHED,
            ToolVersionStatus.DISABLED,
        ):
            raise ConflictError("只有已发布或已停用状态的版本可以撤回")
        tool = await self._get_tool(version.tool_id)
        if tool.default_version_id == version.id:
            tool.default_version_id = None
            tool.update_time = datetime.now(UTC)
            tool.update_by = get_current_operator_id()
            tool.row_version += 1
        old_status = version.status
        version.status = ToolVersionStatus.WITHDRAWN
        self._bump(version)
        self._add_history(version, CatalogHistoryAction.WITHDRAW, comment)
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.withdraw", old_status, comment,
        )
        return version

    @transactional()
    async def archive(
        self, version_id: str, comment: str | None = None,
    ) -> CatalogToolVersion:
        """归档版本（终态）；若为默认版本则清除默认。"""
        version = await self.get_version(version_id)
        if version.status == ToolVersionStatus.ARCHIVED:
            raise ConflictError("版本已归档")
        tool = await self._get_tool(version.tool_id)
        if tool.default_version_id == version.id:
            tool.default_version_id = None
            tool.update_time = datetime.now(UTC)
            tool.update_by = get_current_operator_id()
            tool.row_version += 1
        old_status = version.status
        version.status = ToolVersionStatus.ARCHIVED
        self._bump(version)
        self._add_history(version, CatalogHistoryAction.ARCHIVE, comment)
        await self.db.flush()
        self._after_transition(
            version, "catalog_version.archive", old_status, comment,
        )
        return version

    # ═════════════════════════════════════════════════════════════
    # 内部工具
    # ═════════════════════════════════════════════════════════════

    @staticmethod
    def _validate_schemas(
        input_schema: dict[str, Any] | None,
        output_schema: dict[str, Any] | None,
    ) -> None:
        """校验 Schema 必须为 JSON 对象。"""
        if input_schema is not None and not isinstance(input_schema, dict):
            raise ValidationError("input_schema 必须是 JSON 对象")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise ValidationError("output_schema 必须是 JSON 对象")

    async def _get_tool(self, tool_id: str) -> CatalogTool:
        tool = await self.db.get(CatalogTool, tool_id)
        if tool is None:
            raise NotFoundError(f"工具不存在: {tool_id}")
        return tool

    async def _validate_binding_data(
        self, binding: dict[str, Any],
    ) -> tuple[CatalogProvider, str, str]:
        """校验执行绑定数据，返回 (Provider, method, path_template)。"""
        provider_id = binding.get("provider_id")
        method = (binding.get("method") or "").strip().upper()
        path_template = (binding.get("path_template") or "").strip()
        if not provider_id:
            raise ValidationError("执行绑定必须指定 provider_id")
        provider = await self.db.get(CatalogProvider, provider_id)
        if provider is None:
            raise ValidationError(f"Provider 不存在: {provider_id}")
        if provider.status == "archived":
            raise ValidationError("已归档的 Provider 不能用于执行绑定")
        if provider.provider_type == ProviderType.BUILTIN:
            if method != "COMPUTE":
                raise ValidationError("builtin 类型 Provider 的方法必须是 COMPUTE")
            if not path_template.startswith("builtin://"):
                raise ValidationError("builtin 类型绑定路径必须以 builtin:// 开头")
        else:
            if method not in ("GET", "POST", "PUT", "DELETE"):
                raise ValidationError(
                    "http 类型 Provider 的方法必须是 GET/POST/PUT/DELETE"
                )
            if not path_template.startswith("/"):
                raise ValidationError("http 类型绑定路径必须以 / 开头")
        return provider, method, path_template

    async def _create_binding(
        self, version_id: str, binding: dict[str, Any],
    ) -> CatalogExecutionBinding:
        """创建执行绑定（版本创建 / 更新时调用）。"""
        provider, method, path_template = await self._validate_binding_data(binding)
        now = datetime.now(UTC)
        record = CatalogExecutionBinding(
            version_id=version_id,
            provider_id=provider.id,
            method=method,
            path_template=path_template,
            parameter_mapping=binding.get("parameter_mapping"),
            allowed_headers=binding.get("allowed_headers"),
            response_handling=binding.get("response_handling"),
            timeout_seconds=binding.get("timeout_seconds"),
            retry_max=binding.get("retry_max"),
            idempotent=bool(binding.get("idempotent", True)),
            create_time=now,
            create_by=get_current_operator_id(),
        )
        self.db.add(record)
        await self.db.flush()
        return record

    async def _update_binding(
        self, record: CatalogExecutionBinding, binding: dict[str, Any],
    ) -> None:
        """更新执行绑定字段。"""
        provider, method, path_template = await self._validate_binding_data(binding)
        record.provider_id = provider.id
        record.method = method
        record.path_template = path_template
        record.parameter_mapping = binding.get("parameter_mapping")
        record.allowed_headers = binding.get("allowed_headers")
        record.response_handling = binding.get("response_handling")
        record.timeout_seconds = binding.get("timeout_seconds")
        record.retry_max = binding.get("retry_max")
        record.idempotent = bool(binding.get("idempotent", True))
        record.update_time = datetime.now(UTC)
        record.update_by = get_current_operator_id()
        record.row_version += 1

    @staticmethod
    def _bump(version: CatalogToolVersion) -> None:
        """写入版本修改时间、操作人与乐观锁版本。"""
        version.update_time = datetime.now(UTC)
        version.update_by = get_current_operator_id()
        version.row_version += 1

    def _add_review_record(
        self,
        version: CatalogToolVersion,
        action: CatalogHistoryAction,
        from_status: str,
        comment: str | None,
    ) -> None:
        """追加审核记录。"""
        self.db.add(
            CatalogReviewRecord(
                tool_id=version.tool_id,
                version_id=version.id,
                action=action.value,
                from_status=from_status,
                to_status=version.status,
                comment=comment,
                operator_account_id=get_current_operator_id(),
                create_time=datetime.now(UTC),
                create_by=get_current_operator_id(),
            )
        )

    def _add_history(
        self,
        version: CatalogToolVersion,
        action: CatalogHistoryAction,
        comment: str | None,
    ) -> None:
        """追加发布历史。"""
        self.db.add(
            CatalogPublishHistory(
                tool_id=version.tool_id,
                version_id=version.id,
                action=action.value,
                comment=comment,
                operator_account_id=get_current_operator_id(),
                create_time=datetime.now(UTC),
                create_by=get_current_operator_id(),
            )
        )

    def _after_transition(
        self,
        version: CatalogToolVersion,
        action: str,
        from_status: str,
        comment: str | None,
    ) -> None:
        """状态流转后的审计与索引事件。"""
        AuditService(self.db).add_record(
            action=action,
            object_type="tool_version",
            object_id=version.id,
            before_summary={"status": from_status},
            after_summary={"status": version.status},
            reason=comment,
        )
        emit_catalog_index_event(
            self.db,
            event_type="catalog.version.changed",
            object_type="tool_version",
            object_id=version.id,
            object_version=str(version.row_version),
            payload={"status": version.status},
        )
