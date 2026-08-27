"""运行侧流量控制测试：QPS、配额、并发与熔断。"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from toolhive.config import RuntimeSecuritySettings
from toolhive.models.caller_runtime_policy import CallerRuntimePolicy
from toolhive.runtime.control.traffic import RuntimeTrafficGuard
from toolhive.runtime.errors import (
    RUNTIME_CIRCUIT_OPEN,
    RUNTIME_RATE_LIMITED,
    RuntimeApiError,
)


def _policy() -> CallerRuntimePolicy:
    return CallerRuntimePolicy(
        system_id="sys_1",
        allowed_api_patterns="[]",
        qps_limit=10,
        concurrency_limit=2,
        quota_per_day=100,
        request_timeout_seconds=30,
        circuit_breaker_enabled=True,
    )


def _security() -> RuntimeSecuritySettings:
    return RuntimeSecuritySettings(
        circuit_breaker_failure_threshold=3,
        circuit_breaker_window_seconds=60,
        circuit_breaker_open_seconds=30,
    )


async def test_qps_exceeded_rejected() -> None:
    """QPS 超过上限时返回 429。"""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    redis.incr = AsyncMock(return_value=11)
    redis.expire = AsyncMock()
    guard = RuntimeTrafficGuard()
    with pytest.raises(RuntimeApiError) as exc_info:
        await guard.check("sys_1", _policy(), redis, _security())
    assert exc_info.value.code == RUNTIME_RATE_LIMITED


async def test_quota_exceeded_rejected() -> None:
    """日配额超过上限时返回 429。"""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    redis.incr = AsyncMock(side_effect=[1, 101])
    redis.expire = AsyncMock()
    guard = RuntimeTrafficGuard()
    with pytest.raises(RuntimeApiError) as exc_info:
        await guard.check("sys_1", _policy(), redis, _security())
    assert exc_info.value.code == RUNTIME_RATE_LIMITED


async def test_concurrency_limit_rejected() -> None:
    """并发达到上限时拒绝第二个请求。"""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=0)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    guard = RuntimeTrafficGuard()
    policy = _policy()
    policy.concurrency_limit = 1
    await guard.check("sys_1", policy, redis, _security())
    with pytest.raises(RuntimeApiError) as exc_info:
        await guard.check("sys_1", policy, redis, _security())
    assert exc_info.value.code == RUNTIME_RATE_LIMITED
    await guard.release("sys_1")
    await guard.check("sys_1", policy, redis, _security())


async def test_circuit_open_rejected() -> None:
    """熔断打开时直接拒绝。"""
    redis = AsyncMock()
    redis.exists = AsyncMock(return_value=1)
    guard = RuntimeTrafficGuard()
    with pytest.raises(RuntimeApiError) as exc_info:
        await guard.check("sys_1", _policy(), redis, _security())
    assert exc_info.value.code == RUNTIME_CIRCUIT_OPEN


async def test_record_failure_opens_circuit_after_threshold() -> None:
    """连续失败达到阈值后打开熔断。"""
    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=[1, 2, 3])
    redis.expire = AsyncMock()
    redis.set = AsyncMock()
    guard = RuntimeTrafficGuard()
    security = _security()
    await guard.record_failure("sys_1", redis, security)
    await guard.record_failure("sys_1", redis, security)
    await guard.record_failure("sys_1", redis, security)
    redis.set.assert_awaited_once()


async def test_record_success_resets_failures() -> None:
    """请求成功时重置连续失败计数。"""
    redis = AsyncMock()
    redis.delete = AsyncMock()
    guard = RuntimeTrafficGuard()
    await guard.record_success("sys_1", redis)
    redis.delete.assert_awaited_once()
