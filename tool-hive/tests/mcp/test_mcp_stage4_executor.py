"""MCP 阶段 4 测试：tools/call 执行闭环与 D1 需确认拒绝。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from toolhive.core.enums import CatalogObjectStatus, RiskLevel, ToolVersionStatus
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.mcp_tools.executor import McpCallExecutor


def _tool(**kwargs) -> CatalogTool:
    defaults = {
        "id": "tool_1",
        "namespace": "math.basic",
        "tool_code": "calculator",
        "name": "计算器",
        "status": CatalogObjectStatus.ENABLED,
        "discoverable": True,
        "executable": True,
        "mcp_enabled": True,
        "risk_level": RiskLevel.LOW,
        "default_version_id": "version_1",
        "input_schema": {
            "type": "object",
            "properties": {"a": {"type": "number"}},
            "required": ["a"],
        },
    }
    defaults.update(kwargs)
    return CatalogTool(**defaults)


def _version() -> CatalogToolVersion:
    return CatalogToolVersion(
        id="version_1",
        tool_id="tool_1",
        version="1.0.0",
        status=ToolVersionStatus.PUBLISHED,
    )


def _binding(method: str = "COMPUTE") -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding_1",
        version_id="version_1",
        provider_id="provider_1",
        method=method,
        path_template="builtin://math/add",
    )


def _provider() -> CatalogProvider:
    return CatalogProvider(
        id="provider_1",
        provider_code="builtin-math",
        name="内置数学",
        provider_type="builtin",
        status=CatalogObjectStatus.ENABLED,
    )


def _db_mock(
    *,
    tool: CatalogTool,
    version: CatalogToolVersion | None = None,
    binding: CatalogExecutionBinding | None = None,
    provider: CatalogProvider | None = None,
) -> AsyncMock:
    db = AsyncMock()
    db.scalar = AsyncMock(
        side_effect=[tool, binding] if binding else [tool],
    )
    db.get = AsyncMock(
        side_effect=[version, provider] if version else [version]
    )
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[]))
            )
        )
    )
    return db


def _executor(db) -> McpCallExecutor:
    return McpCallExecutor(db, client_id="client_1", source_ip="127.0.0.1")


async def test_executor_rejects_confirmation_required_tool() -> None:
    """D1 兜底：高风险工具直接拒绝、不进入执行。"""
    db = _db_mock(
        tool=_tool(risk_level=RiskLevel.HIGH),
        version=_version(),
        binding=_binding(),
        provider=_provider(),
    )
    with patch(
        "toolhive.runtime.mcp_tools.executor.scope_allows_tool",
        AsyncMock(return_value=True),
    ), patch(
        "toolhive.runtime.mcp_tools.executor.TraceService.log_event",
        AsyncMock(),
    ):
        outcome = await _executor(db).execute(
            "math.basic.calculator", {"a": 1},
        )
    assert outcome.is_error
    assert "确认" in outcome.text


async def test_executor_rejects_out_of_scope() -> None:
    """客户端未授权时返回不可用错误。"""
    db = _db_mock(tool=_tool())
    with patch(
        "toolhive.runtime.mcp_tools.executor.scope_allows_tool",
        AsyncMock(return_value=False),
    ), patch(
        "toolhive.runtime.mcp_tools.executor.TraceService.log_event",
        AsyncMock(),
    ):
        outcome = await _executor(db).execute(
            "math.basic.calculator", {"a": 1},
        )
    assert outcome.is_error
    assert "不可用" in outcome.text


async def test_executor_rejects_parameter_error() -> None:
    """参数不符合 Schema 时返回 isError，不调用 Provider。"""
    db = _db_mock(
        tool=_tool(),
        version=_version(),
        binding=_binding(),
        provider=_provider(),
    )
    with patch(
        "toolhive.runtime.mcp_tools.executor.scope_allows_tool",
        AsyncMock(return_value=True),
    ), patch(
        "toolhive.runtime.mcp_tools.executor.TraceService.log_event",
        AsyncMock(),
    ):
        outcome = await _executor(db).execute(
            "math.basic.calculator", {},
        )
    assert outcome.is_error
    assert "参数" in outcome.text


async def test_executor_success_path() -> None:
    """低风险只读工具经 Schema 校验后执行并返回结果。"""
    db = _db_mock(
        tool=_tool(),
        version=_version(),
        binding=_binding(),
        provider=_provider(),
    )
    gateway = MagicMock()
    gateway.execute = AsyncMock(return_value={"sum": 2})
    with patch(
        "toolhive.runtime.mcp_tools.executor.scope_allows_tool",
        AsyncMock(return_value=True),
    ), patch(
        "toolhive.runtime.mcp_tools.executor.TraceService.log_event",
        AsyncMock(),
    ), patch(
        "toolhive.runtime.mcp_tools.executor.get_redis",
        AsyncMock(),
    ), patch(
        "toolhive.runtime.mcp_tools.executor.ProviderGateway",
        return_value=gateway,
    ):
        outcome = await _executor(db).execute(
            "math.basic.calculator", {"a": 1},
        )
    assert not outcome.is_error
    assert '"sum": 2' in outcome.text
