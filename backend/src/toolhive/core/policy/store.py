"""策略用 Redis 机制入口；Lua 源码在 adapters/cache/scripts 中。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis

from toolhive.adapters.cache.client import ScriptRegistry


class PolicyStore:
    def __init__(self, redis: Redis, *, namespace: str = "toolhive") -> None:
        if not namespace or any(char in namespace for char in "*?[]{}"):
            raise ValueError("策略命名空间无效")
        self.redis = redis
        self.namespace = namespace
        self.scripts = ScriptRegistry()

    def key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    async def run(
        self,
        name: str,
        keys: Sequence[str],
        args: Sequence[str | int | float | bytes],
    ) -> list[Any]:
        return await self.scripts.run(self.redis, name, keys=keys, args=args)
