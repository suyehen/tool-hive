"""雪花 ID 生成器与 worker 租约（任务 B6）。

位分配、纪元、发号规则**全部照设计 §4.4 实现**，不在本文件重新解释那些数值——
需要核对时请看该节。

为什么单独成模块
----------------
雪花是**所有表的主键来源**（设计 §4.1 全局约定①）。它一旦产生重复，
后果不是"一条记录错了"，而是**整个库的主键约束失效**。所以它值得单独一个文件、
单独一组常量、单独的失败模式。

三条硬约束
----------
1. **绝不重复发号**。时钟大幅回退时**抛错拒绝**，而不是"猜一个"。
2. **纪元不可变**。§4.4 已写明上线后不能改，因此它是常量而非配置项。
3. **同一 (datacenter, worker) 只能有一个实例在发号**。靠 Redis 租约保证，
   并且**租约一旦失去，发号必须立刻停下**（见 :class:`WorkerLease` 的 guard）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Callable
from typing import Final

from redis.asyncio import Redis

from toolhive.adapters.cache.client import ScriptRegistry

__all__ = [
    "MAX_BACKWARD_MS",
    "MAX_SPIN_MS",
    "SNOWFLAKE_EPOCH_MS",
    "ClockBackwardsError",
    "LeaseNotAcquiredError",
    "SnowflakeError",
    "SnowflakeGenerator",
    "WorkerLease",
    "lease_key",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 位分配（设计 §4.4）—— 常量而非配置项
# ---------------------------------------------------------------------------

#: 起始纪元：2024-01-01T00:00:00Z。
#:
#: 🔴 **上线后不得修改**（设计 §4.4）：改纪元会让同一毫秒在新旧纪元下算出不同的
#: 时间戳部分，与已落库的 ID 直接撞车。做成常量而不是配置项，就是为了让它**不可能被顺手改掉**。
SNOWFLAKE_EPOCH_MS: Final = 1704067200000

_SEQUENCE_BITS: Final = 12
_WORKER_BITS: Final = 5
_DATACENTER_BITS: Final = 5

MAX_SEQUENCE: Final = (1 << _SEQUENCE_BITS) - 1  # 4095
MAX_WORKER_ID: Final = (1 << _WORKER_BITS) - 1  # 31
MAX_DATACENTER_ID: Final = (1 << _DATACENTER_BITS) - 1  # 31

_WORKER_SHIFT: Final = _SEQUENCE_BITS  # 12
_DATACENTER_SHIFT: Final = _SEQUENCE_BITS + _WORKER_BITS  # 17
_TIMESTAMP_SHIFT: Final = _SEQUENCE_BITS + _WORKER_BITS + _DATACENTER_BITS  # 22

#: 时钟回退的容忍上限（毫秒）。设计 §4.4：≤ 该值自旋等待，> 该值抛错。
#: 同样是常量——它影响正确性，不该被随手调。
MAX_BACKWARD_MS: Final = 5

#: 等待时钟前进的**安全上限**（毫秒）。超过即报错，而不是继续自旋。
#:
#: 正常等待有界且极短（序列用尽 ≤1ms、时钟回退 ≤5ms）。若超过这个上限，
#: 说明时钟被卡住了（虚拟机挂起、容器被冻结、``time_fn`` 被注入成不前进的值）。
#: **此时无限自旋比报错危险得多**：它会静默吃掉整个请求，且不留下任何日志——
#: 排查时只看到"接口挂了"，看不到原因。
MAX_SPIN_MS: Final = 50

#: 判定"租约已不可证明"时，相对真实 TTL **提前**的余量（毫秒）。
#:
#: **不能等到真实过期点才停发**：那一刻另一个实例已经可以 ``SET NX`` 拿到同一个
#: worker 号了，而我们可能刚好在这个窗口里又发了一个号。提前一点停，落在安全的一侧；
#: 下一次续租成功即自动恢复，不需要人工干预。
_LEASE_SAFETY_MARGIN_MS: Final = 1_000

#: 自旋等待的粒度：每轮让出一次 GIL，避免长时间独占 CPU。
_SPIN_YIELD_SECONDS: Final = 0.0


class SnowflakeError(RuntimeError):
    """雪花生成器的基类异常。"""


class ClockBackwardsError(SnowflakeError):
    """时钟回退超过容忍上限，**拒绝发号**（设计 §4.4）。

    这不是"坏掉了"，而是**故意的失败**：此时无法保证不重复，
    继续发号会静默产生重复主键，比直接报错危险得多。
    """


class LeaseNotAcquiredError(SnowflakeError):
    """worker 租约被别的实例占用，**拒绝启动**（设计 §4.4）。"""


# ---------------------------------------------------------------------------
# 生成器
# ---------------------------------------------------------------------------


class SnowflakeGenerator:
    """按设计 §4.4 发号。

    **线程安全**：内部持锁。多线程（例如同步 worker）与事件循环共用一个实例都没问题。

    关于"等待"路径会阻塞调用线程
    ----------------------------
    两条路径需要等待：序列用尽（同一毫秒超过 4096 个）与时钟小幅回退。
    两者都**有界且极短**（≤5ms），因此用自旋而非 ``time.sleep``：

    * Windows 上 ``time.sleep`` 的粒度约 15ms，会把这 1ms 的等待放大成十几毫秒；
    * 这两条路径在正常负载下**基本不会走到**（4096 ID/ms 远超本项目量级）。
    """

    __slots__ = (
        "_datacenter_id",
        "_epoch_ms",
        "_guard",
        "_issued",
        "_last_ms",
        "_lock",
        "_now_ms",
        "_sequence",
        "_worker_id",
    )

    def __init__(
        self,
        datacenter_id: int,
        worker_id: int,
        *,
        epoch_ms: int = SNOWFLAKE_EPOCH_MS,
        time_fn: Callable[[], int] | None = None,
        guard: Callable[[], None] | None = None,
    ) -> None:
        if not 0 <= datacenter_id <= MAX_DATACENTER_ID:
            raise ValueError(f"datacenter_id 必须在 0..{MAX_DATACENTER_ID}")
        if not 0 <= worker_id <= MAX_WORKER_ID:
            raise ValueError(f"worker_id 必须在 0..{MAX_WORKER_ID}")

        self._datacenter_id = datacenter_id
        self._worker_id = worker_id
        self._epoch_ms = epoch_ms
        #: 可注入的时钟。存在的意义是**让时钟回退可被确定性地验证**——
        #: 否则那条分支只能靠真的去改系统时间来测。
        self._now_ms = time_fn or (lambda: int(time.time() * 1000))
        self._last_ms = -1
        self._sequence = 0
        self._issued = 0

        import threading

        self._lock = threading.Lock()

        #: 每次发号前调用的守卫。用于"租约失去后立刻停发"（设计 §4.4）。
        self._guard = guard

    @property
    def issued_count(self) -> int:
        """已发号数量，供观测/日志使用。"""
        return self._issued

    def next_id(self) -> int:
        """产出一个 64 位正整数 ID。"""
        if self._guard is not None:
            # 在锁外调用：租约检查可能抛异常，不该占着发号锁。
            self._guard()

        with self._lock:
            now = self._now_ms()

            if now < self._last_ms:
                now = self._handle_backward(now)

            if now == self._last_ms:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    # 同一毫秒内 4096 个号已用完。等到下一毫秒——有界（≤1ms），
                    # 比抛错更可用；量级远超本项目，正常不会发生。
                    now = self._spin_until(self._last_ms + 1, reason="序列用尽，等待下一毫秒")
            else:
                self._sequence = 0

            self._last_ms = now
            self._issued += 1

            return (
                ((now - self._epoch_ms) << _TIMESTAMP_SHIFT)
                | (self._datacenter_id << _DATACENTER_SHIFT)
                | (self._worker_id << _WORKER_SHIFT)
                | self._sequence
            )

    def next_ids(self, count: int) -> list[int]:
        """连续产出 ``count`` 个 ID（便于批量插入时减少重复加锁）。"""
        return [self.next_id() for _ in range(count)]

    # -- 内部 ---------------------------------------------------------------

    def _handle_backward(self, now: int) -> int:
        """处理时钟回退。设计 §4.4：≤5ms 等待，>5ms 抛错。"""
        drift = self._last_ms - now
        if drift > MAX_BACKWARD_MS:
            raise ClockBackwardsError(
                f"时钟回退 {drift}ms，超过容忍上限 {MAX_BACKWARD_MS}ms，拒绝发号。"
                "此时无法保证不重复——请检查 NTP/虚拟机迁移等运维因素。"
                "（设计 §4.4：宁可拒绝服务，也不能产生重复主键）"
            )
        # 小幅回退：等到追上上次发号时间。大概率是 NTP 微调。
        _log.warning(
            "snowflake_clock_backward",
            extra={"drift_ms": drift, "tolerance_ms": MAX_BACKWARD_MS},
        )
        return self._spin_until(self._last_ms, reason=f"时钟回退 {drift}ms，等待追上")

    def _spin_until(self, target_ms: int, *, reason: str) -> int:
        """自旋到 ``_now_ms() >= target_ms``，返回到达时的时间。

        自旋而非 ``sleep``：等待有界（≤5ms），而 Windows 上 ``sleep`` 的粒度约 15ms，
        会把这 1ms 的等待放大成十几毫秒。

        **带上限**：用 ``time.monotonic()``（真实流逝时间，与可注入的时钟无关）计量，
        超过 :data:`MAX_SPIN_MS` 就抛错。没有这个上限的话，时钟一旦被卡住
        （VM 挂起、容器冻结），这里会永久自旋——请求静默挂死，日志里什么都没有。
        """
        deadline = time.monotonic() + MAX_SPIN_MS / 1000.0
        while True:
            now = self._now_ms()
            if now >= target_ms:
                return now
            if time.monotonic() >= deadline:
                raise SnowflakeError(
                    f"等待时钟前进已超过 {MAX_SPIN_MS}ms（{reason}）。"
                    "时钟可能被卡住了（虚拟机挂起 / 容器冻结）。拒绝发号——"
                    "继续自旋会静默挂死请求且不留日志。"
                )
            time.sleep(_SPIN_YIELD_SECONDS)  # 让出 GIL，不真的睡眠


# ---------------------------------------------------------------------------
# worker 租约
# ---------------------------------------------------------------------------


def lease_key(datacenter_id: int, worker_id: int) -> str:
    """租约 key（设计 §4.4）：``toolhive:snowflake:lease:{dc}:{worker}``。"""
    return f"toolhive:snowflake:lease:{datacenter_id}:{worker_id}"


class WorkerLease:
    """用 Redis 保证同一 ``(datacenter_id, worker_id)`` 只被一个实例持有。

    为什么必须有它：设计 §4.1 只说"多实例不得重复"，但**光靠配置保证不了**。
    两个实例配成同一个号，会各自从序列 0 开始发号，**产出完全相同的 ID**，
    而数据库只会报一个主键冲突——排查时极难定位到"是发号器撞了"。
    租约把这类**静默的数据损坏**变成**启动期失败**。

    生命周期::

        lease = WorkerLease(client, datacenter_id=1, worker_id=1)
        await lease.acquire()          # 抢不到就抛 LeaseNotAcquiredError
        lease.start_renewal()          # 后台续租；失去租约时 guard 会让发号立刻停下
        gen = SnowflakeGenerator(1, 1, guard=lease.ensure_held)
    """

    def __init__(
        self,
        client: Redis,
        *,
        datacenter_id: int,
        worker_id: int,
        ttl_ms: int = 30_000,
        instance_id: str | None = None,
        registry: ScriptRegistry | None = None,
    ) -> None:
        self._client = client
        self._datacenter_id = datacenter_id
        self._worker_id = worker_id
        self._ttl_ms = ttl_ms
        self._holder_id = instance_id or uuid.uuid4().hex
        self._registry = registry or ScriptRegistry()
        self._key = lease_key(datacenter_id, worker_id)
        self._renew_task: asyncio.Task[None] | None = None
        self._lost = False
        #: 最近一次**成功**续租（或抢占）的单调时刻。守卫靠它判断"还能不能证明自己持有租约"。
        #: 用单调时钟而非 wall clock：系统时间被调整时不该影响这个判断。
        self._last_renew_monotonic: float | None = None

    @property
    def key(self) -> str:
        return self._key

    @property
    def holder_id(self) -> str:
        return self._holder_id

    @property
    def lost(self) -> bool:
        """租约是否已经失去。失去后**必须停止发号**。"""
        return self._lost

    async def acquire(self) -> str:
        """抢占租约。抢不到抛 :class:`LeaseNotAcquiredError`。

        用 ``SET NX PX``：单条命令即原子，不需要 Lua。
        """
        ok = await self._client.set(self._key, self._holder_id, nx=True, px=self._ttl_ms)
        if not ok:
            current = await self._client.get(self._key)
            raise LeaseNotAcquiredError(
                f"(datacenter_id={self._datacenter_id}, worker_id={self._worker_id}) "
                f"已被实例 {current!r} 占用（key={self._key}）。"
                "两个实例用同一个号发号会产生**完全相同的 ID**——请改用不同的 "
                "TOOLHIVE_SNOWFLAKE_WORKER_ID，或确认那个实例已经下线（租约 "
                f"{self._ttl_ms}ms 后自动过期）。"
            )
        self._lost = False
        self._last_renew_monotonic = time.monotonic()
        _log.info(
            "snowflake_lease_acquired",
            extra={"key": self._key, "holder": self._holder_id, "ttl_ms": self._ttl_ms},
        )
        return self._holder_id

    async def renew(self) -> bool:
        """续租。返回是否**仍持有**。"""
        result = await self._registry.run(
            self._client, "worker_lease_renew", keys=[self._key],
            args=[self._holder_id, self._ttl_ms],
        )
        held = bool(result[0])
        if held:
            self._last_renew_monotonic = time.monotonic()
        else:
            self._lost = True
        return held

    async def release(self) -> bool:
        """主动释放（正常停机时用）。返回是否真的删掉了自己的租约。"""
        result = await self._registry.run(
            self._client, "worker_lease_release", keys=[self._key],
            args=[self._holder_id],
        )
        return bool(result[0])

    def ensure_held(self) -> None:
        """守卫：**无法证明仍持有租约**时抛错。传给 :class:`SnowflakeGenerator` 的 ``guard``。

        为什么要在**每次发号前**检查而不是只在启动时检查一次：租约可能因为
        Redis 抖动、网络分区或本进程长时间停顿而悄悄过期，而期间可能有另一个实例
        用同一个号启动并发号。此时继续发号的每一秒都在制造重复 ID。

        两道检查，缺一不可：

        1. ``_lost`` —— 续租**被明确拒绝**（key 已属于别人）。这是确定的丢失。
        2. ``_lease_unprovable`` —— 已经超过一个 TTL 没能**成功**续租。
           这一条覆盖的是"续租根本发不出去"的情况（Redis 从本实例不可达 / 网络分区）：
           此时 :meth:`renew` 是**抛异常**而不是返回 False，所以 ``_lost`` 不会被置位，
           但 key 的 TTL 在正常倒数——到期后别的实例就能接管同一个 worker 号。
           **只看 ``_lost`` 会漏掉这种情况，而这恰恰是最危险的一种。**

        设计 §4.4 的原则是"宁可拒绝服务，也不能产生重复主键"，所以这里选择抛错。
        下一次续租成功即自动恢复，不需要人工干预。
        """
        if self._lost:
            raise LeaseNotAcquiredError(
                f"worker 租约已被别的实例接管（key={self._key}）——"
                "**立即停止发号**，否则会产生重复主键。"
            )

        elapsed_ms = self.millis_since_last_renew
        if elapsed_ms is None or elapsed_ms >= self._unprovable_after_ms:
            raise LeaseNotAcquiredError(
                f"已连续超过 {self._unprovable_after_ms}ms 未能成功续租 worker 租约"
                f"（key={self._key}）——无法证明自己仍独占这个 (datacenter_id, worker_id)，"
                "**拒绝发号**。常见原因：Redis 不可达或网络分区。"
                "续租恢复后会自动继续。"
            )

    @property
    def millis_since_last_renew(self) -> float | None:
        """距上次成功续租（或抢占）过了多少毫秒。从未成功过则为 ``None``。"""
        if self._last_renew_monotonic is None:
            return None
        return (time.monotonic() - self._last_renew_monotonic) * 1000

    @property
    def _unprovable_after_ms(self) -> float:
        """超过这个时长没能成功续租，就认为租约不可证明。

        比真实 TTL 提前 ``_LEASE_SAFETY_MARGIN_MS``。余量上限取 TTL 的 1/3，
        以免 TTL 配得很小时余量把阈值压成负数或 0。
        """
        margin = min(_LEASE_SAFETY_MARGIN_MS, self._ttl_ms // 3)
        return float(self._ttl_ms - margin)

    def start_renewal(self) -> asyncio.Task[None]:
        """启动后台续租任务。续租间隔取 TTL 的 1/3，留两次重试余量。"""
        if self._renew_task is not None and not self._renew_task.done():
            return self._renew_task
        self._renew_task = asyncio.create_task(self._renew_loop())
        return self._renew_task

    async def stop_renewal(self) -> None:
        """停止后台续租并释放租约。"""
        task = self._renew_task
        self._renew_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await self.release()

    async def _renew_loop(self) -> None:
        interval = max(self._ttl_ms / 3000.0, 0.05)
        while True:
            await asyncio.sleep(interval)
            try:
                if not await self.renew():
                    # 失去租约 = 可能已有另一个实例在用同一个号发号。
                    # 这里只告警并标记；真正的"停发"由 ensure_held 在发号时强制。
                    _log.critical(
                        "snowflake_lease_lost",
                        extra={"key": self._key, "holder": self._holder_id},
                    )
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                # 续租**发不出去**（Redis 不可达 / 网络分区）。
                # 这里只告警、不置 _lost——但必须把"已经多久没能续租"记出来，
                # 否则运维只看到一串 warning，看不出租约正在走向不可证明。
                elapsed = self.millis_since_last_renew
                _log.warning(
                    "snowflake_lease_renew_failed",
                    extra={
                        "key": self._key,
                        "millis_since_last_renew": None if elapsed is None else round(elapsed),
                        "unprovable_after_ms": self._unprovable_after_ms,
                    },
                    exc_info=True,
                )
