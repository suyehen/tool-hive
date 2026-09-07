"""MCP 阶段 3 测试：授权范围展开、MCP tools/list 过滤与 HTTP 协议开关。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from toolhive.core.enums import (
    CatalogObjectStatus,
    ToolScopeStatus,
    ToolScopeType,
)
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.mcp_client_scope import McpClientScope
from toolhive.runtime.mcp_tools.service import McpCatalogService
from toolhive.runtime.tool_control.scope_expansion import (
    expand_scope_tool_ids,
    scope_allows_tool,
)
from toolhive.runtime.tool_control.service import CallControlService


def _tool(
    *,
    tool_id: str = "tool_1",
    full_code: str = "math.basic.calculator",
    http_enabled: bool = True,
) -> CatalogTool:
    namespace, tool_code = full_code.rsplit(".", 1)
    return CatalogTool(
        id=tool_id,
        namespace=namespace,
        tool_code=tool_code,
        name="计算器",
        status=CatalogObjectStatus.ENABLED,
        discoverable=True,
        http_enabled=http_enabled,
        mcp_enabled=True,
        default_version_id="version_1",
    )


def _scope(scope_type: str, code: str) -> McpClientScope:
    return McpClientScope(
        client_id="client_1",
        scope_type=scope_type,
        scope_code=code,
        status=ToolScopeStatus.ACTIVE,
    )


def _rows_result(rows: list):
    return MagicMock(
        scalars=MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=rows))
        ),
        all=MagicMock(return_value=rows),
    )


async def test_expand_scope_tool_ids_by_tool_code() -> None:
    """工具范围编码展开为工具 ID。"""
    db = AsyncMock()
    db.execute = AsyncMock(return_value=_rows_result([("tool_1",)]))
    result = await expand_scope_tool_ids(
        db, [_scope(ToolScopeType.TOOL, "math.basic.calculator")],
    )
    assert result == {"tool_1"}


async def test_scope_allows_tool_by_namespace() -> None:
    """命名空间范围命中工具。"""
    db = AsyncMock()
    tool = _tool()
    assert await scope_allows_tool(db, [_scope(ToolScopeType.NAMESPACE, "math.basic")], tool)


async def test_mcp_list_authorized_filters_tools() -> None:
    """MCP tools/list 仅返回授权且实时可用的工具及其默认版本 Schema。"""
    db = AsyncMock()
    tool = _tool()
    tool.mcp_enabled = True
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
    db.execute = AsyncMock(
        side_effect=[
            _rows_result([_scope(ToolScopeType.TOOL, "math.basic.calculator")]),
            _rows_result([("tool_1",)]),
            _rows_result([tool]),
            _rows_result([("tool_1", schema)]),
        ]
    )
    service = McpCatalogService(db, "client_1")
    listings = await service.list_authorized()
    assert len(listings) == 1
    assert listings[0].full_code == "math.basic.calculator"
    assert listings[0].input_schema == schema


async def test_mcp_list_authorized_excludes_disabled_protocol() -> None:
    """mcp_enabled=False 的工具不进入 MCP 可发现集合。"""
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _rows_result([_scope(ToolScopeType.TOOL, "math.basic.calculator")]),
            _rows_result([("tool_1",)]),
            _rows_result([]),
        ]
    )
    service = McpCatalogService(db, "client_1")
    assert await service.list_authorized() == []


async def test_http_resolve_rejects_disabled_http_protocol() -> None:
    """http_enabled=False 的工具在 HTTP 精确解析时被拒绝。"""
    db = AsyncMock()
    db.get = AsyncMock(return_value=_tool(http_enabled=False))
    svc = CallControlService.__new__(CallControlService)
    svc.db = db
    decision = await svc._base_resolve_tool(
        "system_1", None, tool_id="tool_1",
    )
    assert not decision.allowed
    assert "TOOL_NOT_AVAILABLE" in (decision.error_code or "")
