"""Alembic 运行环境（任务 A4）。

两个刻意的设计选择
------------------

**1. 连接串只有一个来源。**
``alembic.ini`` 里不写 ``sqlalchemy.url``；这里从 :func:`toolhive.config.load_settings`
读取 ``TOOLHIVE_DATABASE_URL``。否则迁移连的库和应用连的库可能不是同一个。

**2. 用异步驱动，不额外引入 psycopg2。**
项目本来就用 ``asyncpg``，再为迁移装一个同步驱动是多余的。
``asyncpg`` 需要 ``postgresql+asyncpg://`` 前缀，这里负责转换。

``target_metadata`` 目前是 ``None``：ORM ``Base`` 由任务 C1 建立，届时在此 import 并赋值，
``alembic revision --autogenerate`` 才会生效。M0 的首个迁移由 C1 依据
``docs/03-表结构DDL-v0.2.md`` 转写（该文档是 M0 的建表交付物）。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from toolhive.config import load_settings

# Alembic 的 Config 对象，提供对 alembic.ini 的访问。
config = context.config

# 本项目的日志是 JSON 结构化的（设计 §11），因此**不调用 fileConfig**——
# 那会用 alembic.ini 的 logging 段覆盖全局日志配置，把 JSON 输出换成纯文本。
_ = fileConfig

# ORM 元数据。任务 C1 建立 Base 后改为 import 并赋值。
# 例：from toolhive.adapters.db.base import Base; target_metadata = Base.metadata
target_metadata = None


def _database_url() -> str:
    """从应用配置取连接串，并转换成 asyncpg 可用的形式。"""
    settings = load_settings()
    url = settings.database.url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连数据库（``alembic upgrade head --sql``）。"""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """在线模式：用异步引擎连库并执行迁移。"""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    import asyncio

    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
