"""管理端工具测试服务（一期仅支持 builtin 类型，出站仍走统一网关）。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.enums import (
    CatalogObjectStatus,
    ProviderType,
    RiskLevel,
    ToolVersionStatus,
)
from toolhive.core.exceptions import NotFoundError, ValidationError
from toolhive.infrastructure.transactions import transactional
from toolhive.models.catalog_tool import CatalogTool
from toolhive.runtime.execution.gateway import BuiltinExecutor, ProviderGateway
from toolhive.runtime.tracing.service import TraceService, new_trace_id
from toolhive.runtime.validation.json_schema import JsonSchemaValidator
from toolhive.services.audit_service import AuditService
from toolhive.services.catalog_provider_service import CatalogProviderService
from toolhive.services.catalog_version_service import CatalogVersionService

_WRITE_METHODS = ("POST", "PUT", "DELETE")


class CatalogTestService:
    """管理端调试执行：沿用调用控制、参数校验与统一网关，走管理审计。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    @transactional()
    async def test_execute(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
        confirm: bool = False,
        version: str | None = None,
        trace_id: str | None = None,
        source_ip: str | None = None,
    ) -> dict[str, Any]:
        """测试执行已发布工具；一期仅允许 builtin 类型。"""
        tool = await self.db.get(CatalogTool, tool_id)
        if tool is None:
            raise NotFoundError(f"工具不存在: {tool_id}")
        if tool.status != CatalogObjectStatus.ENABLED or not tool.executable:
            raise ValidationError("工具不可执行")
        version_svc = CatalogVersionService(self.db)
        published = [
            v
            for v in await version_svc.list_versions(tool_id)
            if v.status == ToolVersionStatus.PUBLISHED
        ]
        if not published:
            raise NotFoundError("工具暂无已发布版本")
        if version:
            selected = next(
                (v for v in published if v.version == version), None,
            )
            if selected is None:
                raise ValidationError(f"版本 {version} 未发布或不存在")
        else:
            selected = next(
                (v for v in published if v.id == tool.default_version_id),
                published[-1],
            )
        binding = await version_svc.get_binding(selected.id)
        if binding is None:
            raise ValidationError("版本未配置执行绑定")
        provider = await CatalogProviderService(self.db).get_provider(
            binding.provider_id
        )
        if provider.provider_type != ProviderType.BUILTIN:
            raise ValidationError(
                "管理端测试功能一期仅支持 builtin 类型工具，请通过运行 API 验收"
            )
        confirmation_required = (
            tool.risk_level == RiskLevel.HIGH
            or binding.method in _WRITE_METHODS
        )
        if confirmation_required and not confirm:
            raise ValidationError("该工具为高风险或写操作，请勾选确认后测试")
        input_schema = selected.input_schema or tool.input_schema
        JsonSchemaValidator(input_schema).validate(arguments)

        # 统一 ProviderGateway（固定映射，出站防护仍生效）
        gateway = ProviderGateway(
            {BuiltinExecutor.provider_type: BuiltinExecutor()}
        )
        result = await gateway.execute(binding, provider, arguments)
        trace_id = trace_id or new_trace_id()
        result_digest = hashlib.sha256(
            json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        await TraceService.log_event(
            trace_id=trace_id,
            system_id="management",
            action="runtime.execute",
            status="success",
            summary={
                "source": "admin-test",
                "tool_code": tool.full_code,
                "version": selected.version,
                "provider_type": provider.provider_type,
                # TODO: 此处明文记录执行结果，后续可调整为仅存哈希或掩码方案
                "result": result,
                "result_sha256": result_digest,
            },
            source_ip=source_ip,
        )
        AuditService(self.db).add_record(
            action="catalog_tool.test_execute",
            object_type="catalog_tool",
            object_id=tool_id,
            after_summary={
                "tool_code": tool.full_code,
                "version": selected.version,
                "provider_type": provider.provider_type,
                "confirm_required": confirmation_required,
            },
            trace_id=trace_id,
        )
        return {
            "tool_code": tool.full_code,
            "version": selected.version,
            "result": result,
            "trace_id": trace_id,
        }
