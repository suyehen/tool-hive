"""D 可选内存 Lua 竞争回归；不代表真实 PostgreSQL/Redis 集成通过。"""

from __future__ import annotations

import asyncio
import importlib

from policy_selfcheck import exercise_redis
from toolhive.core.domain.grant_constraints import GrantConstraints
from toolhive.core.domain.models import ExecutionBinding, Provider, Tool, ToolVersion
from toolhive.core.policy.contracts import Authorization, GrantPolicy
from toolhive.core.policy.store import PolicyStore


async def main() -> None:
    fake = importlib.import_module("fakeredis")
    redis = fake.FakeAsyncRedis(decode_responses=True)
    auth = Authorization(
        2**60,
        Tool(id=2**60 + 1),
        ToolVersion(id=2**60 + 2),
        ExecutionBinding(id=2**60 + 3),
        Provider(id=2**60 + 4),
        (GrantPolicy(2**60 + 5, 2**60, "domain", "demo", 1, 1, 3, GrantConstraints()),),
    )
    try:
        await exercise_redis(PolicyStore(redis), auth)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
