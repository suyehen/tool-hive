"""PostgreSQL 连接与会话管理。"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from toolhive.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    poolclass=NullPool,  # 由 async_sessionmaker 管理会话
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
    async with async_session_factory() as session:
        yield session
