"""Execute 幂等守卫：调用系统 + 幂等键 24h 窗口去重。"""

from __future__ import annotations

from redis.asyncio import Redis as AsyncRedis

from toolhive.runtime.errors import (
    RUNTIME_IDEMPOTENCY_CONFLICT,
    RuntimeApiError,
)

_IDEMPOTENCY_PREFIX = "toolhive:idempotency:"
IDEMPOTENCY_TTL_SECONDS = 24 * 3600


async def check_idempotency(
    system_id: str, idempotency_key: str | None, redis: AsyncRedis,
) -> None:
    """消费幂等键；重复键返回 RUNTIME_IDEMPOTENCY_CONFLICT。"""
    if not idempotency_key:
        return
    redis_key = f"{_IDEMPOTENCY_PREFIX}{system_id}:{idempotency_key}"
    created = await redis.set(
        redis_key, "1", nx=True, ex=IDEMPOTENCY_TTL_SECONDS,
    )
    if not created:
        raise RuntimeApiError(
            RUNTIME_IDEMPOTENCY_CONFLICT,
            "重复的幂等键，请勿重放请求",
            409,
        )
