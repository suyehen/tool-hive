"""管理端工具测试服务测试（一期仅 builtin）。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.core.enums import (
    CatalogObjectStatus,
    ProviderType,
    RiskLevel,
    ToolVersionStatus,
)
from toolhive.core.exceptions import ValidationError
from toolhive.models.catalog_execution_binding import CatalogExecutionBinding
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.catalog_tool_version import CatalogToolVersion
from toolhive.runtime.errors import RuntimeApiError
from toolhive.runtime.tracing.service import TraceService
from toolhive.services.catalog_test_service import CatalogTestService


def _tool(risk_level: str = RiskLevel.LOW, **kwargs) -> CatalogTool:
    defaults = dict(
        id="tool-1",
        namespace="math.basic",
        tool_code="calculator",
        name="数学计算器",
        risk_level=risk_level,
        status=CatalogObjectStatus.ENABLED,
        executable=True,
        default_version_id="ver-1",
        row_version=0,
    )
    defaults.update(kwargs)
    return CatalogTool(**defaults)


def _version() -> CatalogToolVersion:
    return CatalogToolVersion(
        id="ver-1", tool_id="tool-1", version="1.0.0",
        status=ToolVersionStatus.PUBLISHED,
        input_schema={
            "type": "object",
            "required": ["a", "b", "operation"],
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
                "operation": {"type": "string", "enum": ["add"]},
            },
            "additionalProperties": False,
        },
        row_version=0,
    )


def _binding() -> CatalogExecutionBinding:
    return CatalogExecutionBinding(
        id="binding-1", version_id="ver-1", provider_id="prov-1",
        method="COMPUTE", path_template="builtin://math/calculate",
        parameter_mapping={
            "a": "$.a", "b": "$.b", "operator": "$.operation",
        },
        row_version=0,
    )


def _provider(provider_type: str = ProviderType.BUILTIN) -> CatalogProvider:
    return CatalogProvider(
        id="prov-1", provider_code="builtin-math", name="内置计算",
        provider_type=provider_type, status=CatalogObjectStatus.ENABLED,
        row_version=0,
    )


@pytest.fixture(autouse=True)
def _patch_trace() -> None:
    with patch.object(TraceService, "log_event", new=AsyncMock()):
        yield


async def test_test_execute_builtin_success() -> None:
    """builtin 工具测试执行成功并返回结果。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(
        side_effect=lambda cls, pk: _tool() if cls is CatalogTool else None
    )
    svc = CatalogTestService(db)
    with (
        patch(
            "toolhive.services.catalog_test_service.CatalogVersionService"
        ) as version_cls,
        patch(
            "toolhive.services.catalog_test_service.CatalogProviderService"
        ) as provider_cls,
        patch(
            "toolhive.services.catalog_test_service.ProviderGateway"
        ) as gateway_cls,
    ):
        version_svc = version_cls.return_value
        version_svc.list_versions = AsyncMock(return_value=[_version()])
        version_svc.get_binding = AsyncMock(return_value=_binding())
        provider_cls.return_value.get_provider = AsyncMock(
            return_value=_provider()
        )
        gateway_cls.return_value.execute = AsyncMock(
            return_value={"result": 3}
        )
        result = await svc.test_execute(
            tool_id="tool-1",
            arguments={"a": 1, "b": 2, "operation": "add"},
        )
    assert result["result"] == {"result": 3}
    assert result["version"] == "1.0.0"


async def test_test_execute_rejects_http_provider() -> None:
    """管理端测试一期仅支持 builtin 类型。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(
        side_effect=lambda cls, pk: _tool() if cls is CatalogTool else None
    )
    svc = CatalogTestService(db)
    with (
        patch(
            "toolhive.services.catalog_test_service.CatalogVersionService"
        ) as version_cls,
        patch(
            "toolhive.services.catalog_test_service.CatalogProviderService"
        ) as provider_cls,
    ):
        version_cls.return_value.list_versions = AsyncMock(
            return_value=[_version()]
        )
        version_cls.return_value.get_binding = AsyncMock(
            return_value=_binding()
        )
        provider_cls.return_value.get_provider = AsyncMock(
            return_value=_provider(provider_type=ProviderType.HTTP)
        )
        with pytest.raises(ValidationError) as exc_info:
            await svc.test_execute(
                tool_id="tool-1",
                arguments={"a": 1, "b": 2, "operation": "add"},
            )
    assert "运行 API 验收" in str(exc_info.value)


async def test_test_execute_high_risk_requires_confirm() -> None:
    """高风险工具测试必须勾选确认。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(
        side_effect=lambda cls, pk: (
            _tool(risk_level=RiskLevel.HIGH) if cls is CatalogTool else None
        )
    )
    svc = CatalogTestService(db)
    with (
        patch(
            "toolhive.services.catalog_test_service.CatalogVersionService"
        ) as version_cls,
        patch(
            "toolhive.services.catalog_test_service.CatalogProviderService"
        ) as provider_cls,
    ):
        version_cls.return_value.list_versions = AsyncMock(
            return_value=[_version()]
        )
        version_cls.return_value.get_binding = AsyncMock(
            return_value=_binding()
        )
        provider_cls.return_value.get_provider = AsyncMock(
            return_value=_provider()
        )
        with pytest.raises(ValidationError) as exc_info:
            await svc.test_execute(
                tool_id="tool-1",
                arguments={"a": 1, "b": 2, "operation": "add"},
                confirm=False,
            )
    assert "确认" in str(exc_info.value)


async def test_test_execute_validates_arguments() -> None:
    """参数不符合 Schema 时拒绝。"""
    db = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(
        side_effect=lambda cls, pk: _tool() if cls is CatalogTool else None
    )
    svc = CatalogTestService(db)
    with (
        patch(
            "toolhive.services.catalog_test_service.CatalogVersionService"
        ) as version_cls,
        patch(
            "toolhive.services.catalog_test_service.CatalogProviderService"
        ) as provider_cls,
    ):
        version_cls.return_value.list_versions = AsyncMock(
            return_value=[_version()]
        )
        version_cls.return_value.get_binding = AsyncMock(
            return_value=_binding()
        )
        provider_cls.return_value.get_provider = AsyncMock(
            return_value=_provider()
        )
        with pytest.raises(RuntimeApiError):
            await svc.test_execute(
                tool_id="tool-1",
                arguments={"a": 1, "operation": "sqrt"},
            )
