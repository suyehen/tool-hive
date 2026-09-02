"""Execute 幂等守卫测试。"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from toolhive.runtime.errors import RUNTIME_IDEMPOTENCY_CONFLICT, RuntimeApiError
from toolhive.runtime.execution.idempotency import (
    check_idempotency,
    update_idempotency_result,
)


async def test_idempotency_new_key_allowed() -> None:
    """新幂等键正常消费。"""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    await check_idempotency("sys_1", "key-1", redis)
    redis.set.assert_awaited_once()


async def test_idempotency_duplicate_rejected() -> None:
    """重复幂等键返回冲突。"""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=False)
    with pytest.raises(RuntimeApiError) as exc_info:
        await check_idempotency("sys_1", "key-1", redis)
    assert exc_info.value.code == RUNTIME_IDEMPOTENCY_CONFLICT


async def test_idempotency_missing_key_skipped() -> None:
    """未携带幂等键时跳过（读操作由调用方决定）。"""
    redis = AsyncMock()
    await check_idempotency("sys_1", None, redis)
    redis.set.assert_not_awaited()


async def test_idempotency_new_key_stores_processing_state() -> None:
    """新幂等键首次消费记录 processing 状态。"""
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)
    await check_idempotency("sys_1", "key-1", redis)
    payload = json.loads(redis.set.call_args.args[1])
    assert payload["status"] == "processing"


async def test_idempotency_terminal_state_records_trace() -> None:
    """终态更新保存状态与 trace_id，供结果查询与受控重试衔接。"""
    redis = AsyncMock()
    await update_idempotency_result(
        "sys_1", "key-1", redis, status="unknown", trace_id="trace-1",
    )
    payload = json.loads(redis.set.call_args.args[1])
    assert payload["status"] == "unknown"
    assert payload["trace_id"] == "trace-1"
