"""工具版本嵌套路由归属校验测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from toolhive.api.admin.catalog.versions import _require_version_owned
from toolhive.core.enums import ToolVersionStatus
from toolhive.core.exceptions import NotFoundError
from toolhive.models.catalog_tool_version import CatalogToolVersion


def _version() -> CatalogToolVersion:
    return CatalogToolVersion(
        id="ver-1",
        tool_id="tool-2",
        version="1.0.0",
        status=ToolVersionStatus.DRAFT,
    )


async def test_require_version_owned_accepts_matching_tool() -> None:
    """URL 工具与版本归属一致时正常返回版本。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_version())
    result = await _require_version_owned(db, "tool-2", "ver-1")
    assert result.id == "ver-1"


async def test_require_version_owned_rejects_wrong_tool() -> None:
    """URL 工具与版本归属不一致时按不存在处理。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_version())
    with pytest.raises(NotFoundError):
        await _require_version_owned(db, "tool-1", "ver-1")
