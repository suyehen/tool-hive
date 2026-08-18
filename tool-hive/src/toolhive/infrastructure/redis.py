"""Redis / 共享缓存客户端。

连接在应用启动阶段通过 ``init_redis`` 显式初始化。
"""

from __future__ import annotations

from redis.asyncio import Redis as AsyncRedis

from toolhive.config import InfrastructureSettings

_redis: AsyncRedis | None = None


def init_redis(infrastructure: InfrastructureSettings) -> None:
    """启动阶段初始化 Redis 客户端。"""
    global _redis
    _redis = AsyncRedis.from_url(
        infrastructure.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )


async def get_redis() -> AsyncRedis:
    """返回全局 Redis 客户端。"""
    global _redis
    if _redis is None:
        raise RuntimeError("Redis 未初始化，请先调用 init_redis()")
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接（应用退出时调用）。"""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
