"""模块 B 的运行时自检（回归用）。

    F:\\soft\\anaconda\\envs\\toolhive\\python.exe scripts\\selfcheck.py

为什么需要它
------------
模块 B 有约 1700 行，此前**只被 ruff/mypy 静态检查覆盖**，运行时行为没有任何自动回归。
一个行级缺陷就是这样漏过去的：``semaphore_acquire.lua`` 把 ``current < limit`` 挡在
``ZADD`` 前面，导致**槽位满时持有者无法续租**——租约到期后槽位被自动回收，
而持有者仍以为自己占着，实际并发数于是突破上限，**互斥被击穿**。
静态检查看不出这种问题。

M0 的决定仍然是"不建测试套件"（设计 §14.3），所以本脚本是**手动执行**的。
但它与一次性验证脚本的本质区别是：**它可以被重复执行**。
改完代码跑一遍，就能知道有没有把运行时行为改坏。

基础设施不可达时**跳过而不是失败**——它不该成为"没开数据库就没法验证代码"的阻碍。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ⚠️ SQLAlchemy 的 Mapped / mapped_column 必须在**模块级**导入。
# 本文件有 `from __future__ import annotations`，注解在运行期是字符串，
# SQLAlchemy 需要能在模块命名空间里解析出 "Mapped" 这个名字；
# 只写在函数内部 import 会报 MappedAnnotationError。
from sqlalchemy.orm import Mapped, mapped_column

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_KEY_PREFIX = "toolhive:selfcheck:"


@dataclass
class Report:
    """收集结果。``skip`` 用于基础设施不可达——不算失败。"""

    lines: list[tuple[str, str]] = field(default_factory=list)

    def check(self, name: str, passed: bool) -> bool:
        self.lines.append((PASS if passed else FAIL, name))
        return passed

    def skip(self, reason: str) -> None:
        self.lines.append((SKIP, reason))

    @property
    def failed(self) -> int:
        return sum(1 for status, _ in self.lines if status == FAIL)

    @property
    def passed(self) -> int:
        return sum(1 for status, _ in self.lines if status == PASS)

    def render(self) -> str:
        out = [f"  [{status}] {name}" for status, name in self.lines]
        out.append("")
        out.append(f"通过 {self.passed} / 失败 {self.failed}")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# Redis 原语（含 BUG-1 回归）
# ---------------------------------------------------------------------------


async def check_cache(report: Report) -> None:
    from toolhive.adapters.cache.client import ScriptRegistry, create_client, ping
    from toolhive.adapters.cache.primitives import CachePrimitives, now_ms
    from toolhive.config import load_settings

    settings = load_settings(BACKEND_ROOT / ".env")
    client = create_client(settings.redis)
    if not await ping(client):
        report.skip("Redis 不可达，跳过缓存原语自检")
        await client.aclose()
        return

    prim = CachePrimitives(client, ScriptRegistry())
    await prim.load_all()
    stale = [k async for k in client.scan_iter(match=_KEY_PREFIX + "*")]
    if stale:
        await client.delete(*stale)

    try:
        # --- BUG-1 回归：槽位满时持有者必须能续租 ---
        #
        # 容量 1。h1 先占住，此时 current == limit == 1。
        # 旧实现把 `current < limit` 挡在 ZADD 前面 → h1 的续租被跳过 →
        # 原租约到期后被 ZREMRANGEBYSCORE 回收 → h2 就能抢到 —— 并发上限被突破。
        key = _KEY_PREFIX + "sem-renew"
        t0 = now_ms()
        lease = 800
        first = await prim.semaphore_acquire(
            key=key, limit=1, timestamp_ms=t0, lease_ms=lease, holder="h1"
        )
        report.check("信号量：首个持有者拿到槽位", first.acquired)
        # 槽位已满时续租 —— 这正是旧实现失败的场景
        renewed = await prim.semaphore_acquire(
            key=key, limit=1, timestamp_ms=t0 + 400, lease_ms=lease, holder="h1"
        )
        report.check("信号量：槽位已满时持有者仍能续租（BUG-1 回归）", renewed.acquired)
        report.check("信号量：续租不增加持有者数", renewed.current == 1)
        # 越过**原**租约到期点（t0+800），但仍在续租后的到期点（t0+1200）之内
        blocked = await prim.semaphore_acquire(
            key=key, limit=1, timestamp_ms=t0 + 1000, lease_ms=lease, holder="h2"
        )
        report.check("信号量：续租生效后他人仍被拒（互斥未被击穿）", not blocked.acquired)

        # --- 租约过期自愈 ---
        key = _KEY_PREFIX + "sem-expire"
        t = now_ms()
        await prim.semaphore_acquire(key=key, limit=1, timestamp_ms=t, lease_ms=500, holder="dead")
        healed = await prim.semaphore_acquire(
            key=key, limit=1, timestamp_ms=t + 1000, lease_ms=500, holder="alive"
        )
        report.check("信号量：租约到期后槽位自动回收", healed.acquired)

        # --- 归还幂等 ---
        key = _KEY_PREFIX + "sem-release"
        t = now_ms()
        await prim.semaphore_acquire(key=key, limit=1, timestamp_ms=t, lease_ms=5000, holder="x")
        report.check("信号量：归还成功", await prim.semaphore_release(key=key, holder="x"))
        report.check("信号量：重复归还安全（返回 False 而不报错）",
                     (await prim.semaphore_release(key=key, holder="x")) is False)

        # --- 限流原语 ---
        key = _KEY_PREFIX + "tb"
        t = now_ms()
        got = [
            await prim.token_bucket(key=key, capacity=3, refill_per_second=1.0, timestamp_ms=t)
            for _ in range(5)
        ]
        report.check("令牌桶：突发上限精确", [int(d.allowed) for d in got] == [1, 1, 1, 0, 0])
        got = [
            await prim.token_bucket(
                key=key, capacity=3, refill_per_second=1.0, timestamp_ms=t + 2000
            )
            for _ in range(3)
        ]
        report.check("令牌桶：按时间补充", [int(d.allowed) for d in got] == [1, 1, 0])

        key = _KEY_PREFIX + "fw"
        got = [
            await prim.fixed_window(key=key, limit=2, expire_at=int(now_ms() / 1000) + 600)
            for _ in range(3)
        ]
        report.check("固定窗口：自然日配额计数", [int(d.allowed) for d in got] == [1, 1, 0])
        report.check("固定窗口：自动设置 TTL", await client.ttl(key) > 0)

        key = _KEY_PREFIX + "sw"
        t = now_ms()
        got = [
            await prim.sliding_window(
                key=key, window_ms=1000, limit=2, timestamp_ms=t, member=str(uuid.uuid4())
            )
            for _ in range(3)
        ]
        report.check("滑动窗口：窗口内上限", [int(d.allowed) for d in got] == [1, 1, 0])

        # --- 原子性 ---
        key = _KEY_PREFIX + "atomic-bucket"
        t = now_ms()
        bucket_res = await asyncio.gather(*[
            prim.token_bucket(key=key, capacity=5, refill_per_second=0.0, timestamp_ms=t)
            for _ in range(50)
        ])
        report.check("原子性：50 并发令牌桶恰好放行 5",
                     sum(1 for r in bucket_res if r.allowed) == 5)

        key = _KEY_PREFIX + "atomic-sem"
        t = now_ms()
        sem_res = await asyncio.gather(*[
            prim.semaphore_acquire(key=key, limit=7, timestamp_ms=t, lease_ms=5000, holder=f"h{i}")
            for i in range(50)
        ])
        report.check("原子性：50 并发抢 7 个槽位恰好 7 个成功",
                     sum(1 for r in sem_res if r.acquired) == 7)

        # --- BUG-5 回归：参数校验必须早失败且指得准 ---
        reg = prim.registry
        for label, kwargs, exc in (
            ("key 非 str", {"keys": [None]}, TypeError),
            ("key 为空串", {"keys": [""]}, ValueError),
            ("参数为 None", {"keys": ["k"], "args": [None]}, TypeError),
            ("参数为 dict", {"keys": ["k"], "args": [{}]}, TypeError),
            ("参数为 nan", {"keys": ["k"], "args": [float("nan")]}, ValueError),
        ):
            try:
                await reg.run(client, "token_bucket", **kwargs)
                report.check(f"参数校验：{label} 必须报错", False)
            except exc as error:
                report.check(f"参数校验：{label} —— {type(error).__name__}", True)
        # 合法参数不应被误拦
        report.check(
            "参数校验：合法参数不被误拦",
            bool(await reg.run(client, "token_bucket", keys=["k"], args=[1, 1.0, now_ms(), 1])),
        )
    finally:
        stale = [k async for k in client.scan_iter(match=_KEY_PREFIX + "*")]
        if stale:
            await client.delete(*stale)
        await client.aclose()


# ---------------------------------------------------------------------------
# 雪花 ID
# ---------------------------------------------------------------------------


async def check_snowflake(report: Report) -> None:
    from toolhive.adapters.snowflake import SnowflakeGenerator

    gen = SnowflakeGenerator(3, 9)
    t0 = time.perf_counter()
    bulk = gen.next_ids(100_000)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    report.check(f"雪花：10w 次无重复（{elapsed_ms:.0f}ms）", len(set(bulk)) == 100_000)
    report.check("雪花：严格递增", all(bulk[i] < bulk[i + 1] for i in range(len(bulk) - 1)))
    report.check("雪花：全部为 64 位正整数", all(0 < x < 2**63 for x in bulk))
    report.check(
        "雪花：解构出的 dc/worker 正确",
        all(((x >> 17) & 31, (x >> 12) & 31) == (3, 9) for x in bulk[:1000]),
    )

    # --- 租约守卫回归：**续租一直发不出去**时也必须停止发号 ---
    #
    # 旧实现只看 _lost（"续租被明确拒绝"）。但 Redis 从本实例不可达时，
    # renew() 是**抛异常**而不是返回 False，_lost 不会置位 —— 于是继续发号，
    # 而 key 的 TTL 在正常倒数，到期后别的实例就能接管同一个 worker 号。
    # 下面这几条把"续租发不出去"这条路径钉住。纯逻辑，不依赖 Redis。
    from typing import cast

    from redis.asyncio import Redis

    from toolhive.adapters.snowflake import LeaseNotAcquiredError, WorkerLease

    lease = WorkerLease(cast("Redis", object()), datacenter_id=1, worker_id=1, ttl_ms=30_000)

    def guard_allows() -> bool:
        try:
            lease.ensure_held()
        except LeaseNotAcquiredError:
            return False
        return True

    lease._last_renew_monotonic = time.monotonic()
    report.check("租约守卫：刚续租成功时放行", guard_allows())

    lease._last_renew_monotonic = time.monotonic() - 20.0
    report.check("租约守卫：TTL 内未超阈值时仍放行", guard_allows())

    lease._last_renew_monotonic = time.monotonic() - 31.0
    report.check(
        "租约守卫：超过 TTL 未成功续租时拒绝发号（本轮修复）", not guard_allows()
    )

    lease._lost = True
    lease._last_renew_monotonic = time.monotonic()
    report.check("租约守卫：被明确拒绝时，即使刚续租过也拒绝", not guard_allows())


# ---------------------------------------------------------------------------
# 信封加密
# ---------------------------------------------------------------------------


def check_crypto(report: Report) -> None:
    import base64
    import json

    from toolhive.adapters.crypto import DecryptionError, EnvelopeCipher, parse_kek_id
    from toolhive.config import SecretSettings

    k1 = base64.b64encode(os.urandom(32)).decode()
    k2 = base64.b64encode(os.urandom(32)).decode()
    secret = SecretSettings(keks=json.dumps({"k1": k1, "k2": k2}), active_kek_id="k2")
    cipher = EnvelopeCipher(secret)
    value = b'{"Authorization": "Bearer sk-upstream-secret"}'

    blob = cipher.encrypt(value)
    report.check("加密：往返一致", cipher.decrypt(blob) == value)
    report.check("加密：密文中不含明文", b"sk-upstream-secret" not in blob)
    report.check("加密：两次加密结果不同（独立随机 DEK）",
                 cipher.encrypt(value) != cipher.encrypt(value))
    blob_k1 = cipher.encrypt(value, kek_id="k1")
    report.check("加密：密文自带 kek_id", parse_kek_id(blob_k1) == "k1")
    report.check("加密：ACTIVE 切换后旧 KEK 的密文仍可解",
                 cipher.decrypt(blob_k1) == value)

    aad = b"credential:name"
    blob_aad = cipher.encrypt(value, aad=aad)
    report.check("加密：AAD 正确时可解", cipher.decrypt(blob_aad, aad=aad) == value)
    try:
        cipher.decrypt(blob_aad, aad=b"other")
        report.check("加密：AAD 不匹配必须失败", False)
    except DecryptionError:
        report.check("加密：AAD 不匹配必须失败", True)

    rewrapped = cipher.rewrap(blob_k1, kek_id="k2")
    report.check("轮换：rewrap 后 kek_id 变更且仍可解",
                 parse_kek_id(rewrapped) == "k2" and cipher.decrypt(rewrapped) == value)

    report.check("密钥不外泄：repr(SecretSettings) 不含 KEK", k2 not in repr(secret))
    report.check("密钥不外泄：repr(EnvelopeCipher) 不含 KEK", k2 not in repr(cipher))


# ---------------------------------------------------------------------------
# 配置校验
# ---------------------------------------------------------------------------

#: 配置的 11 个分区（``Settings.__init__`` 的关键字参数）。
_CONFIG_SECTIONS = (
    "runtime",
    "database",
    "redis",
    "upstream",
    "snowflake",
    "secret",
    "embedding",
    "retrieval",
    "rerank",
    "idempotency",
    "logging",
)

#: (场景说明, 分区, 要打坏的字段, 期望被报出来的 (分区, 字段) 集合)
#:
#: 为什么要有这一段：``validate()`` 原本是单个 214 行的函数，坐在它校验的那些配置类
#: 下方 400 行处——**加一个配置项却忘了补校验，不会被任何检查发现**。
#: 现已按分区拆成 10 个函数并紧挨各自的类；下面这些用例把"每个分区到底还查不查得住"钉住，
#: 防止将来拆分/合并时把某条规则弄丢。
_CONFIG_CASES: tuple[tuple[str, str, dict[str, object], set[tuple[str, str]]], ...] = (
    (
        "database 全坏",
        "database",
        {"url": "mysql://x", "pool_min": 0, "pool_max": 0, "command_timeout": 0},
        {("database", "url"), ("database", "pool_min"), ("database", "command_timeout")},
    ),
    (
        "redis 全坏",
        "redis",
        {
            "url": "http://x",
            "pool_max_connections": 0,
            "pool_wait_timeout_seconds": 0,
            "health_check_interval_seconds": -1,
        },
        {
            ("redis", "url"),
            ("redis", "pool_max_connections"),
            ("redis", "pool_wait_timeout_seconds"),
            ("redis", "health_check_interval_seconds"),
        },
    ),
    (
        "upstream 全坏",
        "upstream",
        {
            "connect_timeout_seconds": 0,
            "max_connections": 0,
            "max_keepalive_connections": 99,
            "user_agent": "",
        },
        {
            ("upstream", "connect_timeout_seconds"),
            ("upstream", "max_connections"),
            ("upstream", "max_keepalive_connections"),
            ("upstream", "user_agent"),
        },
    ),
    (
        "snowflake 越界",
        "snowflake",
        {"datacenter_id": 99, "worker_id": -1},
        {("snowflake", "datacenter_id"), ("snowflake", "worker_id")},
    ),
    (
        "secret KEK 非法",
        "secret",
        {"keks": '{"k1": "not-base64"}', "active_kek_id": "nope"},
        {("secret", "keks"), ("secret", "active_kek_id")},
    ),
    (
        "embedding 全坏（api_key 只告警）",
        "embedding",
        {"base_url": "ftp://x", "model": "", "dim": 0, "api_key": ""},
        {
            ("embedding", "base_url"),
            ("embedding", "model"),
            ("embedding", "dim"),
            ("embedding", "api_key"),
        },
    ),
    (
        "retrieval default_k > max_k",
        "retrieval",
        {"default_k": 50, "max_k": 10},
        {("retrieval", "default_k")},
    ),
    (
        "rerank 开启却留空",
        "rerank",
        {"enabled": True, "endpoint": "ftp://x", "model": "", "api_key": ""},
        {("rerank", "endpoint"), ("rerank", "model"), ("rerank", "api_key")},
    ),
    (
        "idempotency 全坏",
        "idempotency",
        {"ttl_seconds": 0, "max_result_bytes": 0},
        {("idempotency", "ttl_seconds"), ("idempotency", "max_result_bytes")},
    ),
    (
        "logging 桶为空",
        "logging",
        {"latency_buckets_ms": ""},
        {("logging", "latency_buckets_ms")},
    ),
)


def check_config(report: Report) -> None:
    from toolhive.config import Settings, load_settings, validate

    base = load_settings(BACKEND_ROOT / ".env")

    def variant(section: str, changes: dict[str, object]) -> Settings:
        # Settings 是普通类（非 pydantic），只能按 11 个关键字参数重建；
        # 分区本身 frozen=True，用 model_copy(update=...) 绕过校验塞进非法值。
        parts = {name: getattr(base, name) for name in _CONFIG_SECTIONS}
        parts[section] = parts[section].model_copy(update=changes)
        return Settings(**parts)

    report.check("配置：真实 .env 校验通过", not validate(base).problems)

    for label, section, changes, expected in _CONFIG_CASES:
        found = {(p.section, p.field) for p in validate(variant(section, changes)).problems}
        missing = expected - found
        report.check(
            f"配置：{label}"
            + (f"（漏报 {sorted(missing)}）" if missing else ""),
            not missing,
        )

    # 关闭精排时留空不应报错——这是 §6.2 的明确语义，别被"全字段必填"改坏。
    off = variant("rerank", {"enabled": False, "endpoint": "", "model": "", "api_key": ""})
    report.check("配置：精排关闭时留空不报错", not validate(off).problems)

    # 密钥不得出现在校验信息里（§10.1 第 2 条）。
    leak = variant("secret", {"keks": '{"k1": "c2hvcnQ="}', "active_kek_id": "k1"})
    texts = " ".join(p.message for p in validate(leak).problems)
    report.check("配置：校验信息不含 KEK 原文", "c2hvcnQ=" not in texts)


# ---------------------------------------------------------------------------
# 数据库事务与仓储（含 BUG-2 回归）
# ---------------------------------------------------------------------------


async def check_database(report: Report) -> None:
    from sqlalchemy import String, select, text
    from sqlalchemy.ext.asyncio import AsyncSession

    from toolhive.adapters.db.base import (
        AuditMixin,
        Base,
        RowVersionMixin,
        SnowflakePrimaryKeyMixin,
    )
    from toolhive.adapters.db.repository import OptimisticLockError, Repository
    from toolhive.adapters.db.session import (
        Database,
        configure,
        current_session,
        independent_transaction,
        request_session,
        transactional,
    )
    from toolhive.adapters.snowflake import SnowflakeGenerator
    from toolhive.config import load_settings

    table = "zz_selfcheck_row"

    class Row(Base, SnowflakePrimaryKeyMixin, RowVersionMixin, AuditMixin):
        __tablename__ = table
        name: Mapped[str] = mapped_column(String(64))

    class RowRepo(Repository[Row]):
        model = Row

    settings = load_settings(BACKEND_ROOT / ".env")
    db = Database.from_settings(settings.database)
    if not await db.ping():
        report.skip("PostgreSQL 不可达，跳过事务与仓储自检")
        await db.dispose()
        return
    configure(db)
    gen = SnowflakeGenerator(settings.snowflake.datacenter_id, settings.snowflake.worker_id)

    @transactional
    async def make(session: AsyncSession, name: str) -> int:
        row = Row(id=gen.next_id(), name=name)
        row.stamp_create(1, "selfcheck")
        session.add(row)
        await session.flush()
        return row.id

    @independent_transaction
    async def independent(session: AsyncSession, name: str) -> int:
        return await make(name)

    @transactional
    async def outer_with_independent(
        session: AsyncSession, name: str
    ) -> tuple[int, bool, bool]:
        req_before = request_session()
        independent_id = await independent(name + "-independent")
        return independent_id, req_before is request_session(), current_session() is req_before

    @transactional
    async def read_back(session: AsyncSession, name: str) -> bool:
        found = (
            await session.execute(select(Row).where(Row.name == name))
        ).scalars().first()
        return found is not None

    @transactional
    async def bump_touch(session: AsyncSession, row_id: int) -> tuple[int, bool]:
        row = await session.get(Row, row_id)
        assert row is not None
        row.name = "touched"
        row.touch(2, "editor")
        await session.flush()
        return row.row_version, row.update_time is not None

    try:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
        async with db.engine.begin() as conn:
            # 本进程只注册了 Row 一张表，所以 create_all 不带 tables 过滤也只建它。
            # 传 tables=[Row.__table__] 会撞上 __table__ 的静态类型是 FromClause。
            await conn.run_sync(Base.metadata.create_all)

        # --- 会话不自动提交 ---
        async with db.session() as s:
            s.add(Row(id=gen.next_id(), name="ghost"))
            await s.flush()
            await s.rollback()
        async with db.session() as s:
            from sqlalchemy import select

            ghosts = (await s.execute(select(Row).where(Row.name == "ghost"))).scalars().all()
        report.check("事务：会话不自动提交", not ghosts)

        # --- BUG-2 回归：请求级事务身份不被独立事务顶掉 ---
        independent_id, req_preserved, back_to_request = await outer_with_independent("p")
        report.check("事务：requires_new 期间请求级事务身份未被替换（BUG-2 回归）", req_preserved)
        report.check("事务：requires_new 返回后回到请求级事务", back_to_request)
        async with db.session() as s:
            from sqlalchemy import select

            kept = (await s.execute(select(Row).where(Row.id == independent_id))).scalars().first()
        report.check("事务：requires_new 的写入独立提交", kept is not None)

        # --- 第二处修复：Database.session() 登记为请求级事务 ---
        # 若没登记，@transactional 服务函数会另开连接，看不到未提交的改动。
        async with db.session() as s:
            s.add(Row(id=gen.next_id(), name="uncommitted-in-route"))
            await s.flush()
            visible = await read_back("uncommitted-in-route")
            await s.rollback()
        report.check("事务：路由会话被登记为请求级事务（服务函数能看见未提交数据）", visible)

        # --- 乐观锁 ---
        row_id = await make("opt")
        async with db.session() as s:
            repo = RowRepo(s)
            await repo.update_with_row_version(
                row_id, expected_row_version=1, values={"name": "v2"}
            )
            await s.commit()
        async with db.session() as s:
            repo = RowRepo(s)
            try:
                await repo.update_with_row_version(
                    row_id, expected_row_version=1, values={"name": "v3"}
                )
                report.check("乐观锁：过期版本必须冲突", False)
            except OptimisticLockError:
                report.check("乐观锁：过期版本必须冲突", True)
            await s.rollback()

        # --- BUG-3 / BUG-4 回归：touch() ---
        new_version, has_time = await bump_touch(row_id)
        report.check("审计：touch() 写入的是 datetime（BUG-3 回归）", has_time)
        report.check("审计：touch() 推进 row_version（BUG-4 回归）", new_version == 3)

        # --- 行锁 ---
        async with db.session() as holder:
            await RowRepo(holder).get_for_update(row_id)

            async def try_lock() -> None:
                async with db.session() as other:
                    await RowRepo(other).get_for_update(row_id)
                    await other.rollback()

            try:
                await asyncio.wait_for(try_lock(), timeout=0.6)
                report.check("仓储：SELECT FOR UPDATE 阻塞第二个事务", False)
            except TimeoutError:
                report.check("仓储：SELECT FOR UPDATE 阻塞第二个事务", True)
            await holder.rollback()
    finally:
        async with db.engine.begin() as conn:
            await conn.execute(text(f'DROP TABLE IF EXISTS "{table}"'))
        await db.dispose()


# ---------------------------------------------------------------------------


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="selfcheck", description="模块 B 运行时自检")
    parser.parse_args(argv)

    print("ToolHive 运行时自检（模块 B）")
    print("=" * 72)

    report = Report()
    for label in (
        "缓存原语（Redis）",
        "雪花 ID",
        "信封加密",
        "配置校验",
        "数据库事务与仓储（PostgreSQL）",
    ):
        print(f"\n--- {label} ---")
        before = len(report.lines)
        if label == "缓存原语（Redis）":
            await check_cache(report)
        elif label == "雪花 ID":
            await check_snowflake(report)
        elif label == "信封加密":
            check_crypto(report)
        elif label == "配置校验":
            check_config(report)
        else:
            await check_database(report)
        for status, name in report.lines[before:]:
            print(f"  [{status}] {name}")

    print("\n" + "=" * 72)
    print(f"通过 {report.passed} / 失败 {report.failed}"
          f" / 跳过 {sum(1 for s, _ in report.lines if s == SKIP)}")
    if report.failed:
        print("\n失败的检查项：")
        for status, name in report.lines:
            if status == FAIL:
                print(f"  - {name}")
    print("\n✅ 全部通过。" if not report.failed else "\n❌ 有失败项。")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
