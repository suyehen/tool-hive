"""MCP 阶段 5 测试：管理端暴露工具与调用记录查询服务。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from toolhive.core.enums import CatalogObjectStatus
from toolhive.core.operation_codes import OPERATION_META, OperationCode
from toolhive.models.catalog_tool import CatalogTool
from toolhive.models.runtime_trace_log import RuntimeTraceLog
from toolhive.services.mcp_exposed_tool_service import McpExposedToolService
from toolhive.services.mcp_trace_query_service import McpTraceQueryService


def _tool() -> CatalogTool:
    return CatalogTool(
        id="tool_1",
        namespace="math.basic",
        tool_code="calculator",
        name="计算器",
        status=CatalogObjectStatus.ENABLED,
        discoverable=True,
        mcp_enabled=True,
        default_version_id="version_1",
    )


def test_mcp_trace_view_operation_registered() -> None:
    """mcp_trace:view 操作码已登记。"""
    assert str(OperationCode.MCP_TRACE_VIEW) in OPERATION_META


async def test_exposed_tools_returns_default_version_only() -> None:
    """暴露工具仅返回存在默认已发布版本的工具。"""
    db = AsyncMock()
    rows = MagicMock(
        scalars=MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[_tool()]))
        ),
        all=MagicMock(return_value=[("tool_1", "1.0.0")]),
    )
    db.execute = AsyncMock(return_value=rows)
    items = await McpExposedToolService(db).list_exposed()
    assert len(items) == 1
    assert items[0].full_code == "math.basic.calculator"
    assert items[0].version == "1.0.0"


async def test_trace_records_pagination() -> None:
    """调用记录分页返回摘要行与总数。"""
    db = AsyncMock()
    event = RuntimeTraceLog(
        id="event_1",
        trace_id="trace_1",
        channel="mcp",
        action="runtime.execute",
        status="success",
    )
    db.scalar = AsyncMock(return_value=1)
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=[event]))
            )
        )
    )
    items, total = await McpTraceQueryService(db).list_records(offset=0, limit=20)
    assert total == 1
    assert items[0].trace_id == "trace_1"


async def test_trace_detail_returns_event_chain() -> None:
    """Trace 详情返回完整事件链。"""
    db = AsyncMock()
    events = [
        RuntimeTraceLog(
            id="event_1", trace_id="trace_1", channel="mcp",
            action="runtime.auth", status="success",
        ),
        RuntimeTraceLog(
            id="event_2", trace_id="trace_1", channel="mcp",
            action="runtime.execute", status="success",
        ),
    ]
    db.execute = AsyncMock(
        return_value=MagicMock(
            scalars=MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=events))
            )
        )
    )
    result = await McpTraceQueryService(db).get_events("trace_1")
    assert len(result) == 2
