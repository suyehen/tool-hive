"""运行侧 ToolContext 契约测试。"""

from __future__ import annotations

import pytest

from toolhive.runtime.context.schema import ToolContext, parse_tool_context
from toolhive.runtime.errors import RUNTIME_PARAMETER_INVALID, RuntimeApiError


async def test_parse_context_missing_returns_empty() -> None:
    """context 缺失时返回全空上下文。"""
    context = parse_tool_context(None)
    assert isinstance(context, ToolContext)
    assert context.user_id is None
    assert context.presence_summary() == {
        "user_id": False, "tenant_id": False, "role": False,
        "channel": False, "session_id": False,
    }


async def test_parse_context_valid_fields() -> None:
    """合法字段解析成功。"""
    context = parse_tool_context(
        {
            "user_id": "u-1",
            "tenant_id": "t-1",
            "role": "admin",
            "channel": "api",
            "session_id": "s-1",
        }
    )
    assert context.user_id == "u-1"
    assert context.presence_summary()["tenant_id"] is True


async def test_parse_context_rejects_unknown_field() -> None:
    """未知业务身份字段默认拒绝（防绕过）。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        parse_tool_context({"user_id": "u-1", "evil": "x"})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_parse_context_rejects_non_dict() -> None:
    """context 必须是 JSON 对象。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        parse_tool_context(["u-1"])
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_parse_context_rejects_non_string_value() -> None:
    """字段值必须是字符串。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        parse_tool_context({"user_id": 123})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_parse_context_rejects_empty_string() -> None:
    """空字符串字段拒绝。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        parse_tool_context({"user_id": "  "})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID


async def test_parse_context_rejects_overlong_value() -> None:
    """超长字段拒绝。"""
    with pytest.raises(RuntimeApiError) as exc_info:
        parse_tool_context({"user_id": "x" * 129})
    assert exc_info.value.code == RUNTIME_PARAMETER_INVALID
