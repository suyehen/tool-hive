"""Redis 原子原语（任务 B3，设计 §7.2 / §9.1）。

本模块提供**机制**，不提供**策略**：
"允不允许"由脚本原子判定并返回，至于"限额设多少、超限后怎么办"是策略层（模块 D）的事。
这里不判断权限、不读配置、不写日志决定——只把一次原子操作做掉并把结果交回去。

四种原语与它们的用途
--------------------
======================  ==========================================================
原语                     用途
======================  ==========================================================
:meth:`token_bucket`    QPS 限流。稳态速率 + 允许突发。
:meth:`sliding_window`  "最近 N 毫秒不超过 M 次"。不会在窗口边界放行双倍流量。
:meth:`fixed_window`    **自然日配额**。日历对齐，是设计 §9.1 明确要求的窗口语义。
:meth:`semaphore_*`     并发控制。**租约式**，持有者崩溃后槽位自动释放。
======================  ==========================================================

关于 fail-open / fail-closed
----------------------------
设计 §7.2 给了完整矩阵（幂等 fail-closed、配额与并发 fail-open 并告警）。
**那个分类判断不在这里做**——本模块在 Redis 不可用时如实抛出异常，
由策略层按矩阵决定是放行还是拒绝。把分类写进原语会让它无法被复用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from redis.asyncio import Redis

from toolhive.adapters.cache.client import ScriptRegistry

__all__ = [
    "CachePrimitives",
    "LeaseDecision",
    "RateDecision",
    "now_ms",
    "quota_key",
]

#: Redis key 的命名空间前缀。集中在这里，避免各处手写字符串造成拼写漂移。
_NS: Final = "toolhive"


def now_ms() -> int:
    """当前毫秒时间戳。

    **一次请求只取一次**，然后把它传给所有原语——设计 §7.2 要求"一个整体 deadline
    从入口贯穿到出站"，时间基准同理。各原语自己取时间会导致阶段间的时间不一致。
    """
    return int(time.time() * 1000)


def quota_key(
    principal_id: int,
    scope_type: str,
    scope_value: str,
    window: str,
) -> str:
    """按设计 §9.1 生成配额 key：``quota:{principal_id}:{scope_type}:{scope_value}:{window}``。

    为什么把格式固化成一个函数：配额是**每个命中的 grant 各自计数**
    （domain / system / tag / tool 会同时命中多个），key 一旦拼错就会
    "看起来在限流、实际各限各的"，而这种错误不会报错、只会静默失效。

    ``window`` 用于区分同一个 scope 下的不同配额维度与周期，
    例如 ``qps`` / ``daily:20261005`` / ``concurrency``。
    """
    return f"{_NS}:quota:{principal_id}:{scope_type}:{scope_value}:{window}"


@dataclass(frozen=True, slots=True)
class RateDecision:
    """一次限流判定的结果。"""

    allowed: bool
    #: 放行后的剩余额度。语义随原语不同：令牌桶是剩余令牌数，
    #: 窗口计数是**已用**次数（窗口类原语的"剩余"没有稳定含义，故统一给已用数）。
    quantity: int
    #: 该原语对应的 key，便于调用方写日志/审计时定位。
    key: str


@dataclass(frozen=True, slots=True)
class LeaseDecision:
    """一次并发槽位申请的结果。"""

    acquired: bool
    #: 当前有效持有者数量（已剔除租约过期的）。
    current: int
    key: str


class CachePrimitives:
    """把 Redis 客户端与脚本注册表绑在一起，提供类型化调用。

    刻意做成**无状态**：所有可变状态都在 Redis 里，进程重启不丢。
    这也是设计 §7.2 要求"第一天就是分布式的"的直接含义。
    """

    def __init__(self, client: Redis, registry: ScriptRegistry | None = None) -> None:
        self._client = client
        self._registry = registry or ScriptRegistry()

    @property
    def registry(self) -> ScriptRegistry:
        return self._registry

    async def load_all(self) -> dict[str, str]:
        """启动时预热脚本，避免第一次调用多一次 ``NOSCRIPT`` 往返。"""
        return await self._registry.load_all(self._client)

    # -- 限流 ---------------------------------------------------------------

    async def token_bucket(
        self,
        *,
        key: str,
        capacity: int,
        refill_per_second: float,
        timestamp_ms: int,
        tokens: int = 1,
    ) -> RateDecision:
        """令牌桶。``capacity`` 是允许的突发量，``refill_per_second`` 是稳态速率。"""
        result = await self._registry.run(
            self._client,
            "token_bucket",
            keys=[key],
            args=[capacity, refill_per_second, timestamp_ms, tokens],
        )
        return RateDecision(allowed=bool(result[0]), quantity=int(result[1]), key=key)

    async def sliding_window(
        self,
        *,
        key: str,
        window_ms: int,
        limit: int,
        timestamp_ms: int,
        member: str,
    ) -> RateDecision:
        """滑动窗口。``member`` **必须每次请求唯一**，否则重复调用不计数（等于关掉限流）。"""
        result = await self._registry.run(
            self._client,
            "sliding_window",
            keys=[key],
            args=[window_ms, limit, timestamp_ms, member],
        )
        return RateDecision(allowed=bool(result[0]), quantity=int(result[1]), key=key)

    async def fixed_window(
        self,
        *,
        key: str,
        limit: int,
        expire_at: int,
    ) -> RateDecision:
        """固定窗口。用于自然日配额——``key`` 带日期、``expire_at`` 传当日结束的绝对秒。"""
        result = await self._registry.run(
            self._client,
            "fixed_window",
            keys=[key],
            args=[limit, expire_at],
        )
        return RateDecision(allowed=bool(result[0]), quantity=int(result[1]), key=key)

    # -- 并发 ---------------------------------------------------------------

    async def semaphore_acquire(
        self,
        *,
        key: str,
        limit: int,
        timestamp_ms: int,
        lease_ms: int,
        holder: str,
    ) -> LeaseDecision:
        """申请一个并发槽位。

        ``holder`` 同一次调用必须用同一个值：重复申请只会续租，不会多占槽位。
        ``lease_ms`` 是崩溃兜底——正常情况下应当显式 :meth:`semaphore_release`。
        """
        result = await self._registry.run(
            self._client,
            "semaphore_acquire",
            keys=[key],
            args=[limit, timestamp_ms, lease_ms, holder],
        )
        return LeaseDecision(acquired=bool(result[0]), current=int(result[1]), key=key)

    async def semaphore_release(self, *, key: str, holder: str) -> bool:
        """归还槽位。**幂等**——重复归还不报错，返回是否真的释放了一个。

        设计 §7.1 的归还矩阵要求"只要占用了就一定要还"，包括"出站前校验失败"。
        因此它通常写在 ``finally`` 里：此时**重复归还绝不能抛异常**，
        否则会把原始错误盖掉。
        """
        result = await self._registry.run(
            self._client,
            "semaphore_release",
            keys=[key],
            args=[holder],
        )
        return bool(result[0])
