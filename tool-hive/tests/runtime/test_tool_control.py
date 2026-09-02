"""运行侧工具调用控制测试：可发现 / 可执行区分与确认条件。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from toolhive.core.enums import (
    CatalogObjectStatus,
    RiskLevel,
    ToolScopeStatus,
    ToolScopeType,
    ToolVersionStatus,
)
from toolhive.models.caller_tool_scope import CallerToolScope
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.errors import (
    RUNTIME_SCOPE_NOT_ALLOWED,
    RUNTIME_TOOL_NOT_AVAILABLE,
    RUNTIME_TOOL_NOT_FOUND,
)
from toolhive.runtime.tool_control.service import CallControlService


def _tool(**kwargs) -> CatalogTool:
    defaults = dict(
        namespace="math.basic",
        tool_code="calculator",
        name="计算器",
        status=CatalogObjectStatus.ENABLED,
        discoverable=True,
        executable=True,
        risk_level=RiskLevel.LOW,
        default_version_id="ver-1",
        row_version=0,
    )
    defaults.update(kwargs)
    return CatalogTool(**defaults)


def _version(status: str = ToolVersionStatus.PUBLISHED) -> CatalogToolVersion:
    return CatalogToolVersion(
        id="ver-1",
        tool_id="tool-1",
        version="1.0.0",
        status=status,
        row_version=0,
    )


def _binding(method: str = "COMPUTE") -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding-1",
        version_id="ver-1",
        provider_id="prov-1",
        method=method,
        path_template="builtin://math/add",
        row_version=0,
    )


def _provider(status: str = CatalogObjectStatus.ENABLED) -> CatalogProvider:
    return CatalogProvider(
        provider_code="builtin-math",
        name="内置数学通道",
        provider_type="builtin",
        status=status,
        row_version=0,
    )


def _scope(
    scope_type: str = ToolScopeType.TOOL,
    scope_code: str = "math.basic.calculator",
) -> CallerToolScope:
    return CallerToolScope(
        system_id="sys_1",
        scope_type=scope_type,
        scope_code=scope_code,
        status=ToolScopeStatus.ACTIVE,
    )


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


async def test_resolve_tool_not_found() -> None:
    """工具不存在时返回 RUNTIME_TOOL_NOT_FOUND。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=None)
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", "math.basic.calculator")
    assert not decision.allowed
    assert decision.error_code == RUNTIME_TOOL_NOT_FOUND


async def test_resolve_tool_archived_or_hidden() -> None:
    """已归档或不可发现的工具返回 RUNTIME_TOOL_NOT_AVAILABLE。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_tool(status=CatalogObjectStatus.ARCHIVED))
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", "math.basic.calculator")
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_resolve_tool_out_of_scope() -> None:
    """调用系统范围未授权时返回 RUNTIME_SCOPE_NOT_ALLOWED。"""
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=_tool())
    db.execute = AsyncMock(return_value=_execute_result([]))
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", "math.basic.calculator")
    assert decision.error_code == RUNTIME_SCOPE_NOT_ALLOWED


async def test_resolve_tool_no_published_version() -> None:
    """无已发布版本时返回 RUNTIME_TOOL_NOT_AVAILABLE。"""
    tool = _tool(default_version_id=None)
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, None])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", "math.basic.calculator")
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_resolve_tool_discoverable() -> None:
    """范围内已发布工具可发现。"""
    tool = _tool()
    version = _version()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, None])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(return_value=version)
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", "math.basic.calculator")
    assert decision.allowed
    assert decision.discoverable
    assert not decision.executable
    assert not decision.confirmation_required


async def test_resolve_high_risk_reports_confirmation_required() -> None:
    """Resolve 决策输出与 Execute 同源的确认需求。"""
    tool = _tool(risk_level=RiskLevel.HIGH)
    version = _version()
    binding = _binding("COMPUTE")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(side_effect=[version, _provider()])
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", "math.basic.calculator")
    assert decision.allowed
    assert decision.confirmation_required


async def test_execute_rejects_non_executable_tool() -> None:
    """工具 executable=false 时不可执行。"""
    tool = _tool(executable=False)
    version = _version()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=tool)
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(return_value=version)
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert not decision.allowed
    assert decision.discoverable
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_execute_low_risk_compute_no_confirmation() -> None:
    """低风险只读计算不需要确认。"""
    tool = _tool()
    version = _version()
    binding = _binding("COMPUTE")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(side_effect=[version, _provider()])
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert decision.allowed
    assert decision.executable
    assert not decision.confirmation_required


async def test_execute_high_risk_requires_confirmation() -> None:
    """高风险工具必须确认。"""
    tool = _tool(risk_level=RiskLevel.HIGH)
    version = _version()
    binding = _binding("COMPUTE")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(side_effect=[version, _provider()])
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert decision.confirmation_required


async def test_execute_write_method_requires_confirmation() -> None:
    """写操作（POST）必须确认。"""
    tool = _tool()
    version = _version()
    binding = _binding("POST")
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(side_effect=[version, _provider()])
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert decision.confirmation_required


async def test_execute_rejects_disabled_provider() -> None:
    """Provider 已停用时执行决策必须拒绝。"""
    tool = _tool()
    version = _version()
    binding = _binding()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(
        side_effect=[version, _provider(status=CatalogObjectStatus.DISABLED)]
    )
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert not decision.allowed
    assert decision.discoverable
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_execute_rejects_missing_provider() -> None:
    """执行绑定指向的 Provider 不存在时执行决策必须拒绝。"""
    tool = _tool()
    version = _version()
    binding = _binding()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(side_effect=[version, None])
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert not decision.allowed
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_execute_explicit_version_must_be_published() -> None:
    """显式指定版本必须是已发布版本。"""
    tool = _tool()
    version = _version()
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, None, None])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(return_value=version)
    svc = CallControlService(db)
    decision = await svc.evaluate_executable(
        "sys_1", "math.basic.calculator", version="9.9.9",
    )
    assert not decision.allowed
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_execute_explicit_version_does_not_depend_on_default_provider() -> None:
    """显式指定版本时只校验目标版本 Provider，不被默认版本绑定状态阻塞。"""
    tool = _tool(default_version_id="ver-1")
    explicit_version = CatalogToolVersion(
        id="ver-2",
        tool_id="tool-1",
        version="2.0.0",
        status=ToolVersionStatus.PUBLISHED,
        row_version=0,
    )
    explicit_binding = _binding("COMPUTE")
    explicit_binding.version_id = "ver-2"
    explicit_binding.provider_id = "prov-2"
    db = AsyncMock()
    db.scalar = AsyncMock(
        side_effect=[tool, explicit_version, explicit_binding],
    )
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(return_value=_provider())
    svc = CallControlService(db)
    decision = await svc.evaluate_executable(
        "sys_1", "math.basic.calculator", version="2.0.0",
    )
    assert decision.allowed
    assert decision.version is not None
    assert decision.version.version == "2.0.0"


async def test_execute_without_version_denies_when_no_default_version() -> None:
    """未传版本且未配置默认版本时执行必须拒绝，不回退最新发布。"""
    tool = _tool(default_version_id=None)
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=tool)
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    svc = CallControlService(db)
    decision = await svc.evaluate_executable("sys_1", "math.basic.calculator")
    assert not decision.allowed
    assert decision.error_code == RUNTIME_TOOL_NOT_AVAILABLE


async def test_resolve_by_tool_id() -> None:
    """Resolve 支持按工具 ID 精确解析。"""
    tool = _tool()
    version = _version()
    db = AsyncMock()
    db.get = AsyncMock(side_effect=[tool, version])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.scalar = AsyncMock(return_value=None)
    svc = CallControlService(db)
    decision = await svc.resolve_tool("sys_1", tool_id="tool-1")
    assert decision.allowed
    assert decision.version is not None
    assert decision.version.version == "1.0.0"


async def test_resolve_honors_explicit_version() -> None:
    """Resolve 显式版本请求必须返回该已发布版本。"""
    tool = _tool()
    explicit_version = CatalogToolVersion(
        id="ver-2",
        tool_id="tool-1",
        version="2.0.0",
        status=ToolVersionStatus.PUBLISHED,
        row_version=0,
    )
    binding = _binding("COMPUTE")
    binding.version_id = "ver-2"
    db = AsyncMock()
    db.scalar = AsyncMock(side_effect=[tool, explicit_version, binding])
    db.execute = AsyncMock(return_value=_execute_result([_scope()]))
    db.get = AsyncMock(return_value=_provider())
    svc = CallControlService(db)
    decision = await svc.resolve_tool(
        "sys_1", "math.basic.calculator", version="2.0.0",
    )
    assert decision.allowed
    assert decision.version is not None
    assert decision.version.version == "2.0.0"


async def test_list_discoverable_tools_via_tool_scope() -> None:
    """工具范围命中且已发布时进入可发现集合。"""
    tool = _tool()
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _execute_result([_scope()]),
            _execute_result([tool]),
            MagicMock(all=MagicMock(return_value=[(tool.id,)])),
        ]
    )
    svc = CallControlService(db)
    tools = await svc.list_discoverable_tools("sys_1")
    assert [t.id for t in tools] == [tool.id]


async def test_list_discoverable_tools_filters_hidden_and_unpublished() -> None:
    """不可发现或未发布工具不进可发现集合。"""
    visible = _tool()
    hidden = _tool(tool_code="hidden", discoverable=False)
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _execute_result([_scope()]),
            _execute_result([visible, hidden]),
            MagicMock(
                all=MagicMock(return_value=[(visible.id,)]),
            ),
        ]
    )
    svc = CallControlService(db)
    tools = await svc.list_discoverable_tools("sys_1")
    assert [t.id for t in tools] == [visible.id]


async def test_list_discoverable_excludes_tools_without_enabled_pack_grant() -> None:
    """能力包授权缺失（含包已停用）时工具不进可发现集合。"""
    tool = _tool()
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _execute_result([_scope(ToolScopeType.CAPABILITY, "pack-1")]),
            _execute_result([tool]),
            MagicMock(all=MagicMock(return_value=[])),
        ]
    )
    svc = CallControlService(db)
    tools = await svc.list_discoverable_tools("sys_1")
    assert tools == []
