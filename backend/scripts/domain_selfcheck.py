"""C 的真实 PostgreSQL 验证：显式配置，在本次独立 schema 中迁移、检查并清理。

不修改已有业务表，不创建或删除共享扩展；缺少扩展或连接失败均非零退出。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import itertools
import json
import sys
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from domain_regression import initial_migration
from toolhive.adapters.crypto import EnvelopeCipher
from toolhive.adapters.db.base import Base
from toolhive.adapters.db.repository import OptimisticLockError
from toolhive.config import SecretSettings, load_database_settings
from toolhive.core.domain.catalog import CatalogService
from toolhive.core.domain.contracts import Actor, BindingDefinition, ToolDefinition
from toolhive.core.domain.credentials import CredentialRepository
from toolhive.core.domain.errors import (
    ImmutableDefinitionError,
    InvalidApiKeyError,
    InvalidDefinitionError,
    InvalidTransitionError,
)
from toolhive.core.domain.grants import GrantRepository
from toolhive.core.domain.identity import IdentityService
from toolhive.core.domain.models import (
    ApiKey,
    ExecutionBinding,
    OutboxEvent,
    ReviewRecord,
    ToolChannel,
    ToolVersion,
)
from toolhive.core.domain.providers import ProviderService


async def rejected(error: type[Exception], operation: Callable[[], Awaitable[object]]) -> None:
    try:
        await operation()
    except error:
        return
    raise AssertionError(f"expected {error.__name__}")


def migrate_and_compare(connection: Connection, schema: str) -> None:
    migration = initial_migration()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        # 扩展预先存在；测试迁移仅在隔离 schema 执行建表/索引。
        for statement in migration._SQL.split(";"):
            if statement.strip() and "CREATE EXTENSION" not in statement:
                Operations(context).execute(statement)
    connection.dialect.default_schema_name = schema
    inspected = inspect(connection)
    actual_tables = set(inspected.get_table_names(schema=schema))
    expected_tables = set(Base.metadata.tables)
    assert actual_tables == expected_tables, (
        f"table differences: missing={expected_tables - actual_tables}, "
        f"extra={actual_tables - expected_tables}"
    )
    differences = compare_metadata(
        MigrationContext.configure(
            connection, opts={"compare_type": True, "compare_server_default": True}
        ),
        Base.metadata,
    )
    assert not differences, f"ORM/migration differences: {differences!r}"
    for table in Base.metadata.tables.values():
        actual = {item["name"] for item in inspected.get_indexes(table.name)}
        assert actual == {index.name for index in table.indexes}, table.name
    print("[PASS] migration / ORM: 16 tables, columns, defaults, indexes, foreign keys")


async def exercise(factory: async_sessionmaker[AsyncSession]) -> None:
    ids = itertools.count(1)

    def next_id() -> int:
        return next(ids)

    actor = Actor(900, "domain-selfcheck")
    definition = ToolDefinition(
        name="Lookup",
        input_schema={"type": "object"},
        domain="demo",
        system="crm",
        tags=("entity:customer",),
        side_effect="read",
        retry_safe=True,
    )
    async with factory() as session, session.begin():
        identity = IdentityService(session, next_id)
        principal = await identity.create_principal("selfcheck", "service", actor)
        issued = await identity.issue_key(principal.id, actor)
        expiring = await identity.issue_key(
            principal.id, actor, datetime.now(UTC) + timedelta(seconds=1)
        )
        expired_id = expiring.id
        provider = await ProviderService(session, next_id).register(
            "selfcheck", "Selfcheck", "http", "https://example.invalid", actor
        )
        catalog = CatalogService(session, next_id)
        tool = await catalog.create_tool(
            "demo.crm.customer.query", "openapi:demo#query", "Lookup", provider.id, actor
        )
        binding = BindingDefinition(provider.id, "POST", "/search", {})
        version = await catalog.create_draft(tool.id, "1", definition, binding, actor)
        await catalog.submit(version.id, actor)
        await catalog.approve(version.id, actor)
        stable = await session.scalar(select(ToolChannel).where(ToolChannel.tool_id == tool.id))
        assert stable is not None and stable.version_id == version.id
        assert tool.executable and tool.side_effect == "read"
        assert await session.scalar(select(func.count()).select_from(OutboxEvent)) == 2
        assert await session.scalar(select(func.count()).select_from(ReviewRecord)) == 2
        await rejected(InvalidTransitionError, lambda: catalog.approve(version.id, actor))
        other = await catalog.create_tool(
            "demo.crm.customer.other", "openapi:demo#other", "Other", provider.id, actor
        )
        await rejected(
            InvalidDefinitionError,
            lambda: catalog.publish_channel(other.id, version.id, "stable", actor),
        )
        draft2 = await catalog.create_draft(
            tool.id,
            "2",
            ToolDefinition(name="Changed", input_schema={}, domain="other", side_effect="read"),
            binding,
            actor,
        )
        assert tool.domain == "demo" and tool.name == "Lookup"
        await catalog.submit(draft2.id, actor)
        await catalog.reject(draft2.id, actor)
        await catalog.reopen(draft2.id, actor)
        await catalog.revise_draft(draft2.id, definition, binding, actor)
        grants = GrantRepository(session, next_id)
        grant = await grants.create(principal.id, "domain", "demo", actor)
        assert await grants.expand_tool_ids(principal.id) == {tool.id}
        await grants.disable(grant.id, actor)
        assert not await grants.expand_tool_ids(principal.id)
        credential_id = next_id()
        # 本次测试专用公开 dummy KEK；不读取实际运行面的 KEK。
        cipher = EnvelopeCipher(
            SecretSettings(
                keks=json.dumps({"test": base64.b64encode(b"a" * 32).decode()}),
                active_kek_id="test",
            )
        )
        ciphertext = cipher.encrypt(b"dummy-token", aad=f"credential:{credential_id}".encode())
        secrets = CredentialRepository(session, next_id)
        await secrets.store_encrypted(
            credential_id, "opaque", "bearer", ciphertext, "test", {}, actor
        )
        view = await secrets.get_by_id(credential_id)
        assert view is not None and not hasattr(view, "ciphertext")
        encrypted = await secrets.load_active_ciphertext(credential_id)
        assert "dummy-token" not in repr(encrypted)
        assert (
            cipher.decrypt(encrypted.ciphertext, aad=f"credential:{credential_id}".encode())
            == b"dummy-token"
        )
        providers = ProviderService(session, next_id)
        await providers.revise(
            provider.id, 0, base_url="https://updated.invalid", auth_ref=credential_id, actor=actor
        )
        await rejected(
            OptimisticLockError,
            lambda: providers.revise(
                provider.id,
                0,
                base_url="https://stale.invalid",
                auth_ref=credential_id,
                actor=actor,
            ),
        )
        await secrets.revoke(credential_id, actor)
        await rejected(
            InvalidDefinitionError, lambda: secrets.load_active_ciphertext(credential_id)
        )
        principal_id, tool_id, version_id, provider_id = (
            principal.id,
            tool.id,
            version.id,
            provider.id,
        )
    print("[PASS] lifecycle / projection / scopes / masked credential / revocation")
    async with factory() as session, session.begin():
        identity = IdentityService(session, next_id)
        assert (await identity.authenticate(issued.plaintext)).id == principal_id
        used_key = await session.get(ApiKey, issued.id)
        assert used_key is not None and used_key.last_used_at is not None
        await rejected(InvalidApiKeyError, lambda: identity.authenticate(issued.plaintext + "bad"))
        expired = await session.get(ApiKey, expired_id)
        assert expired is not None
        expired.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.flush()
        await rejected(InvalidApiKeyError, lambda: identity.authenticate(expiring.plaintext))
        await identity.revoke_key(issued.id, actor)
        await rejected(InvalidApiKeyError, lambda: identity.authenticate(issued.plaintext))
    print("[PASS] API Key hash / invalid / expired / revoked")
    async with factory() as session, session.begin():
        # SAVEPOINT 回滚确保冻结保护失败不会破坏外层事务。
        async def modify() -> None:
            async with session.begin_nested():
                version = await session.get(ToolVersion, version_id)
                assert version is not None
                version.name = "illegal"
                await session.flush()

        await rejected(ImmutableDefinitionError, modify)

        async def binding_modify() -> None:
            async with session.begin_nested():
                binding = await session.scalar(
                    select(ExecutionBinding).where(ExecutionBinding.version_id == version_id)
                )
                assert binding is not None
                binding.path_template = "/illegal"
                await session.flush()

        await rejected(ImmutableDefinitionError, binding_modify)
    print("[PASS] frozen version and binding")
    async with factory() as session:
        frozen_version = await session.get(ToolVersion, version_id)
        assert frozen_version is not None and frozen_version.input_schema is not None
        frozen_version.input_schema["properties"] = {"injected": {"type": "string"}}
        await rejected(ImmutableDefinitionError, session.commit)
        await session.rollback()
    async with factory() as session, session.begin():

        async def bulk_change() -> None:
            await session.execute(
                update(ToolVersion).where(ToolVersion.id == version_id).values(name="illegal bulk")
            )

        await rejected(ImmutableDefinitionError, bulk_change)
    print("[PASS] nested JSON and bulk DML cannot bypass frozen definitions")
    # 新版本先送审，然后两个真实独立连接竞争审批。
    async with factory() as session, session.begin():
        catalog = CatalogService(session, next_id)
        pending = await catalog.create_draft(
            tool_id, "3", definition, BindingDefinition(provider_id, "GET", "/lookup", {}), actor
        )
        await catalog.submit(pending.id, actor)
        pending_id = pending.id

    async def approve() -> bool:
        async with factory() as session, session.begin():
            try:
                await CatalogService(session, next_id).approve(pending_id, actor)
                return True
            except InvalidTransitionError:
                return False

    results = await asyncio.gather(approve(), approve())
    assert sorted(results) == [False, True]
    print("[PASS] concurrent approval: exactly one success (PostgreSQL row locks)")


async def run(env_file: Path) -> None:
    if not env_file.is_file():
        raise RuntimeError("explicit env file does not exist")
    url = load_database_settings(env_file).url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    schema = "th_c_selfcheck_" + uuid.uuid4().hex
    engine = create_async_engine(
        url,
        poolclass=NullPool,
        connect_args={
            "timeout": 5,
            "command_timeout": 15,
            "server_settings": {"search_path": f"{schema},public"},
        },
    )
    created = False
    try:
        async with engine.begin() as connection:
            extensions = set(
                (await connection.scalars(text("SELECT extname FROM pg_extension"))).all()
            )
            assert {"vector", "pg_trgm"} <= extensions, "required extensions unavailable"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            await connection.run_sync(migrate_and_compare, schema)
        await exercise(async_sessionmaker(engine, expire_on_commit=False, autoflush=False))
        async with engine.begin() as connection:

            def downgrade(sync_connection: Connection) -> None:
                with Operations.context(MigrationContext.configure(sync_connection)):
                    initial_migration().downgrade()
                assert not inspect(sync_connection).get_table_names(schema=schema)

            await connection.run_sync(downgrade)
        print("[PASS] downgrade removes domain tables")
    finally:
        try:
            if created:
                async with engine.begin() as connection:
                    await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.env_file.resolve()))
    except Exception as exc:
        # 网络/驱动异常可能含配置；只打印异常类型，不输出连接串或凭据。
        print(f"[FAIL] domain integration: {type(exc).__name__}")
        if isinstance(exc, AssertionError):
            print(str(exc))
        for frame in traceback.extract_tb(exc.__traceback__):
            if Path(frame.filename).name == Path(__file__).name:
                print(f"  {frame.name}:{frame.lineno}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
