"""运行侧流量控制：QPS、日配额、并发、熔断。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime

from redis.asyncio import Redis as AsyncRedis

from toolhive.config import RuntimeSecuritySettings
from toolhive.models.caller_runtime_policy import CallerRuntimePolicy
from toolhive.runtime.errors import (
    RUNTIME_CIRCUIT_OPEN,
    RUNTIME_RATE_LIMITED,
    RuntimeApiError,
)

logger = logging.getLogger(__name__)

_QPS_KEY_PREFIX = "toolhive:qps:"
_QUOTA_KEY_PREFIX = "toolhive:quota:"
_CIRCUIT_FAIL_PREFIX = "toolhive:circuit:fail:"
_CIRCUIT_OPEN_PREFIX = "toolhive:circuit:open:"


class RuntimeTrafficGuard:
    """调用系统维度流量控制（一期单 Worker：并发计数在进程内）。

    一期仅支持单实例部署；多实例扩容前必须先迁移到 Redis 原子计数，
    否则各实例并发上限会按实例数放大。
    """

    def __init__(self) -> None:
        self._active: dict[str, int] = {}
        self._active_lock = asyncio.Lock()

    async def check(
        self,
        system_id: str,
        policy: CallerRuntimePolicy,
        redis: AsyncRedis,
        security: RuntimeSecuritySettings,
    ) -> None:
        """QPS / 日配额 / 熔断 / 并发检查，任一超限抛出 429/503。"""
        # 熔断开关关闭时跳过历史熔断状态检查（仅影响后续记录与否由中间件决定）
        if policy.circuit_breaker_enabled:
            await self._check_circuit(system_id, redis)
        await self._check_qps(system_id, policy.qps_limit, redis)
        await self._check_quota(system_id, policy.quota_per_day, redis)
        await self._acquire(system_id, policy.concurrency_limit)

    async def release(self, system_id: str) -> None:
        """释放并发占用。"""
        async with self._active_lock:
            current = self._active.get(system_id, 0)
            self._active[system_id] = max(0, current - 1)

    async def _acquire(self, system_id: str, limit: int) -> None:
        """进程内并发信号量：达到上限时拒绝。"""
        async with self._active_lock:
            current = self._active.get(system_id, 0)
            if current >= limit:
                raise RuntimeApiError(
                    RUNTIME_RATE_LIMITED,
                    "调用系统并发请求已达上限",
                    429,
                )
            self._active[system_id] = current + 1

    async def _check_qps(
        self, system_id: str, limit: int, redis: AsyncRedis,
    ) -> None:
        """固定 1 秒窗口 QPS 计数。"""
        window = int(time.time())
        key = f"{_QPS_KEY_PREFIX}{system_id}:{window}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 2)
        if count > limit:
            raise RuntimeApiError(
                RUNTIME_RATE_LIMITED,
                "调用系统 QPS 超过上限",
                429,
            )

    async def _check_quota(
        self, system_id: str, limit: int, redis: AsyncRedis,
    ) -> None:
        """按自然日配额计数。"""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = f"{_QUOTA_KEY_PREFIX}{system_id}:{today}"
        count = await redis.incr(key)
        if count == 1:
            # TTL 覆盖到次日再宽限 1 小时，避免跨日窗口漏计
            await redis.expire(key, 25 * 3600)
        if count > limit:
            raise RuntimeApiError(
                RUNTIME_RATE_LIMITED,
                "调用系统当日配额已用完",
                429,
            )

    async def _check_circuit(
        self, system_id: str, redis: AsyncRedis,
    ) -> None:
        """熔断开关检查。"""
        opened = await redis.exists(f"{_CIRCUIT_OPEN_PREFIX}{system_id}")
        if opened:
            raise RuntimeApiError(
                RUNTIME_CIRCUIT_OPEN,
                "调用系统触发熔断，请求被拒绝",
                503,
            )

    async def record_failure(
        self,
        system_id: str,
        redis: AsyncRedis,
        security: RuntimeSecuritySettings,
    ) -> None:
        """记录一次 5xx 失败；连续失败达到阈值时打开熔断。"""
        fail_key = f"{_CIRCUIT_FAIL_PREFIX}{system_id}"
        count = await redis.incr(fail_key)
        if count == 1:
            await redis.expire(fail_key, security.circuit_breaker_window_seconds)
        if count >= security.circuit_breaker_failure_threshold:
            await redis.set(
                f"{_CIRCUIT_OPEN_PREFIX}{system_id}",
                "1",
                ex=security.circuit_breaker_open_seconds,
            )
            logger.error(
                "runtime circuit opened system=%s failures=%s",
                system_id, count,
            )

    async def record_success(self, system_id: str, redis: AsyncRedis) -> None:
        """请求成功：重置连续失败计数（基础熔断按连续失败判定）。"""
        await redis.delete(f"{_CIRCUIT_FAIL_PREFIX}{system_id}")
