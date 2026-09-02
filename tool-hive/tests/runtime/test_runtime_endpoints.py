"""运行 API 端点测试：resolve / discover / execute / confirmations。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.api.runtime.v1.confirmations import (
    request_confirmation,
    verify_confirmation,
)
from toolhive.api.runtime.v1.schemas import (
    ConfirmRequest,
    DiscoverRequest,
    ExecuteRequest,
    ResolveRequest,
    VerifyConfirmRequest,
)
from toolhive.api.runtime.v1.tools import (
    discover_tools,
    execute_tool,
    resolve_tool,
)
from toolhive.core.enums import CatalogObjectStatus, RiskLevel
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.errors import RUNTIME_TOOL_NOT_FOUND, RuntimeApiError
from toolhive.runtime.tool_control.service import ControlDecision
from toolhive.runtime.tracing.service import TraceService


def _identity() -> SimpleNamespace:
    return SimpleNamespace(
        system=SimpleNamespace(system_id="sys_1"),
        source_ip="10.0.0.1",
        trace_id="trace-1",
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(caller_identity=_identity()))


def _tool(**kwargs) -> CatalogTool:
    defaults = dict(
        id="tool-1",
        namespace="math.basic",
        tool_code="calculator",
        name="计算器",
        description="数学计算",
        risk_level=RiskLevel.LOW,
        status=CatalogObjectStatus.ENABLED,
        discoverable=True,
        executable=True,
        row_version=0,
    )
    defaults.update(kwargs)
    return CatalogTool(**defaults)


def _version() -> CatalogToolVersion:
    return CatalogToolVersion(
        id="ver-1", tool_id="tool-1", version="1.0.0",
        input_schema={
            "type": "object",
            "required": ["a", "b"],
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        row_version=0,
    )


def _binding() -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding-1", version_id="ver-1", provider_id="prov-1",
        method="COMPUTE", path_template="builtin://math/add", row_version=0,
    )


def _provider() -> CatalogProvider:
    return CatalogProvider(
        id="prov-1", provider_code="builtin-math", name="内置计算",
        provider_type="builtin", status=CatalogObjectStatus.ENABLED,
        row_version=0,
    )


def _decision(**kwargs) -> ControlDecision:
    defaults = dict(
        allowed=True,
        discoverable=True,
        executable=True,
        tool=_tool(),
        version=_version(),
        binding=_binding(),
    )
    defaults.update(kwargs)
    return ControlDecision(**defaults)


@pytest.fixture(autouse=True)
def _patch_trace():
    """端点测试不落真实 Trace。"""
    trace_mock = AsyncMock()
    with patch.object(TraceService, "log_event", new=trace_mock):
        yield trace_mock


async def test_resolve_tool_returns_schema() -> None:
    """resolve 返回通过范围校验的工具 Schema。"""
    with patch(
        "toolhive.api.runtime.v1.tools.CallControlService"
    ) as control_cls:
        control_cls.return_value.resolve_tool = AsyncMock(
            return_value=_decision()
        )
        response = await resolve_tool(
            _request(), ResolveRequest(tool_code="math.basic.calculator"),
            db=AsyncMock(),
        )
    assert response.tool_code == "math.basic.calculator"
    assert response.version == "1.0.0"
    assert response.executable is True


async def test_resolve_tool_denied_raises() -> None:
    """resolve 拒绝时抛出稳定错误码。"""
    denied = _decision(
        allowed=False, discoverable=False, executable=False,
        error_code=RUNTIME_TOOL_NOT_FOUND, error_message="工具不存在",
    )
    with patch(
        "toolhive.api.runtime.v1.tools.CallControlService"
    ) as control_cls:
        control_cls.return_value.resolve_tool = AsyncMock(return_value=denied)
        with pytest.raises(RuntimeApiError) as exc_info:
            await resolve_tool(
                _request(), ResolveRequest(tool_code="x.y"),
                db=AsyncMock(),
            )
    assert exc_info.value.code == RUNTIME_TOOL_NOT_FOUND


async def test_discover_returns_controlled_candidates(_patch_trace) -> None:
    """discover 返回受控候选与降级标记。"""
    with patch("toolhive.api.runtime.v1.tools.RetrievalService") as retrieval_cls:
        retrieval_cls.return_value.discover = AsyncMock(
            return_value=(
                [
                    {
                        "tool_code": "math.basic.calculator",
                        "name": "计算器",
                        "description": None,
                        "risk_level": "low",
                        "version": "1.0.0",
                    }
                ],
                True,
            )
        )
        response = await discover_tools(
            _request(), DiscoverRequest(query="计算"), db=AsyncMock(),
        )
    assert response.total == 1
    assert response.items[0].tool_code == "math.basic.calculator"
    assert response.items[0].version == "1.0.0"
    assert response.degraded is True
    retrieval_calls = [
        call.kwargs
        for call in _patch_trace.call_args_list
        if call.kwargs.get("action") == "runtime.retrieval"
    ]
    assert retrieval_calls
    # TODO（明文记录）：query 原文进入 Trace 摘要
    assert retrieval_calls[0]["summary"]["query"] == "计算"
    assert retrieval_calls[0]["summary"]["degraded"] is True


async def test_execute_full_flow(_patch_trace) -> None:
    """execute 全链路：授权 + 参数校验 + 幂等 + Provider。"""
    with (
        patch("toolhive.api.runtime.v1.tools.CallControlService") as control_cls,
        patch("toolhive.api.runtime.v1.tools.CatalogProviderService") as provider_cls,
        patch("toolhive.api.runtime.v1.tools.ProviderGateway") as gateway_cls,
        patch("toolhive.api.runtime.v1.tools.check_idempotency", new=AsyncMock()),
    ):
        control_cls.return_value.evaluate_executable = AsyncMock(
            return_value=_decision()
        )
        provider_cls.return_value.get_provider = AsyncMock(
            return_value=_provider()
        )
        gateway_cls.return_value.execute = AsyncMock(
            return_value={"result": 3}
        )
        response = await execute_tool(
            _request(),
            "math.basic.calculator",
            ExecuteRequest(arguments={"a": 1, "b": 2}),
            db=AsyncMock(),
            redis=AsyncMock(),
        )
    assert response.result == {"result": 3}
    assert response.version == "1.0.0"
    execute_calls = [
        call.kwargs
        for call in _patch_trace.call_args_list
        if call.kwargs.get("action") == "runtime.execute"
    ]
    assert execute_calls
    # TODO（明文记录）：执行结果与哈希进入 Trace 摘要
    assert execute_calls[0]["summary"]["result"] == {"result": 3}
    assert execute_calls[0]["summary"]["result_sha256"]


async def test_execute_requires_confirmation_for_high_risk() -> None:
    """高风险工具缺少确认令牌时被拒绝。"""
    with patch("toolhive.api.runtime.v1.tools.CallControlService") as control_cls:
        control_cls.return_value.evaluate_executable = AsyncMock(
            return_value=_decision(
                tool=_tool(risk_level=RiskLevel.HIGH),
                confirmation_required=True,
            )
        )
        with pytest.raises(RuntimeApiError) as exc_info:
            await execute_tool(
                _request(),
                "math.basic.calculator",
                ExecuteRequest(arguments={"a": 1, "b": 2}),
                db=AsyncMock(),
                redis=AsyncMock(),
            )
    assert exc_info.value.code == "RUNTIME_CONFIRMATION_REQUIRED"


async def test_execute_validates_arguments() -> None:
    """参数不符合 Schema 时被拒绝。"""
    with patch("toolhive.api.runtime.v1.tools.CallControlService") as control_cls:
        control_cls.return_value.evaluate_executable = AsyncMock(
            return_value=_decision()
        )
        with pytest.raises(RuntimeApiError) as exc_info:
            await execute_tool(
                _request(),
                "math.basic.calculator",
                ExecuteRequest(arguments={"a": 1, "evil": 2}),
                db=AsyncMock(),
                redis=AsyncMock(),
            )
    assert exc_info.value.code == "RUNTIME_PARAMETER_INVALID"


async def test_execute_rejects_result_not_matching_output_schema(_patch_trace) -> None:
    """Provider 结果不符合声明 output_schema 时以运行错误拒绝。"""
    version = _version()
    version.output_schema = {"type": "array"}
    with (
        patch("toolhive.api.runtime.v1.tools.CallControlService") as control_cls,
        patch("toolhive.api.runtime.v1.tools.CatalogProviderService") as provider_cls,
        patch("toolhive.api.runtime.v1.tools.ProviderGateway") as gateway_cls,
    ):
        control_cls.return_value.evaluate_executable = AsyncMock(
            return_value=_decision(version=version)
        )
        provider_cls.return_value.get_provider = AsyncMock(
            return_value=_provider()
        )
        gateway_cls.return_value.execute = AsyncMock(
            return_value={"result": 3}
        )
        with pytest.raises(RuntimeApiError) as exc_info:
            await execute_tool(
                _request(),
                "math.basic.calculator",
                ExecuteRequest(arguments={"a": 1, "b": 2}),
                db=AsyncMock(),
                redis=AsyncMock(),
            )
    assert exc_info.value.code == "RUNTIME_PROVIDER_ERROR"


async def test_confirmation_request_and_verify() -> None:
    """确认申请返回令牌，校验消费成功。"""
    record = MagicMock()
    record.id = "confirm-1"
    record.tool_code = "math.basic.calculator"
    record.expires_at = datetime.now(UTC) + timedelta(minutes=5)
    with (
        patch(
            "toolhive.api.runtime.v1.confirmations.CallControlService"
        ) as control_cls,
        patch(
            "toolhive.api.runtime.v1.confirmations.ConfirmationService"
        ) as confirm_cls,
    ):
        control_cls.return_value.evaluate_executable = AsyncMock(
            return_value=_decision(
                tool=_tool(risk_level=RiskLevel.HIGH),
                confirmation_required=True,
            )
        )
        confirm_cls.return_value.request_confirmation = AsyncMock(
            return_value=(record, "token-abc")
        )
        created = await request_confirmation(
            _request(), ConfirmRequest(tool_code="math.basic.calculator"),
            db=AsyncMock(),
        )
        assert created.token == "token-abc"
        assert created.confirmation_id == "confirm-1"

        confirm_cls.return_value.verify_confirmation = AsyncMock(
            return_value=record
        )
        verified = await verify_confirmation(
            _request(),
            VerifyConfirmRequest(confirmation_id="confirm-1", token="token-abc"),
            db=AsyncMock(),
        )
    assert verified.valid is True
    assert verified.tool_code == "math.basic.calculator"
