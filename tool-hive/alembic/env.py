"""Alembic 异步迁移环境。"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import create_async_engine

# 导入模型以注册全部表元数据，供后续 autogenerate 使用
import toolhive.models  # noqa: F401
from alembic import context
from toolhive.config import load_settings, settings
from toolhive.models.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _configure(connection) -> None:
    """按目标数据库配置 Alembic 上下文。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )


def _run_offline() -> None:
    """离线模式仅输出 SQL，不建立真实连接。"""
    load_settings()
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    """在线模式使用应用配置中的异步数据库 URL 执行迁移。"""
    load_settings()
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as connection:
        await connection.run_sync(_configure)
        async with connection.begin():
            await connection.run_sync(lambda sync_conn: context.run_migrations())
    await engine.dispose()


def run_migrations_offline() -> None:
    """Alembic CLI 离线入口。"""
    _run_offline()


def run_migrations_online() -> None:
    """Alembic CLI 在线入口。"""
    asyncio.run(_run_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
