"""PostgreSQL 连接与会话管理。

连接在应用启动阶段通过 ``init_infrastructure`` 显式初始化，
模块导入时不建立数据库连接。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from toolhive.config import InfrastructureSettings

engine = None
async_session_factory = None


def init_infrastructure(
    infrastructure: InfrastructureSettings, debug: bool = False,
) -> None:
    """启动阶段初始化数据库连接与会话工厂。"""
    global engine, async_session_factory
    engine = create_async_engine(
        infrastructure.database_url,
        echo=debug,
        poolclass=NullPool,
    )
    async_session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入用：每次请求提供一个数据库会话。

    只注入会话，不负责提交或回滚；事务边界由 Service 写方法通过
    ``@transactional`` 声明。
    """
    if async_session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_infrastructure()")
    async with async_session_factory() as session:
        yield session
