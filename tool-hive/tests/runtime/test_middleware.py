"""运行侧中间件静态逻辑测试：API 范围匹配、Trace 归类与工具路径预校验。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from toolhive.core.enums import (
    CatalogObjectStatus,
    ToolScopeStatus,
    ToolScopeType,
)
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.models.catalog_tool import CatalogTool
from toolhive.runtime.errors import RUNTIME_SCOPE_NOT_ALLOWED, RuntimeApiError
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
