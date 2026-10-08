"""带 owner 的配额预留；中途拒绝、取消及 ACK 丢失都补偿已尝试的键。"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from redis.exceptions import RedisError

from toolhive.adapters.cache.primitives import CachePrimitives
from toolhive.core.policy.contracts import GrantPolicy
from toolhive.core.policy.degradation import Mechanism, dependency_failed
from toolhive.core.policy.errors import PolicyError
from toolhive.core.policy.store import PolicyStore


@dataclass(frozen=True)
class Reservation:
    keys: tuple[tuple[str, str, int], ...]
    owner: str = field(repr=False)
    lease_ms: int
    ttl_ms: int
    daily: bool


class ResourcePolicy:
    def __init__(self, store: PolicyStore, *, daily_timezone: str = "Asia/Shanghai") -> None:
        self.store = store
        self.timezone = ZoneInfo(daily_timezone)

    async def check_qps(self, grants: tuple[GrantPolicy, ...], *, timestamp_ms: int) -> None:
        primitives = CachePrimitives(self.store.redis, self.store.scripts)
        for grant in grants:
            if grant.qps is None:
                continue
            try:
                decision = await primitives.token_bucket(
                    key=self.store.key(f"qps:{grant.id}"),
                    capacity=grant.qps,
                    refill_per_second=grant.qps,
                    timestamp_ms=timestamp_ms,
                )
            except RedisError:
                dependency_failed(Mechanism.QPS)
                continue
            if not decision.allowed:
                raise PolicyError("TH_RATE_LIMITED", retry_after_ms=math.ceil(1000 / grant.qps))

    async def reserve(
        self,
        grants: tuple[GrantPolicy, ...],
        *,
        daily: bool,
        lease_ms: int,
        now: datetime,
    ) -> Reservation:
        """lease_ms 必须覆盖整个执行 deadline；出站前 commit_daily，finally release。

        daily 仅在确定未出站时 refund；未知结果不得退还每日额度。
        """
        if lease_ms <= 0 or now.tzinfo is None:
            raise ValueError("预留需要正租期与带时区时间")
        local = now.astimezone(self.timezone)
        midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        ttl_ms = (
            math.ceil((midnight - local).total_seconds() * 1000) + lease_ms + 60_000
            if daily
            else lease_ms * 2
        )
        attempted: list[tuple[str, str, int]] = []
        owner = uuid4().hex
        mechanism = Mechanism.DAILY if daily else Mechanism.CONCURRENCY
        try:
            for grant in grants:
                limit = grant.daily if daily else grant.concurrency
                if limit is None:
                    continue
                suffix = f"daily:{grant.id}:{local.date()}" if daily else f"concurrency:{grant.id}"
                pair = (
                    self.store.key(suffix + ":pending"),
                    self.store.key(suffix + ":used"),
                    limit,
                )
                attempted.append(pair)  # 包括 Lua 成功但返回 ACK 丢失的当前键。
                receipt = Reservation(tuple(attempted), owner, lease_ms, ttl_ms, daily)
                try:
                    accepted = await self._operation(receipt, pair, "acquire")
                except RedisError:
                    dependency_failed(mechanism)
                    await self.release(Reservation((pair,), owner, lease_ms, ttl_ms, daily))
                    attempted.pop()
                    continue
                if not accepted:
                    raise PolicyError("TH_QUOTA_EXCEEDED" if daily else "TH_CONCURRENCY_LIMITED")
        except BaseException:
            receipt = Reservation(tuple(attempted), owner, lease_ms, ttl_ms, daily)
            await asyncio.shield(self.release(receipt))
            raise
        return Reservation(tuple(attempted), owner, lease_ms, ttl_ms, daily)

    async def _operation(self, receipt: Reservation, pair: tuple[str, str, int], op: str) -> bool:
        result = await self.store.run(
            "policy_reservation",
            pair[:2],
            [
                op,
                receipt.owner,
                pair[2],
                receipt.lease_ms,
                receipt.ttl_ms,
                int(receipt.daily),
            ],
        )
        return bool(int(result[0]))

    async def renew(self, receipt: Reservation) -> None:
        for pair in receipt.keys:
            try:
                if not await self._operation(receipt, pair, "renew"):
                    raise PolicyError(
                        "TH_CONCURRENCY_LIMITED" if not receipt.daily else "TH_QUOTA_EXCEEDED"
                    )
            except RedisError:
                dependency_failed(Mechanism.DAILY if receipt.daily else Mechanism.CONCURRENCY)

    async def commit_daily(self, receipt: Reservation) -> None:
        if not receipt.daily:
            raise ValueError("只能提交每日额度")
        for pair in receipt.keys:
            try:
                if not await self._operation(receipt, pair, "commit"):
                    raise PolicyError("TH_QUOTA_EXCEEDED")
            except RedisError:
                dependency_failed(Mechanism.DAILY)

    async def release(self, receipt: Reservation) -> None:
        """并发释放 / 出站前每日补偿，owner CAS 使重复调用安全。"""
        for pair in receipt.keys:
            try:
                await self._operation(receipt, pair, "release")
            except RedisError:
                dependency_failed(Mechanism.DAILY if receipt.daily else Mechanism.CONCURRENCY)
