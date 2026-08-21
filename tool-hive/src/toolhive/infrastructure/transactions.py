"""统一事务管理。

业务写操作由 Application Service 通过 ``@transactional`` 声明事务边界：

- 方法正常结束自动 ``commit``，抛出异常自动 ``rollback``；
- 内部调用默认加入当前事务，只有最外层事务边界执行提交或回滚；
- ``requires_new=True`` 时使用独立 session 提交，不影响外层请求事务，
  用于登录失败计数等"请求最终失败也必须保留"的安全数据。
"""

from __future__ import annotations

import contextvars
import functools
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.infrastructure.database import async_session_factory

_TX_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar(
    "toolhive_tx_depth", default=0
)

_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


def transactional(*, requires_new: bool = False) -> Callable[[_F], _F]:
    """声明异步 Service 方法为数据库事务边界。

    装饰器从方法所属实例（``self.db``）获取当前 session。
    """

    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            db: AsyncSession | None = getattr(self, "db", None)
            if db is None:
                return await func(self, *args, **kwargs)

            depth = _TX_DEPTH.get()

            if requires_new:
                # 独立事务：临时替换 self.db 为独立 session
                original_db: AsyncSession = db
                async with async_session_factory() as new_db:
                    self.db = new_db
                    token = _TX_DEPTH.set(1)
                    try:
                        result = await func(self, *args, **kwargs)
                        await new_db.commit()
                        return result
                    except BaseException:
                        await new_db.rollback()
                        raise
                    finally:
                        _TX_DEPTH.reset(token)
                        self.db = original_db

            if depth == 0:
                token = _TX_DEPTH.set(1)
                try:
                    result = await func(self, *args, **kwargs)
                    await db.commit()
                    return result
                except BaseException:
                    await db.rollback()
                    raise
                finally:
                    _TX_DEPTH.reset(token)

            # 已处于外层事务中：加入当前事务，不重复提交
            return await func(self, *args, **kwargs)

        return cast(_F, wrapper)

    return decorator
