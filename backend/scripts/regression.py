"""审查缺陷的本地回归：不读取 .env，不连接外部服务。"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast
from unittest.mock import patch

import httpx
from pydantic_settings import PydanticBaseSettingsSource
from redis.asyncio import Redis
from sqlalchemy import String, Table, create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, Session, mapped_column

from toolhive.adapters.cache.client import ScriptRegistry
from toolhive.adapters.crypto import DecryptionError, EnvelopeCipher
from toolhive.adapters.db.base import AuditMixin, Base, RowVersionMixin, SnowflakePrimaryKeyMixin
from toolhive.adapters.db.repository import (
    OptimisticLockError,
    Repository,
    RepositoryError,
    UnflushedChangesError,
)
from toolhive.adapters.http import Deadline, DeadlineExceededError, UpstreamClient
from toolhive.adapters.snowflake import (
    LeaseNotAcquiredError,
    SnowflakeError,
    SnowflakeGenerator,
    WorkerLease,
)
from toolhive.config import (
    ConfigError,
    SecretSettings,
    UpstreamSettings,
    load_database_settings,
    load_management_settings,
    load_settings,
)
from toolhive.observability.logging import (
    JsonFormatter,
    LatencyBuckets,
    LatencyHistogram,
    log_latency,
)

for stream in (sys.stdout, sys.stderr):
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8", errors="replace")


def rejects(error: type[Exception], fn: Callable[[], object]) -> None:
    try:
        fn()
    except error:
        return
    raise AssertionError(f"expected {error.__name__}")


def check_snowflake() -> None:
    clock = [1800000000000]
    gen = SnowflakeGenerator(1, 1, time_fn=lambda: clock[0])
    issued = gen.next_ids(4096)
    # 失败不能重置序列；第二次尝试也必须拒绝，而不是重复发号。
    rejects(SnowflakeError, gen.next_id)
    rejects(SnowflakeError, gen.next_id)
    assert gen.issued_count == 4096
    clock[0] += 1
    assert gen.next_id() > max(issued)
    calls = [0]

    def guard() -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise LeaseNotAcquiredError("expired during wait")

    guarded = SnowflakeGenerator(1, 1, time_fn=lambda: clock[0], guard=guard)
    rejects(LeaseNotAcquiredError, guarded.next_id)
    assert guarded.issued_count == 0


async def check_lease() -> None:
    mono = [10.0]

    class Client:
        async def set(self, *args: object, **kwargs: object) -> bool:
            mono[0] += 3.0  # 服务端执行后响应迟到，超过 TTL 的 2/3
            return True

    class Registry:
        async def run(self, client: object, name: str, **kwargs: object) -> list[int]:
            if name == "worker_lease_renew":
                mono[0] += 3.0
            return [1]

    with patch("toolhive.adapters.snowflake.time.monotonic", side_effect=lambda: mono[0]):
        lease = WorkerLease(cast("Redis", Client()), datacenter_id=1, worker_id=1,
                            ttl_ms=3000, registry=cast("ScriptRegistry", Registry()))
        await lease.acquire()
        rejects(LeaseNotAcquiredError, lease.ensure_held)
        mono[0] = 14.0
        await lease.renew()
        rejects(LeaseNotAcquiredError, lease.ensure_held)
        await lease.release()
        rejects(LeaseNotAcquiredError, lease.ensure_held)
        assert not await lease.renew()


async def check_deadline() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(.05)
        return httpx.Response(200, content=b"ok")

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(100):
                await asyncio.sleep(.002)
                yield b"x"

    async def streaming(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Chunks())

    cfg = UpstreamSettings(connect_timeout_seconds=3, read_timeout_seconds=10,
                           max_connections=100, max_keepalive_connections=20,
                           user_agent="regression")
    for handler in (slow, streaming):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                    verify=False, trust_env=False) as raw:
            client = UpstreamClient(raw, cfg)
            try:
                await client.request("GET", "https://example.invalid",
                                     deadline=Deadline.in_seconds(.01))
            except DeadlineExceededError:
                pass
            else:
                raise AssertionError("overall deadline was not enforced")
    async with httpx.AsyncClient(transport=httpx.MockTransport(slow),
                                verify=False, trust_env=False) as raw:
        client = UpstreamClient(raw, cfg)
        assert (await client.request("GET", "https://example.invalid")).status_code == 200
        task = asyncio.create_task(client.request("GET", "https://example.invalid",
                                                  deadline=Deadline.in_seconds(1)))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("external cancellation was swallowed")


def check_crypto() -> None:
    secret = SecretSettings(keks=json.dumps({
        "old": base64.b64encode(b"a" * 32).decode(),
        "new": base64.b64encode(b"b" * 32).decode(),
    }), active_kek_id="new")
    cipher = EnvelopeCipher(secret)
    blob = cipher.encrypt(b"dummy", kek_id="old", aad=b"credential:42")
    rotated = cipher.rewrap(blob, aad=b"credential:42")
    assert cipher.decrypt(rotated, aad=b"credential:42") == b"dummy"
    # 正文 nonce/ciphertext 尾部不改变，轮换只重包装 DEK。
    assert blob[5 + len("old") + 12 + 48:] == rotated[5 + len("new") + 12 + 48:]
    rejects(DecryptionError, lambda: cipher.rewrap(blob, aad=b"wrong"))
    rejects(DecryptionError, lambda: cipher.rewrap(rotated, aad=b"wrong"))
    assert cipher.rewrap(rotated, aad=b"credential:42") == rotated


def check_config() -> None:
    base = {
        "TOOLHIVE_DATABASE_URL": "postgresql://dummy:dummy@localhost/db",
        "TOOLHIVE_REDIS_URL": "redis://localhost/1",
        "TOOLHIVE_KEKS": json.dumps({"k": base64.b64encode(b"a" * 32).decode()}),
        "TOOLHIVE_ACTIVE_KEK_ID": "k",
        "TOOLHIVE_EMBEDDING_BASE_URL": "https://example.invalid",
        "TOOLHIVE_EMBEDDING_MODEL": "dummy",
        "TOOLHIVE_EMBEDDING_API_KEY": "dummy",
    }
    before = dict(os.environ)
    # 不只是退出后还原：构造分区期间进程环境也必须保持不变。
    from toolhive.config import _Section
    original = _Section.settings_customise_sources

    def observe(*args: Any, **kwargs: Any) -> tuple[PydanticBaseSettingsSource, ...]:
        assert dict(os.environ) == before
        return original(*args, **kwargs)

    with patch.object(_Section, "settings_customise_sources", side_effect=observe):
        assert load_settings(environ=base).snowflake.worker_id == 1
    assert dict(os.environ) == before
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(lambda n: load_settings(environ={
            **base, "TOOLHIVE_SNOWFLAKE_WORKER_ID": str(n)
        }).snowflake.worker_id, range(8)))
    assert values == list(range(8))
    db_only = {"TOOLHIVE_DATABASE_URL": base["TOOLHIVE_DATABASE_URL"]}
    assert load_database_settings(environ=db_only).url == base["TOOLHIVE_DATABASE_URL"]
    mgmt = load_management_settings(environ={**db_only, "TOOLHIVE_REDIS_URL": "redis://localhost/1"})
    assert not hasattr(mgmt, "secret")
    rejects(ConfigError, lambda: load_settings(environ=db_only))


class Row(Base, SnowflakePrimaryKeyMixin, RowVersionMixin, AuditMixin):
    __tablename__ = "regression_row"
    status: Mapped[str] = mapped_column(String)


class Rows(Repository[Row]):
    model = Row


async def check_repository() -> None:
    # SQLite 只验证身份映射刷新和默认值；不声称验证 PostgreSQL 行锁。
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[cast(Table, Row.__table__)])
    try:
        with Session(engine) as writer:
            writer.add(Row(id=1, status="pending_review"))
            writer.commit()
        with Session(engine, expire_on_commit=False, autoflush=False) as session:
            stale = session.get(Row, 1)
            assert stale is not None and stale.row_version == 0
            session.commit()
            with Session(engine) as writer:
                row = writer.get(Row, 1)
                assert row is not None
                row.status = "published"
                writer.commit()

            class Adapter:
                @property
                def dirty(self) -> Iterable[object]:
                    return session.dirty

                async def execute(self, statement: Any) -> Any:
                    return session.execute(statement)

            repo = Rows(cast("AsyncSession", Adapter()))
            # 普通读也应刷新其他事务修改后的状态。
            refreshed = await repo.get_by_id(1)
            assert refreshed is stale and refreshed.status == "published"
            session.commit()
            with Session(engine) as writer:
                row = writer.get(Row, 1)
                assert row is not None
                row.status = "changed_again"
                writer.commit()
            rows = await repo.list_by_ids([1])
            assert rows == [stale] and stale.status == "changed_again"
            refreshed = await repo.get_for_update(1)
            assert refreshed is stale and refreshed.status == "changed_again"
            stale.status = "dirty"
            operations = [repo.get_by_id(1), repo.get_for_update(1), repo.list_by_ids([1]),
                          repo.update_with_row_version(1, expected_row_version=0, values={})]
            for operation in operations:
                try:
                    await operation
                except UnflushedChangesError as exc:
                    assert isinstance(exc, RepositoryError) and not isinstance(exc, ValueError)
                else:
                    raise AssertionError("unflushed changes were overwritten")
            session.rollback()
            refreshed = await repo.get_by_id(1)
            assert refreshed is stale
            new_version = await repo.update_with_row_version(
                1, expected_row_version=0, values={"status": "conditional"}
            )
            # 在任何 reread 前检查：ORM DML 自身应同步字段和版本。
            assert new_version == stale.row_version == 1 and stale.status == "conditional"
            assert await repo.get_by_id(1) is stale
            try:
                await repo.update_with_row_version(1, expected_row_version=0,
                                                   values={"status": "conflict"})
            except OptimisticLockError:
                assert stale.row_version == 1 and stale.status == "conditional"
            else:
                raise AssertionError("optimistic conflict was swallowed")
            stale.status = "touched"
            stale.touch(1, "regression")
            assert stale.row_version == 2
            session.flush()
            session.commit()
        with Session(engine) as reader:
            row = reader.get(Row, 1)
            assert row is not None and row.row_version == 2 and row.status == "touched"
    finally:
        engine.dispose()


def check_histogram() -> None:
    histogram = LatencyHistogram(LatencyBuckets([10, 25, 50]))
    for value in (5, 20, 40, 100):
        histogram.observe(value)
    snapshot = histogram.snapshot()
    assert snapshot["buckets"] == {"le_10": 1, "le_25": 2, "le_50": 3, "le_+Inf": 4}
    assert snapshot["buckets"]["le_+Inf"] == snapshot["count"] == 4
    histogram.reset()
    assert histogram.snapshot()["buckets"]["le_+Inf"] == 0
    assert histogram.observe(30) == "range_25_50_ms"
    rejects(ValueError, lambda: histogram.observe(float("nan")))
    output = io.StringIO()
    logger = logging.Logger("regression")
    handler = logging.StreamHandler(output)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    log_latency(logger, operation="probe", latency_ms=30, buckets=LatencyBuckets([10, 25, 50]))
    event = json.loads(output.getvalue())
    assert event["latency_interval"] == "range_25_50_ms" and "latency_bucket" not in event


def check_preflight() -> None:
    from preflight import is_single_active_index
    good = {"indisunique": True, "indisvalid": True,
            "columns": ["status"], "predicate": "((status)::text = 'active'::text)"}
    assert is_single_active_index(good)
    assert not is_single_active_index(None)
    assert not is_single_active_index({**good, "predicate": None})
    assert not is_single_active_index({**good, "columns": ["index_version"]})
    assert not is_single_active_index({**good, "indisvalid": False})


def check_integration_gate() -> None:
    from selfcheck import Report, exit_code
    from verify import FAIL, PASS, SKIP, run_integration

    report = Report()
    report.skip("Redis unavailable")
    assert exit_code(report, strict=True) == 1
    assert exit_code(report, strict=False) == 0
    assert run_integration(None).status == SKIP
    assert run_integration(None, required=True).status == FAIL
    with TemporaryDirectory() as directory:
        env_file = Path(directory) / ".env.test"
        env_file.write_text("# dummy config; subprocess is mocked\n", encoding="utf-8")
        for returncode, expected in ((0, PASS), (1, FAIL)):
            with patch("verify._run_tool", return_value=subprocess.CompletedProcess(
                [], returncode, stdout="probe", stderr=""
            )) as runner:
                assert run_integration(env_file).status == expected
                command = runner.call_args.args[0]
                assert "--env-file" in command
                assert "--strict" in runner.call_args_list[0].args[0]
                assert str(env_file.resolve()) in command


async def main() -> None:
    checks: list[Callable[[], Awaitable[None] | None]] = [
              check_snowflake, check_lease, check_deadline, check_crypto,
              check_config, check_repository, check_histogram, check_preflight,
              check_integration_gate]
    for check in checks:
        result = check()
        if result is not None:
            await result
        print(f"[PASS] {check.__name__}")
    print(f"{len(checks)}/{len(checks)} 回归组通过")


if __name__ == "__main__":
    # 允许从任意工作目录调用脚本。
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    asyncio.run(main())
