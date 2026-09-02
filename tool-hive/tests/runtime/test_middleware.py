"""运行侧中间件静态逻辑测试：API 范围匹配、Trace 归类与工具路径预校验。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.core.enums import (
    CatalogObjectStatus,
    ToolScopeStatus,
    ToolScopeType,
)
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.models.catalog_tool import CatalogTool
from toolhive.runtime.errors import (
    RUNTIME_RATE_LIMITED,
    RUNTIME_SCOPE_NOT_ALLOWED,
    RuntimeApiError,
)
from toolhive.runtime.middleware import RuntimeSecurityMiddleware


def _middleware() -> RuntimeSecurityMiddleware:
    return RuntimeSecurityMiddleware.__new__(RuntimeSecurityMiddleware)


async def test_matches_api_pattern_exact_and_wildcard() -> None:
    """API 范围匹配：精确匹配与尾 * 前缀匹配。"""
    assert RuntimeSecurityMiddleware._matches_api_pattern(
        "/api/runtime/v1/tools/execute",
        ["/api/runtime/v1/tools/execute"],
    )
    assert RuntimeSecurityMiddleware._matches_api_pattern(
        "/api/runtime/v1/tools/a.b/execute",
        ["/api/runtime/v1/tools/*"],
    )
    assert not RuntimeSecurityMiddleware._matches_api_pattern(
        "/api/runtime/v1/ping",
        ["/api/runtime/v1/tools/execute"],
    )


async def test_trace_action_mapping() -> None:
    """错误码归类到对应 Trace 动作。"""
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_AUTH_REPLAYED_NONCE"
    ) == "runtime.auth"
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_SCOPE_NOT_ALLOWED"
    ) == "runtime.scope"
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_PROVIDER_ERROR"
    ) == "runtime.provider"
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_RETRIEVAL_UNAVAILABLE"
    ) == "runtime.retrieval"
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_CONFIRMATION_INVALID"
    ) == "runtime.confirmation"
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_PARAMETER_INVALID"
    ) == "runtime.request"
    assert RuntimeSecurityMiddleware._trace_action_for(
        "RUNTIME_RATE_LIMITED"
    ) == "runtime.traffic"


def _request(path: str) -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(path=path))


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


async def test_tool_path_scope_allowed_by_tool_scope() -> None:
    """execute 路径命中调用系统工具范围时放行。"""
    mw = _middleware()
    session = AsyncMock()
    tool = CatalogTool(
        namespace="math.basic", tool_code="calculator", name="计算器",
        status=CatalogObjectStatus.ENABLED, executable=True,
    )
    scope = CallerToolScope(
        system_id="sys_1", scope_type=ToolScopeType.TOOL,
        scope_code="math.basic.calculator", status=ToolScopeStatus.ACTIVE,
    )
    session.scalar = AsyncMock(side_effect=[tool, 1])
    session.execute = AsyncMock(return_value=_execute_result([scope]))
    await mw._check_tool_path_scope(
        _request("/api/runtime/v1/tools/math.basic.calculator/execute"),
        session,
        "sys_1",
    )


async def test_tool_path_scope_allowed_by_capability() -> None:
    """execute 路径命中能力包（包含该工具）时放行。"""
    mw = _middleware()
    session = AsyncMock()
    tool = CatalogTool(
        namespace="math.basic", tool_code="calculator", name="计算器",
        status=CatalogObjectStatus.ENABLED, executable=True,
    )
    scope = CallerToolScope(
        system_id="sys_1", scope_type=ToolScopeType.CAPABILITY,
        scope_code="basic-math", status=ToolScopeStatus.ACTIVE,
    )
    session.scalar = AsyncMock(side_effect=[tool, 1, "link-id"])
    session.execute = AsyncMock(return_value=_execute_result([scope]))
    await mw._check_tool_path_scope(
        _request("/api/runtime/v1/tools/math.basic.calculator/execute"),
        session,
        "sys_1",
    )


async def test_tool_path_scope_denied_without_scope() -> None:
    """未授权工具返回 RUNTIME_SCOPE_NOT_ALLOWED。"""
    mw = _middleware()
    session = AsyncMock()
    tool = CatalogTool(
        namespace="math.basic", tool_code="calculator", name="计算器",
        status=CatalogObjectStatus.ENABLED, executable=True,
    )
    session.scalar = AsyncMock(side_effect=[tool, 1])
    session.execute = AsyncMock(return_value=_execute_result([]))
    with pytest.raises(RuntimeApiError) as exc_info:
        await mw._check_tool_path_scope(
            _request("/api/runtime/v1/tools/math.basic.calculator/execute"),
            session,
            "sys_1",
        )
    assert exc_info.value.code == RUNTIME_SCOPE_NOT_ALLOWED


def _session_cm(session) -> MagicMock:
    """构造支持 async with 的会话工厂返回值。"""
    class _ContextManager:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    factory = MagicMock(return_value=_ContextManager())
    return factory


def _identity() -> SimpleNamespace:
    """构造认证通过后的调用身份。"""
    return SimpleNamespace(
        system=SimpleNamespace(system_id="sys_1"),
        key=SimpleNamespace(key_id="key_1"),
        source_ip="10.1.1.1",
        trace_id="trace-1",
    )


async def test_dispatch_does_not_release_when_guard_rejects() -> None:
    """流量检查拒绝（未获取并发槽位）时 finally 不得调用 release。"""
    mw = RuntimeSecurityMiddleware.__new__(RuntimeSecurityMiddleware)
    guard = SimpleNamespace(
        check=AsyncMock(
            side_effect=RuntimeApiError(
                RUNTIME_RATE_LIMITED, "QPS 超过上限", 429,
            )
        ),
        release=AsyncMock(),
    )
    mw._guard = guard
    mw._security = SimpleNamespace()
    mw._authorize = AsyncMock(
        return_value=SimpleNamespace(circuit_breaker_enabled=True)
    )
    request = SimpleNamespace(
        headers={},
        url=SimpleNamespace(path="/api/runtime/v1/tools/math.basic/execute"),
        state=SimpleNamespace(),
    )
    session = AsyncMock()
    with (
        patch("toolhive.runtime.middleware.parse_trace_id", return_value="trace-1"),
        patch(
            "toolhive.runtime.middleware.database.async_session_factory",
            return_value=_session_cm(session),
        ),
        patch("toolhive.runtime.middleware.get_redis", new=AsyncMock()),
        patch("toolhive.runtime.middleware.RuntimeAuthService") as auth_cls,
        patch(
            "toolhive.runtime.middleware.TraceService.log_event", new=AsyncMock(),
        ),
    ):
        auth_cls.return_value.authenticate = AsyncMock(return_value=_identity())
        await mw.dispatch(request, AsyncMock())
    guard.release.assert_not_awaited()


async def test_dispatch_releases_after_successful_acquire() -> None:
    """流量检查通过（并发槽位已获取）时 finally 释放一次。"""
    mw = RuntimeSecurityMiddleware.__new__(RuntimeSecurityMiddleware)
    guard = SimpleNamespace(check=AsyncMock(), release=AsyncMock())
    mw._guard = guard
    mw._security = SimpleNamespace()
    mw._authorize = AsyncMock(
        return_value=SimpleNamespace(
            circuit_breaker_enabled=False,
            request_timeout_seconds=30,
        )
    )
    request = SimpleNamespace(
        headers={},
        url=SimpleNamespace(path="/api/runtime/v1/ping"),
        state=SimpleNamespace(),
    )
    response = SimpleNamespace(status_code=200, headers={})
    session = AsyncMock()
    with (
        patch("toolhive.runtime.middleware.parse_trace_id", return_value="trace-1"),
        patch(
            "toolhive.runtime.middleware.database.async_session_factory",
            return_value=_session_cm(session),
        ),
        patch("toolhive.runtime.middleware.get_redis", new=AsyncMock()),
        patch("toolhive.runtime.middleware.RuntimeAuthService") as auth_cls,
        patch(
            "toolhive.runtime.middleware.TraceService.log_event", new=AsyncMock(),
        ),
    ):
        auth_cls.return_value.authenticate = AsyncMock(return_value=_identity())
        result = await mw.dispatch(request, AsyncMock(return_value=response))
    assert result.status_code == 200
    guard.release.assert_awaited_once()
