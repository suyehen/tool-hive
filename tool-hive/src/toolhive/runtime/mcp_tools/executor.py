"""MCP tools/call 执行闭环：授权重判 → 需确认拒绝 → Schema → Provider → Trace。"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.config import settings
from toolhive.core.enums import (
    CatalogObjectStatus,
    RiskLevel,
    ToolScopeStatus,
    ToolVersionStatus,
)
from toolhive.infrastructure.redis import get_redis
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.models.mcp_client_scope import McpClientScope
from toolhive.runtime.errors import (
    RUNTIME_CONFIRMATION_REQUIRED,
    RUNTIME_INTERNAL_ERROR,
    RUNTIME_PARAMETER_INVALID,
    RUNTIME_PROVIDER_ERROR,
    RUNTIME_TOOL_NOT_AVAILABLE,
    RuntimeApiError,
)
from toolhive.runtime.execution.gateway import BuiltinExecutor, ProviderGateway
from toolhive.runtime.execution.http_executor import HttpExecutor
from toolhive.runtime.tool_control.scope_expansion import scope_allows_tool
from toolhive.runtime.tracing.service import TraceService, new_trace_id
from toolhive.runtime.validation.json_schema import JsonSchemaValidator

logger = logging.getLogger(__name__)

_WRITE_METHODS = ("POST", "PUT", "DELETE")


class McpToolCallError(Exception):
    """MCP 工具调用业务拒绝（转换为 isError 结果，不抛给协议层）。"""

    def __init__(self, message: str, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code


@dataclass
class McpCallOutcome:
    """MCP tools/call 结果（文本 + 结构化内容）。"""

    text: str
    structured: Any = None
    is_error: bool = False


class McpCallExecutor:
    """按 MCP 客户端身份执行一次工具调用，走现有决策链与 Provider 网关。"""

    def __init__(self, db: AsyncSession, *, client_id: str, source_ip: str):
        self.db = db
        self.client_id = client_id
        self.source_ip = source_ip

    async def execute(self, full_code: str, arguments: dict[str, Any]) -> McpCallOutcome:
        """执行工具；拒绝与失败均返回 isError 结果并落 Trace。"""
        trace_id = new_trace_id()
        start = time.perf_counter()
        try:
            return await self._execute_guarded(full_code, arguments, trace_id, start)
        except McpToolCallError as exc:
            await self._log(
                trace_id, "runtime.control", "failure", exc.error_code,
                {"tool_code": full_code, "decision": "deny"},
            )
            return McpCallOutcome(
                text=exc.message, is_error=True,
            )
        except RuntimeApiError as exc:
            await self._log(
                trace_id, "runtime.request", "failure", exc.code,
                {"tool_code": full_code},
            )
            return McpCallOutcome(
                text=exc.message or "工具执行失败", is_error=True,
            )
        except Exception as exc:
            logger.error(
                "mcp tool call failed tool=%s client=%s error=%s",
                full_code, self.client_id, exc,
            )
            await self._log(
                trace_id, "runtime.request", "failure", RUNTIME_INTERNAL_ERROR,
                {"tool_code": full_code},
            )
            return McpCallOutcome(text="内部错误", is_error=True)

    async def _execute_guarded(
        self,
        full_code: str,
        arguments: dict[str, Any],
        trace_id: str,
        start: float,
    ) -> McpCallOutcome:
        """授权重判并执行，成功才返回非错误结果。"""
        tool, version, binding, provider = await self._authorize(full_code, trace_id)
        # D1 兜底：需确认（高风险/写操作）工具本批拒绝执行
        confirmation_required = self._confirmation_required(tool, binding)
        if confirmation_required:
            raise McpToolCallError(
                "该工具需要确认，暂不支持执行",
                RUNTIME_CONFIRMATION_REQUIRED,
            )
        input_schema = version.input_schema or tool.input_schema
        try:
            JsonSchemaValidator(input_schema).validate(arguments)
        except RuntimeApiError as exc:
            raise McpToolCallError(
                "参数无效", RUNTIME_PARAMETER_INVALID,
            ) from exc
        redis = await get_redis()
        gateway = ProviderGateway(
            {
                BuiltinExecutor.provider_type: BuiltinExecutor(),
                HttpExecutor.provider_type: HttpExecutor(
                    redis, settings.runtime_security,
                ),
            }
        )
        try:
            result = await gateway.execute(binding, provider, arguments)
        except RuntimeApiError as exc:
            await self._log(
                trace_id, "runtime.provider", "failure", exc.code,
                {"tool_code": full_code, "provider_type": provider.provider_type},
            )
            raise
        output_schema = version.output_schema or tool.output_schema
        if output_schema is not None:
            try:
                JsonSchemaValidator(output_schema).validate(result, path="result")
            except RuntimeApiError:
                raise McpToolCallError(
                    "Provider 返回结果不符合声明的输出 Schema",
                    RUNTIME_PROVIDER_ERROR,
                ) from None
        digest = hashlib.sha256(
            json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        await self._log(
            trace_id, "runtime.execute", "success", None,
            {
                "tool_code": full_code,
                "version": version.version,
                "result_sha256": digest,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            },
        )
        text = result if isinstance(result, str) else json.dumps(
            result, ensure_ascii=False, sort_keys=True,
        )
        return McpCallOutcome(text=text, structured=result)

    async def _authorize(
        self,
        full_code: str,
        trace_id: str,
    ) -> tuple[CatalogTool, CatalogToolVersion, CatalogExecutionBinding, CatalogProvider]:
        """实时重判工具可用性、客户端授权、默认版本与 Provider 状态。"""
        namespace, tool_code = full_code.rsplit(".", 1)
        tool = await self.db.scalar(
            select(CatalogTool).where(
                CatalogTool.namespace == namespace,
                CatalogTool.tool_code == tool_code,
            )
        )
        if (
            tool is None
            or tool.status != CatalogObjectStatus.ENABLED
            or not tool.discoverable
            or not tool.executable
            or tool.mcp_enabled is False
        ):
            raise McpToolCallError("工具不可用", RUNTIME_TOOL_NOT_AVAILABLE)
        scopes = await self._load_active_scopes()
        if not await scope_allows_tool(self.db, scopes, tool):
            raise McpToolCallError("工具不可用", RUNTIME_TOOL_NOT_AVAILABLE)
        version = await self.db.get(CatalogToolVersion, tool.default_version_id)
        if (
            version is None
            or version.status != ToolVersionStatus.PUBLISHED
        ):
            raise McpToolCallError("工具不可用", RUNTIME_TOOL_NOT_AVAILABLE)
        binding = await self.db.scalar(
            select(CatalogExecutionBinding).where(
                CatalogExecutionBinding.version_id == version.id,
            )
        )
        if binding is None:
            raise McpToolCallError("工具不可用", RUNTIME_TOOL_NOT_AVAILABLE)
        provider = await self.db.get(CatalogProvider, binding.provider_id)
        if provider is None or provider.status != CatalogObjectStatus.ENABLED:
            raise McpToolCallError("工具不可用", RUNTIME_TOOL_NOT_AVAILABLE)
        await self._log(
            trace_id, "runtime.control", "success", None,
            {"tool_code": full_code, "decision": "allow"},
        )
        return tool, version, binding, provider

    async def _load_active_scopes(self) -> list[McpClientScope]:
        """查询客户端 ACTIVE 授权范围。"""
        result = await self.db.execute(
            select(McpClientScope).where(
                McpClientScope.client_id == self.client_id,
                McpClientScope.status == ToolScopeStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    @staticmethod
    def _confirmation_required(
        tool: CatalogTool, binding: CatalogExecutionBinding,
    ) -> bool:
        """统一确认需求：高风险或写操作绑定需要确认。"""
        return tool.risk_level == RiskLevel.HIGH or (
            binding.method in _WRITE_METHODS
        )

    async def _log(
        self,
        trace_id: str,
        action: str,
        status: str,
        error_code: str | None,
        summary: dict[str, Any],
    ) -> None:
        """写 MCP 渠道 Trace 事件。"""
        await TraceService.log_event(
            trace_id=trace_id,
            action=action,
            status=status,
            error_code=error_code,
            summary=summary,
            source_ip=self.source_ip,
            channel="mcp",
            mcp_client_id=self.client_id,
        )
