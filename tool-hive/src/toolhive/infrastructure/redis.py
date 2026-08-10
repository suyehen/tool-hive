"""Redis / 共享缓存客户端。"""

from __future__ import annotations

from redis.asyncio import Redis as AsyncRedis

from toolhive.config import settings

_redis: AsyncRedis | None = None


async def get_redis() -> AsyncRedis:
    """返回全局 Redis 客户端（惰性初始化，连接池复用）。"""
    global _redis
    if _redis is None:
        _redis = AsyncRedis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接（应用退出时调用）。"""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
