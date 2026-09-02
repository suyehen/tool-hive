"""Execute 幂等守卫：调用系统 + 幂等键 24h 窗口去重与状态落库。"""

from __future__ import annotations

import json

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
    """消费幂等键并标记 processing；重复键返回 RUNTIME_IDEMPOTENCY_CONFLICT。"""
    if not idempotency_key:
        return
    redis_key = f"{_IDEMPOTENCY_PREFIX}{system_id}:{idempotency_key}"
    created = await redis.set(
        redis_key,
        json.dumps({"status": "processing"}, ensure_ascii=False),
        nx=True,
        ex=IDEMPOTENCY_TTL_SECONDS,
    )
    if not created:
        raise RuntimeApiError(
            RUNTIME_IDEMPOTENCY_CONFLICT,
            "重复的幂等键，请勿重放请求",
            409,
        )


async def update_idempotency_result(
    system_id: str,
    idempotency_key: str | None,
    redis: AsyncRedis,
    *,
    status: str,
    trace_id: str | None = None,
) -> None:
    """幂等键对应请求到达终态后更新状态（success / unknown），便于查询衔接。"""
    if not idempotency_key:
        return
    redis_key = f"{_IDEMPOTENCY_PREFIX}{system_id}:{idempotency_key}"
    await redis.set(
        redis_key,
        json.dumps({"status": status, "trace_id": trace_id}, ensure_ascii=False),
        ex=IDEMPOTENCY_TTL_SECONDS,
    )
