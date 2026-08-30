"""Provider 健康检查测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from toolhive.core.enums import CatalogObjectStatus
from toolhive.models.catalog_provider import CatalogProvider
from toolhive.runtime.execution.health import check_provider_health


def _provider(provider_type: str = "http", **kwargs) -> CatalogProvider:
    defaults = dict(
        id="prov-1",
        provider_code="http1",
        name="外部服务",
        provider_type=provider_type,
        status=CatalogObjectStatus.ENABLED,
        target_security_config={
            "allowed_domains": ["api.example.com"],
            "allowed_ports": [443],
            "protocols": ["https"],
            "allowed_cidrs": [],
        },
        row_version=0,
    )
    defaults.update(kwargs)
    return CatalogProvider(**defaults)


async def test_health_builtin_skips() -> None:
    """builtin Provider 无需出站健康检查。"""
    result = await check_provider_health(_provider(provider_type="builtin"))
    assert result["healthy"] is True


async def test_health_success() -> None:
    """解析与连接均成功时返回可达。"""
    client_mock = AsyncMock()
    client_mock.get = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = client_mock
    cm.__aexit__.return_value = False
    factory = MagicMock(return_value=cm)
    with (
        patch(
            "toolhive.runtime.execution.health.resolve_host",
            return_value=[],
        ),
        patch(
            "toolhive.runtime.execution.health.validate_resolved_addresses",
            new=MagicMock(),
        ),
        patch("toolhive.runtime.execution.health.httpx.AsyncClient", factory),
    ):
        result = await check_provider_health(_provider())
    assert result["healthy"] is True


async def test_health_dns_failure() -> None:
    """域名解析失败返回不可达。"""
    with patch(
        "toolhive.runtime.execution.health.resolve_host",
        side_effect=RuntimeError("dns down"),
    ):
        result = await check_provider_health(_provider())
    assert result["healthy"] is False
