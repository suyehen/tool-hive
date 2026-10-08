"""D 真实基础设施验证；只写随机 PostgreSQL schema 和 Redis namespace。"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import sys
import traceback
from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from domain_selfcheck import migrate_and_compare
from toolhive.adapters.cache.client import create_client
from toolhive.config import load_management_settings
from toolhive.core.domain.catalog import CatalogService
from toolhive.core.domain.contracts import Actor, BindingDefinition, ToolDefinition
from toolhive.core.domain.grants import GrantRepository
from toolhive.core.domain.identity import IdentityService
from toolhive.core.domain.providers import ProviderService
from toolhive.core.policy.authorization import AuthorizationService
from toolhive.core.policy.circuit import CircuitPermit, CircuitPolicy, CircuitSettings
from toolhive.core.policy.constraints import enforce_constraints
from toolhive.core.policy.contracts import Authorization, RequestContext
from toolhive.core.policy.errors import PolicyError
from toolhive.core.policy.idempotency import CallRecord, IdempotencyPolicy, request_fingerprint
from toolhive.core.policy.resources import Reservation, ResourcePolicy
from toolhive.core.policy.store import PolicyStore
from toolhive.core.policy.visibility import consume_invalidations


async def rejected(code: str, operation: Callable[[], Awaitable[object]]) -> None:
    try:
        await operation()
    except PolicyError as exc:
        assert exc.code == code, exc.code
    else:
        raise AssertionError(f"expected {code}")


async def exercise(factory: async_sessionmaker[AsyncSession], store: PolicyStore) -> None:
    next_id = itertools.count(2**60).__next__
    actor = Actor(1, "policy-selfcheck")
    definition = ToolDefinition(name="Read", domain="demo", input_schema={}, side_effect="read")
    async with factory() as session, session.begin():
        principal = await IdentityService(session, next_id).create_principal(
            "test", "service", actor
        )
        provider = await ProviderService(session, next_id).register(
            "test", "test", "http", "https://example.invalid", actor
        )
        catalog = CatalogService(session, next_id)
        tool = await catalog.create_tool("demo.crm.query", "test#query", "Read", provider.id, actor)
        binding = BindingDefinition(provider.id, "GET", "/read", {})
        version = await catalog.create_draft(tool.id, "1", definition, binding, actor)
        await catalog.submit(version.id, actor)
        await catalog.approve(version.id, actor)
        grant = await GrantRepository(session, next_id).create(
            principal.id, "domain", "demo", actor, quota={"qps": 1, "daily": 1, "concurrency": 3}
        )
        identifiers = principal.id, tool.id, provider.id, version.id, grant.id
    pid, tid, provider_id, vid, gid = identifiers
    async with factory() as session:
        service = AuthorizationService(session, store, visible_ttl=1)
        auth = await service.resolve(pid, "demo.crm.query")
        assert auth.version.id == vid
        assert await service.visible_ids(pid) == {tid}
        await rejected("TH_TOOL_NOT_FOUND", lambda: service.resolve(pid, "missing"))
        await rejected("TH_TOOL_NOT_FOUND", lambda: service.resolve(pid + 1, "demo.crm.query"))
        await rejected("TH_TOOL_NOT_FOUND", lambda: service.resolve(pid, "demo.crm.query", "beta"))
        enforce_constraints(auth.grants, RequestContext(datetime.now(UTC)))
    print("[PASS] fresh authorization and indistinguishable unavailable tools")
    idem, fp, completed = await exercise_redis(store, auth)
    async with factory() as session:
        service = AuthorizationService(session, store)
        with patch.object(
            store.redis, "get", new=AsyncMock(side_effect=RedisConnectionError("secret"))
        ):
            assert await service.visible_ids(pid) == {tid}
        with patch.object(
            session,
            "scalar",
            new=AsyncMock(side_effect=OperationalError("", {}, Exception("secret"))),
        ):
            await rejected(
                "TH_DEPENDENCY_UNAVAILABLE", lambda: service.resolve(pid, "demo.crm.query")
            )
    print(
        "[PASS] dependency faults: idempotency/database closed, "
        "quota/circuit open, visibility DB bypass"
    )
    # 切换 stable 后重放仍引用旧版本；禁用 grant 后重放授权立即失败。
    async with factory() as session, session.begin():
        catalog = CatalogService(session, next_id)
        new = await catalog.create_draft(tid, "2", definition, binding, actor)
        await catalog.submit(new.id, actor)
        await catalog.approve(new.id, actor)
        await catalog.publish_channel(tid, new.id, "stable", actor)
    async with factory() as session:
        service = AuthorizationService(session, store)
        assert (await service.resolve(pid, "demo.crm.query")).version.id != vid
        pinned = await service.resolve(pid, "demo.crm.query", pinned_version_id=vid)
        replay = idem.replay(completed, fp, pinned)
        assert replay is not None and replay["trace_id"] == "original"
        await service.invalidate([pid])
        assert await AuthorizationService(session, store, visible_ttl=1).visible_ids(pid) == {tid}
    async with factory() as session, session.begin():
        await GrantRepository(session, next_id).disable(gid, actor)
    await asyncio.sleep(1.1)
    async with factory() as session:
        assert not await AuthorizationService(session, store).visible_ids(pid)
    async with factory() as session, session.begin():
        service = AuthorizationService(session, store)
        await rejected(
            "TH_TOOL_NOT_FOUND",
            lambda: service.resolve(pid, "demo.crm.query", pinned_version_id=vid),
        )
        assert await consume_invalidations(service) > 0
        assert await service.visible_ids(pid) == set()
    # 锁定旧 session 身份映射，独立事务撤销 Provider 后也不能执行。
    async with factory() as session, session.begin():
        await GrantRepository(session, next_id).create(pid, "tool", str(tid), actor)
    async with factory() as stale:
        service = AuthorizationService(stale, store)
        await service.resolve(pid, "demo.crm.query")
        async with factory() as session, session.begin():
            provider = await ProviderService(session, next_id).require(provider_id)
            await ProviderService(session, next_id).set_status(
                provider_id, provider.row_version, "disabled", actor
            )
        await rejected("TH_TOOL_NOT_FOUND", lambda: service.resolve(pid, "demo.crm.query"))
    print(
        "[PASS] pinned replay across stable switch, revoked Grant denial, "
        "active cache invalidation, fresh Provider disable"
    )


async def exercise_redis(
    store: PolicyStore, auth: Authorization
) -> tuple[IdempotencyPolicy, str, CallRecord]:
    vid = auth.version.id
    pid, tid, provider_id, gid = (
        auth.principal_id,
        auth.tool.id,
        auth.provider.id,
        auth.grants[0].id,
    )
    resources = ResourcePolicy(store)
    grants = auth.grants
    now = datetime.now(UTC)
    await resources.check_qps(grants, timestamp_ms=int(now.timestamp() * 1000))
    await rejected(
        "TH_RATE_LIMITED",
        lambda: resources.check_qps(grants, timestamp_ms=int(now.timestamp() * 1000)),
    )
    # 后一个 Grant 已满，前一个成功预留必须退还。
    first = replace(grants[0], id=gid + 100, daily=1)
    held = await resources.reserve(grants, daily=True, lease_ms=5000, now=now)
    await rejected(
        "TH_QUOTA_EXCEEDED",
        lambda: resources.reserve((first, *grants), daily=True, lease_ms=5000, now=now),
    )
    recovered = await resources.reserve((first,), daily=True, lease_ms=5000, now=now)
    await resources.release(recovered)
    await resources.commit_daily(held)
    await resources.commit_daily(held)  # ACK 重试不会重复扣减。
    await rejected(
        "TH_QUOTA_EXCEEDED", lambda: resources.reserve(grants, daily=True, lease_ms=5000, now=now)
    )
    await resources.release(held)
    await resources.release(held)
    available = await resources.reserve(grants, daily=True, lease_ms=5000, now=now)
    await resources.release(available)
    print(
        "[PASS] QPS and daily: every matching Grant, partial compensation, idempotent commit/refund"
    )

    async def reserve_concurrent() -> Reservation | None:
        try:
            return await resources.reserve(grants, daily=False, lease_ms=5000, now=now)
        except PolicyError as exc:
            assert exc.code == "TH_CONCURRENCY_LIMITED"
            return None

    acquired = [r for r in await asyncio.gather(*(reserve_concurrent() for _ in range(100))) if r]
    assert len(acquired) == 3, len(acquired)
    await asyncio.gather(*(resources.release(r) for r in acquired))
    short = await resources.reserve(grants, daily=False, lease_ms=50, now=now)
    await asyncio.sleep(0.08)
    await rejected("TH_CONCURRENCY_LIMITED", lambda: resources.renew(short))
    # Lua 已生效、客户端取消：当前键也必须释放。
    original = store.run

    async def cancelled(
        name: str, keys: Sequence[str], args: Sequence[str | int | float | bytes]
    ) -> list[Any]:
        result = await original(name, keys, args)
        if name == "policy_reservation" and args[0] == "acquire":
            raise asyncio.CancelledError
        return result

    with patch.object(store, "run", side_effect=cancelled), suppress(asyncio.CancelledError):
        await resources.reserve(grants, daily=False, lease_ms=5000, now=now)
    assert await store.redis.zcard(store.key(f"concurrency:{gid}:pending")) == 0
    lost_ack = True

    async def ack_lost(
        name: str,
        keys: Sequence[str],
        args: Sequence[str | int | float | bytes],
    ) -> list[Any]:
        nonlocal lost_ack
        result = await original(name, keys, args)
        if lost_ack and name == "policy_reservation" and args[0] == "acquire":
            lost_ack = False
            raise RedisConnectionError("ack lost")
        return result

    with patch.object(store, "run", side_effect=ack_lost):
        receipt = await resources.reserve(grants, daily=False, lease_ms=5000, now=now)
        assert not receipt.keys
    assert await store.redis.zcard(store.key(f"concurrency:{gid}:pending")) == 0
    print(
        "[PASS] concurrency: 100 requests / 3 slots, expired owner cannot "
        "renew, cancellation compensation"
    )
    idem = IdempotencyPolicy(store, max_result_bytes=20)
    fp = request_fingerprint(tid, None, {"number": 2**60})

    async def claim() -> CallRecord | None:
        try:
            return await idem.claim(pid, "same", fp, auth, binding_digest="digest", lease_ms=5000)
        except PolicyError as exc:
            assert exc.code == "TH_IDEMPOTENCY_IN_PROGRESS"
            return None

    winners = [r for r in await asyncio.gather(*(claim() for _ in range(100))) if r]
    assert len(winners) == 1
    record = winners[0]
    assert record.tool_id == tid and record.version_id == vid  # > Lua double precision
    await rejected(
        "TH_IDEMPOTENCY_KEY_REUSED",
        lambda: idem.claim(pid, "same", "other-fp", auth, binding_digest="digest", lease_ms=5000),
    )
    await idem.transition(record, "dispatch")
    await idem.complete(record, trace_id="original", result="large result more than twenty bytes")
    completed = await idem.lookup(pid, "same")
    assert completed is not None
    raced = await idem.claim(pid, "same", fp, auth, binding_digest="digest", lease_ms=5000)
    assert raced.state == "completed"
    await rejected("TH_IDEMPOTENCY_IN_PROGRESS", lambda: idem.transition(raced, "dispatch"))
    assert idem.replay(completed, fp, auth) == {
        "trace_id": "original",
        "result": None,
        "result_retained": False,
        "error_code": None,
    }
    assert await idem.lookup(pid + 1, "same") is None
    lease = await idem.claim(pid, "takeover", fp, auth, binding_digest="digest", lease_ms=50)
    await asyncio.sleep(0.08)
    successor = await idem.claim(pid, "takeover", fp, auth, binding_digest="digest", lease_ms=5000)
    await rejected("TH_IDEMPOTENCY_IN_PROGRESS", lambda: idem.transition(lease, "dispatch"))
    await idem.transition(successor, "abandon")
    uncertain = await idem.claim(pid, "unknown", fp, auth, binding_digest="digest", lease_ms=50)
    await idem.transition(uncertain, "dispatch")
    await asyncio.sleep(0.08)
    unknown = await idem.lookup(pid, "unknown")
    assert unknown is not None and unknown.state == "unknown"
    assert await store.redis.ttl(unknown.key) == -1
    await rejected(
        "TH_EXECUTION_OUTCOME_UNKNOWN",
        lambda: idem.claim(pid, "unknown", fp, auth, binding_digest="digest", lease_ms=5000),
    )
    await idem.complete(uncertain, trace_id="late", result=2**60)
    late = await idem.lookup(pid, "unknown")
    assert late is not None
    replay = idem.replay(late, fp, auth)
    assert replay is not None and replay["result"] == 2**60
    print(
        "[PASS] idempotency: 100 claims / 1 owner, large IDs, takeover CAS, "
        "unknown tombstone, late result, result cap"
    )
    circuit = CircuitPolicy(
        store, CircuitSettings(threshold=2, window_ms=1000, open_ms=200, probe_lease_ms=5000)
    )
    old = await circuit.allow(provider_id)
    second = await circuit.allow(provider_id)
    await circuit.report(old, healthy=False)
    await circuit.report(second, healthy=False)
    await circuit.report(old, healthy=True)
    await rejected("TH_CIRCUIT_OPEN", lambda: circuit.allow(provider_id))
    await asyncio.sleep(0.25)

    async def probe() -> CircuitPermit | None:
        try:
            return await circuit.allow(provider_id)
        except PolicyError as exc:
            assert exc.code == "TH_CIRCUIT_OPEN"
            return None

    probes = [r for r in await asyncio.gather(*(probe() for _ in range(100))) if r]
    assert len(probes) == 1
    await circuit.report(probes[0], healthy=True)
    assert not (await circuit.allow(provider_id)).owner
    print(
        "[PASS] Provider circuit: threshold, stale result fencing, 100 "
        "contenders / 1 half-open probe"
    )
    # Redis 失效：幂等拒绝，防滥用放行，可见集合走 DB。
    with patch.object(store, "run", new=AsyncMock(side_effect=RedisConnectionError("secret"))):
        await rejected("TH_DEPENDENCY_UNAVAILABLE", lambda: idem.lookup(pid, "same"))
        assert (await circuit.allow(provider_id)).degraded
        degraded = await resources.reserve(grants, daily=True, lease_ms=1000, now=now)
        assert not degraded.keys
        degraded = await resources.reserve(grants, daily=False, lease_ms=1000, now=now)
        assert not degraded.keys
    with patch.object(
        store.scripts, "run", new=AsyncMock(side_effect=RedisConnectionError("secret"))
    ):
        await resources.check_qps(grants, timestamp_ms=int(now.timestamp() * 1000))
    return idem, fp, completed


async def run(env_file: Path) -> None:
    settings = load_management_settings(env_file)
    url = settings.database.url.replace("postgresql://", "postgresql+asyncpg://", 1).replace(
        "postgres://", "postgresql+asyncpg://", 1
    )
    schema = "th_d_selfcheck_" + uuid4().hex
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "timeout": 5,
            "command_timeout": 15,
            "server_settings": {"search_path": f"{schema},public"},
        },
    )
    redis = create_client(settings.redis)
    store = PolicyStore(redis, namespace="toolhive:policy-selfcheck:" + uuid4().hex)
    created = False
    connected = False
    try:
        await redis.ping()
        connected = True
        async with engine.begin() as connection:
            extensions = set(
                (await connection.scalars(text("SELECT extname FROM pg_extension"))).all()
            )
            assert {"vector", "pg_trgm"} <= extensions
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            await connection.run_sync(migrate_and_compare, schema)
        await exercise(async_sessionmaker(engine, expire_on_commit=False, autoflush=False), store)
    finally:
        try:
            if connected:
                async for key in redis.scan_iter(match=store.namespace + ":*"):
                    await redis.delete(key)
        finally:
            await redis.aclose()
            try:
                if created:
                    async with engine.begin() as connection:
                        await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.env_file.resolve()))
    except Exception as exc:
        print(f"[FAIL] policy integration: {type(exc).__name__}")
        if isinstance(exc, AssertionError):
            print(str(exc))
        for frame in traceback.extract_tb(exc.__traceback__):
            if Path(frame.filename).name == Path(__file__).name:
                print(f"  {frame.name}:{frame.lineno}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
