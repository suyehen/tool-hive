"""可选 Lua 回归，使用 fakeredis[lua] 的内存 Redis，不读取 .env。"""
from __future__ import annotations

import asyncio
import importlib

from toolhive.adapters.cache.client import ScriptRegistry
from toolhive.adapters.cache.primitives import CachePrimitives, now_ms
from toolhive.adapters.snowflake import LeaseNotAcquiredError, WorkerLease


async def main() -> None:
    try:
        fake = importlib.import_module("fakeredis")
    except ModuleNotFoundError as exc:
        raise SystemExit("此可选脚本需要隔离验证环境中的 fakeredis[lua]") from exc
    client = fake.FakeAsyncRedis(decode_responses=True)
    registry = ScriptRegistry()
    primitives = CachePrimitives(client, registry)
    try:
        t = now_ms()
        decision = await primitives.token_bucket(key="bucket", capacity=1,
            refill_per_second=1, timestamp_ms=t)
        assert decision.allowed
        decision = await primitives.token_bucket(key="bucket", capacity=1,
            refill_per_second=1, timestamp_ms=t - 10_000)
        assert not decision.allowed
        decision = await primitives.token_bucket(key="bucket", capacity=1,
            refill_per_second=1, timestamp_ms=t)
        assert not decision.allowed
        print("[PASS] clock rollback does not refill the same interval twice")

        await primitives.semaphore_acquire(key="semaphore", limit=2,
            timestamp_ms=t, lease_ms=10_000, holder="long")
        await primitives.semaphore_acquire(key="semaphore", limit=2,
            timestamp_ms=t, lease_ms=100, holder="short")
        assert await client.pttl("semaphore") >= 9_000
        blocked = await primitives.semaphore_acquire(key="semaphore", limit=2,
            timestamp_ms=t, lease_ms=100, holder="denied")
        assert not blocked.acquired
        assert await client.pttl("semaphore") >= 9_000
        print("[PASS] short and denied requests do not expire long holders")

        results = await asyncio.gather(*[
            primitives.semaphore_acquire(key="atomic", limit=3, timestamp_ms=t,
                                         lease_ms=10_000, holder=str(i))
            for i in range(50)
        ])
        assert sum(result.acquired for result in results) == 3
        print("[PASS] Lua semaphore preserves capacity under 50 concurrent requests")

        lease = WorkerLease(client, datacenter_id=1, worker_id=1, registry=registry)
        await lease.acquire()
        assert await lease.renew()
        await lease.release()
        try:
            lease.ensure_held()
        except LeaseNotAcquiredError:
            pass
        else:
            raise AssertionError("released lease remains usable")
        print("[PASS] scalar Lua lease replies and release guard")

        await client.script_flush()
        decision = await primitives.token_bucket(key="reloaded", capacity=1,
            refill_per_second=1, timestamp_ms=t)
        assert decision.allowed
        print("[PASS] NOSCRIPT recovery reloads actual Lua sources")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
