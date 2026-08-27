"""运行侧基础 Trace 服务测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from toolhive.runtime.errors import RUNTIME_PARAMETER_INVALID, RuntimeApiError
from toolhive.runtime.tracing.service import TraceService, new_trace_id, parse_trace_id


async def test_new_trace_id_format() -> None:
    """生成的 trace_id 为 32 位 hex。"""
    trace_id = new_trace_id()
    assert len(trace_id) == 32
    assert all(c in "0123456789abcdef" for c in trace_id)


async def test_parse_trace_id_missing_generates() -> None:
    """缺失时生成新 trace_id。"""
    first = parse_trace_id(None)
    second = parse_trace_id("")
    assert len(first) == 32
    assert len(second) == 32
    assert first != second


async def test_parse_trace_id_invalid_rejected() -> None:
    """非法 trace_id 返回 400。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        parse_trace_id("bad trace id!")
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_log_event_writes_record() -> None:
    """log_event 通过独立事务写入 Trace 记录。"""
    mock_session = AsyncMock()
    mock_session.add = MagicMock()
    context_manager = AsyncMock()
    context_manager.__aenter__ = AsyncMock(return_value=mock_session)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    mock_factory = MagicMock(return_value=context_manager)
    with patch(
        "toolhive.infrastructure.database.async_session_factory", mock_factory,
    ):
        await TraceService.log_event(
            trace_id="trace-1",
            system_id="sys_1",
            action="runtime.auth",
            status="success",
            source_ip="10.0.0.1",
        )
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()
