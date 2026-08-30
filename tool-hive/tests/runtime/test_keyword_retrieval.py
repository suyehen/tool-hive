"""Discover 关键词检索测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from toolhive.core.enums import CatalogObjectStatus
from toolhive.models.catalog_tool import CatalogTool
from toolhive.runtime.retrieval.keyword import KeywordRetrieval, fetch_default_versions


def _tool(tool_code: str = "calculator", name: str = "计算器") -> CatalogTool:
    return CatalogTool(
        namespace="math.basic",
        tool_code=tool_code,
        name=name,
        status=CatalogObjectStatus.ENABLED,
        discoverable=True,
        row_version=0,
    )


def _execute_result(items: list) -> MagicMock:
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result


async def test_search_returns_empty_when_no_allowed_tools() -> None:
    """调用系统无可发现工具时返回空集合。"""
    db = AsyncMock()
    with patch(
        "toolhive.runtime.retrieval.keyword.CallControlService"
    ) as control_cls:
        control_cls.return_value.list_discoverable_tools = AsyncMock(
            return_value=[]
        )
        svc = KeywordRetrieval(db)
        assert await svc.search("sys_1", "计算", limit=20) == []


async def test_search_filters_by_keyword() -> None:
    """在受控集合内按关键词过滤。"""
    tool = _tool()
    db = AsyncMock()
    with patch(
        "toolhive.runtime.retrieval.keyword.CallControlService"
    ) as control_cls:
        control_cls.return_value.list_discoverable_tools = AsyncMock(
            return_value=[_tool()]
        )
        db.execute = AsyncMock(return_value=_execute_result([tool]))
        svc = KeywordRetrieval(db)
        result = await svc.search("sys_1", "计算", limit=20)
    assert [t.id for t in result] == [tool.id]
    # 关键词不命中时无结果
    with patch(
        "toolhive.runtime.retrieval.keyword.CallControlService"
    ) as control_cls:
        control_cls.return_value.list_discoverable_tools = AsyncMock(
            return_value=[_tool()]
        )
        db.execute = AsyncMock(return_value=_execute_result([]))
        assert await svc.search("sys_1", "不存在的关键词", limit=20) == []


async def test_fetch_default_versions() -> None:
    """返回工具 → 已发布版本号映射。"""
    db = AsyncMock()
    rows = MagicMock()
    rows.all.return_value = [("tool-1", "1.0.0"), ("tool-2", "2.0.0")]
    db.execute = AsyncMock(return_value=rows)
    tools = [_tool(), _tool(tool_code="power")]
    tools[0].id = "tool-1"
    tools[1].id = "tool-2"
    versions = await fetch_default_versions(db, tools)
    assert versions == {"tool-1": "1.0.0", "tool-2": "2.0.0"}
