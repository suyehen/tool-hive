"""运行侧安全与控制中间件：认证、范围、流量、超时、熔断与 Trace。"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import UTC, datetime

from sqlalchemy import func, select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from toolhive.config import RuntimeSecuritySettings
from toolhive.core.enums import (
    CatalogObjectStatus,
    ToolScopeStatus,
    ToolScopeType,
    ToolVersionStatus,
)
from toolhive.infrastructure import database
from toolhive.infrastructure.redis import get_redis
from toolhive.models.caller_runtime_policy import CallerRuntimePolicy
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.models.catalog_capability_pack import CatalogCapabilityPack
from toolhive.models.catalog_capability_pack_tool import CatalogCapabilityPackTool
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.authentication.service import RuntimeAuthService
from toolhive.runtime.control.traffic import RuntimeTrafficGuard
from toolhive.runtime.errors import (
    RUNTIME_AUTH_SECURITY_UNAVAILABLE,
    RUNTIME_CIRCUIT_OPEN,
    RUNTIME_INTERNAL_ERROR,
    RUNTIME_RATE_LIMITED,
    RUNTIME_REQUEST_TIMEOUT,
    RUNTIME_SCOPE_NOT_ALLOWED,
    RUNTIME_TOOL_NOT_AVAILABLE,
    RUNTIME_TOOL_NOT_FOUND,
    RuntimeApiError,
)
from toolhive.runtime.tracing.service import TraceService, new_trace_id, parse_trace_id

logger = logging.getLogger(__name__)

_EXECUTE_PATH_RE = re.compile(
    r"^/api/runtime/v1/tools/(?P<tool_code>[^/]+)/execute$"
)


class RuntimeSecurityMiddleware(BaseHTTPMiddleware):
    """运行 API 统一安全链：签名认证 → 范围 → 流量 → 超时 → 熔断 → Trace。"""

    def __init__(
        self,
        app,
        runtime_security: RuntimeSecuritySettings,
    ) -> None:
        super().__init__(app)
        self._security = runtime_security
        self._guard = RuntimeTrafficGuard()

    async def dispatch(self, request: Request, call_next):
        # 解析透传 trace_id；非法直接返回 400
        raw_trace = request.headers.get("X-ToolHive-Trace-Id")
        try:
            trace_id = parse_trace_id(raw_trace)
        except RuntimeApiError as exc:
            trace_id = new_trace_id()
            response = self._error_response(
                exc.code, exc.message, exc.http_status, trace_id,
            )
            response.headers["X-ToolHive-Trace-Id"] = trace_id
            return response
        request.state.trace_id = trace_id
        redis = None
        system_id: str | None = None
        start = time.perf_counter()
        try:
            redis = await get_redis()
            async with database.async_session_factory() as session:
                # 签名认证（系统状态/IP/公钥/时间窗/Nonce/签名）
                identity = await RuntimeAuthService(
                    session, redis, self._security,
                ).authenticate(request, trace_id)
                request.state.caller_identity = identity
                request.state.caller_system = identity.system
                system_id = identity.system.system_id
                await TraceService.log_event(
                    trace_id=trace_id,
                    system_id=system_id,
                    action="runtime.auth",
                    status="success",
                    summary={"key_id": identity.key.key_id},
                    source_ip=identity.source_ip,
                )
                # 运行范围与流量控制
                policy = await self._authorize(request, session, system_id)
                await self._guard.check(system_id, policy, redis, self._security)
                request.state.runtime_policy = policy
                await TraceService.log_event(
                    trace_id=trace_id,
                    system_id=system_id,
                    action="runtime.scope",
                    status="success",
                    summary={"path": request.url.path},
                    source_ip=identity.source_ip,
                )

            try:
                response = await asyncio.wait_for(
                    call_next(request),
                    timeout=policy.request_timeout_seconds,
                )
            except TimeoutError:
                response = self._error_response(
                    RUNTIME_REQUEST_TIMEOUT,
                    "运行请求处理超时",
                    504,
                    trace_id,
                )
            response.headers["X-ToolHive-Trace-Id"] = trace_id
            await self._record_outcome(
                redis, system_id, request, response.status_code, start, trace_id,
            )
            return response
        except RuntimeApiError as exc:
            action = self._trace_action_for(exc.code)
            await TraceService.log_event(
                trace_id=trace_id,
                system_id=system_id,
                action=action,
                status="failure",
                error_code=exc.code,
                summary={"path": request.url.path},
            )
            response = self._error_response(
                exc.code, exc.message, exc.http_status, trace_id,
            )
            response.headers["X-ToolHive-Trace-Id"] = trace_id
            return response
        except Exception:
            logger.exception("runtime request failed path=%s", request.url.path)
            await TraceService.log_event(
                trace_id=trace_id,
                system_id=system_id,
                action="runtime.request",
                status="failure",
                error_code=RUNTIME_INTERNAL_ERROR,
                summary={"path": request.url.path},
            )
            response = self._error_response(
                RUNTIME_INTERNAL_ERROR, "内部错误", 500, trace_id,
            )
            response.headers["X-ToolHive-Trace-Id"] = trace_id
            return response
        finally:
            if system_id is not None:
                await self._guard.release(system_id)

    @staticmethod
    def _trace_action_for(code: str) -> str:
        """按错误码归类 Trace 事件动作。"""
        if code.startswith("RUNTIME_AUTH"):
            return "runtime.auth"
        if code in (
            RUNTIME_RATE_LIMITED,
            RUNTIME_CIRCUIT_OPEN,
            RUNTIME_AUTH_SECURITY_UNAVAILABLE,
        ):
            return "runtime.traffic"
        return "runtime.scope"

    async def _authorize(self, request: Request, session, system_id: str):
        """运行 API 范围 + 工具路径预校验 + 策略有效期。"""
        policy = await session.scalar(
            select(CallerRuntimePolicy).where(
                CallerRuntimePolicy.system_id == system_id
            )
        )
        if policy is None:
            raise RuntimeApiError(
                RUNTIME_SCOPE_NOT_ALLOWED,
                "调用系统未配置运行策略",
                403,
            )
        now = datetime.now(UTC)
        if policy.effective_from and policy.effective_from > now:
            raise RuntimeApiError(
                RUNTIME_SCOPE_NOT_ALLOWED,
                "运行策略尚未生效",
                403,
            )
        if policy.effective_to and policy.effective_to <= now:
            raise RuntimeApiError(
                RUNTIME_SCOPE_NOT_ALLOWED,
                "运行策略已过期",
                403,
            )
        if not self._matches_api_pattern(
            request.url.path, policy.get_allowed_api_patterns()
        ):
            raise RuntimeApiError(
                RUNTIME_SCOPE_NOT_ALLOWED,
                f"运行 API 不在调用系统授权范围: {request.url.path}",
                403,
            )
        await self._check_tool_path_scope(request, session, system_id)
        return policy

    @staticmethod
    def _matches_api_pattern(path: str, patterns: list[str]) -> bool:
        """API 范围匹配：精确匹配或尾 * 前缀匹配。"""
        for pattern in patterns:
            value = pattern.strip()
            if not value:
                continue
            if value.endswith("*"):
                if path.startswith(value[:-1]):
                    return True
            elif path == value:
                return True
        return False

    async def _check_tool_path_scope(
        self, request: Request, session, system_id: str,
    ) -> None:
        """execute 路径按 tool_code 做调用系统范围 + Catalog 状态预校验。"""
        match = _EXECUTE_PATH_RE.match(request.url.path)
        if match is None:
            return
        full_code = match.group("tool_code")
        tool = await session.scalar(
            select(CatalogTool).where(
                (CatalogTool.namespace + "." + CatalogTool.tool_code) == full_code
            )
        )
        if tool is None:
            raise RuntimeApiError(
                RUNTIME_TOOL_NOT_FOUND, f"工具不存在: {full_code}", 404,
            )
        if tool.status == CatalogObjectStatus.ARCHIVED or not tool.executable:
            raise RuntimeApiError(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具不可执行", 403,
            )
        published = await session.scalar(
            select(func.count())
            .select_from(CatalogToolVersion)
            .where(
                CatalogToolVersion.tool_id == tool.id,
                CatalogToolVersion.status == ToolVersionStatus.PUBLISHED,
            )
        )
        if not published:
            raise RuntimeApiError(
                RUNTIME_TOOL_NOT_AVAILABLE, "工具暂无已发布版本", 403,
            )
        result = await session.execute(
            select(CallerToolScope).where(
                CallerToolScope.system_id == system_id,
                CallerToolScope.status == ToolScopeStatus.ACTIVE,
            )
        )
        scopes = list(result.scalars().all())
        allowed = False
        for scope in scopes:
            if (
                scope.scope_type == ToolScopeType.TOOL
                and scope.scope_code == full_code
            ):
                allowed = True
                break
            if scope.scope_type == ToolScopeType.CAPABILITY:
                linked = await session.scalar(
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
                    allowed = True
                    break
        if not allowed:
            raise RuntimeApiError(
                RUNTIME_SCOPE_NOT_ALLOWED,
                f"调用系统无权执行工具: {full_code}",
                403,
            )

    async def _record_outcome(
        self,
        redis,
        system_id: str | None,
        request: Request,
        status_code: int,
        start: float,
        trace_id: str,
    ) -> None:
        """请求完成后记录熔断计数与 Trace 完成事件。"""
        if redis is not None and system_id is not None:
            policy = getattr(request.state, "runtime_policy", None)
            if policy is not None and policy.circuit_breaker_enabled:
                if status_code >= 500:
                    await self._guard.record_failure(
                        system_id, redis, self._security,
                    )
                else:
                    await self._guard.record_success(system_id, redis)
        await TraceService.log_event(
            trace_id=trace_id,
            system_id=system_id,
            action="runtime.request",
            status="success" if status_code < 500 else "failure",
            summary={
                "path": request.url.path,
                "http_status": status_code,
                "duration_ms": int((time.perf_counter() - start) * 1000),
            },
        )

    @staticmethod
    def _error_response(code: str, message: str, http_status: int, trace_id: str):
        """构造统一错误体。"""
        return JSONResponse(
            status_code=http_status,
            content={"code": code, "message": message, "trace_id": trace_id},
        )
