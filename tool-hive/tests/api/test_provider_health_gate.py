"""Provider 启用健康检查测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from toolhive.api.admin.catalog.providers import enable_provider
from toolhive.core.enums import CatalogObjectStatus
from toolhive.models.catalog_provider import CatalogProvider


def _provider() -> CatalogProvider:
    return CatalogProvider(
        id="prov-1",
        provider_code="http-api",
        name="外部 API",
        provider_type="http",
        status=CatalogObjectStatus.DISABLED,
        target_security_config={
            "allowed_domains": ["api.example.com"],
            "allowed_ports": [443],
            "allowed_cidrs": [],
        },
        row_version=0,
    )


async def test_enable_provider_requires_healthy_check() -> None:
    """健康检查不通过时拒绝启用。"""
    with (
        patch(
            "toolhive.api.admin.catalog.providers.CatalogProviderService"
        ) as svc_cls,
        patch(
            "toolhive.api.admin.catalog.providers.check_provider_health",
            new=AsyncMock(return_value={"healthy": False, "detail": "目标不可达"}),
        ),
        patch(
            "toolhive.api.admin.catalog.providers._set_status",
            new=AsyncMock(),
        ) as set_status,
    ):
        svc_cls.return_value.get_provider = AsyncMock(return_value=_provider())
        with pytest.raises(HTTPException) as exc_info:
            await enable_provider(
                "prov-1", db=AsyncMock(), _account=object(),
            )
    assert exc_info.value.status_code == 400
    set_status.assert_not_awaited()


async def test_enable_provider_passes_healthy_check() -> None:
    """健康检查通过后执行启用。"""
    with (
        patch(
            "toolhive.api.admin.catalog.providers.CatalogProviderService"
        ) as svc_cls,
        patch(
            "toolhive.api.admin.catalog.providers.check_provider_health",
            new=AsyncMock(return_value={"healthy": True, "detail": "目标可达"}),
        ),
        patch(
            "toolhive.api.admin.catalog.providers._set_status",
            new=AsyncMock(return_value=object()),
        ) as set_status,
    ):
        svc_cls.return_value.get_provider = AsyncMock(return_value=_provider())
        db = AsyncMock()
        await enable_provider("prov-1", db=db, _account=object())
    set_status.assert_awaited_once_with("prov-1", "enabled", db)
