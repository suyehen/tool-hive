"""领域写入使用调用方事务，并以 savepoint 隔离失败的单次操作。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.core.domain.errors import DomainError
from toolhive.core.domain.guards import governance


@asynccontextmanager
async def domain_write(session: AsyncSession) -> AsyncIterator[None]:
    if not session.in_transaction():
        raise DomainError("领域写入必须由调用方开启事务")
    with governance(session.sync_session):
        async with session.begin_nested():
            yield
