"""数据库会话与事务（任务 B1）。

三条设计约束
------------
1. **``get_db()`` 不自动提交。** 提交必须是显式动作。自动提交会让"某一步失败但前面
   已经落库"变成常态，而设计的执行内核有 13 个阶段（§7.1），中途失败必须能整体回滚。
2. **``@transactional`` 支持嵌套。** 嵌套时**复用外层事务**，只有最外层提交。
   否则内层提交后外层再回滚，会留下"提交过但整体失败"的数据。
3. **``requires_new=True`` 才开独立事务。** 它用一个**全新的 session**（新连接、新事务），
   因此外层回滚**不会**撤销它。典型用途：审计落库、配额扣减这类
   "父事务失败也必须留下痕迹"的写入。

关于 PostgreSQL 不可用
----------------------
设计 §7.2 规定 **PostgreSQL 不可用时一律 fail-closed**——没有数据库就没有授权与审计，
不能放行。本模块据此**如实抛出异常**，不吞、不降级、不返回空。
把它映射成 ``TH_DEPENDENCY_UNAVAILABLE`` 是执行内核（模块 F）与 REST 前端（模块 I）的事。
"""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Concatenate, ParamSpec, TypeVar

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from toolhive.config import DatabaseSettings

__all__ = [
    "Database",
    "configure",
    "current_session",
    "get_db",
    "independent_transaction",
    "request_session",
    "require_session",
    "transactional",
]

_log = logging.getLogger(__name__)

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")
#: **请求级**事务的 session。由最外层 ``@transactional`` 或 :meth:`Database.session`
#: 设置，一路贯穿到请求结束。
#:
#: 它与下面的 ``_override_session`` **必须分开**：进入 ``requires_new`` 独立事务时，
#: 如果用同一个变量去覆盖，请求级事务的身份就被**替换**掉了——一旦恢复环节有任何闪失
#: （异常路径、任务取消、将来有人改了 reset 的位置），那个身份就永久丢失，
#: 后续代码会**静默另开一个事务**，把请求悄悄劈成两半且不留任何痕迹。
#: 两个变量让请求级事务在独立事务作用域内**始终不被触碰**。
_request_session: ContextVar[AsyncSession | None] = ContextVar(
    "toolhive_request_session", default=None
)

#: ``requires_new`` 作用域内的**临时覆盖**。只在这一层有效，退出即失效。
#: 它表示"接下来这段代码的写入属于这个独立事务"。
_override_session: ContextVar[AsyncSession | None] = ContextVar(
    "toolhive_override_session", default=None
)

#: 应用启动时通过 :func:`configure` 注入的默认 Database。
#: 用于 ``requires_new=True``（它需要 sessionmaker 才能开新 session）。
_default_database: Database | None = None


def configure(database: Database) -> None:
    """在应用启动时调用一次，注册默认 :class:`Database`。

    只在启动路径调用：此后再改它会让不同请求用不同的连接池。
    """
    global _default_database
    _default_database = database


def _require_database() -> Database:
    if _default_database is None:
        raise RuntimeError(
            "尚未配置默认 Database —— 应用启动时请调用 toolhive.adapters.db.session.configure(db)"
        )
    return _default_database


def current_session() -> AsyncSession | None:
    """当前应参与事务的 session：优先 ``requires_new`` 的临时作用域，其次是请求级事务。

    不在任何事务里时为 ``None``。
    """
    override = _override_session.get()
    return override if override is not None else _request_session.get()


def request_session() -> AsyncSession | None:
    """**请求级**事务的 session，**忽略** ``requires_new`` 的临时覆盖。

    什么时候必须用它：需要看到"请求事务里刚改过、但还没提交"的数据时。
    若误用 :func:`current_session`，在独立事务作用域内会拿到另一个连接，
    读不到那些未提交的改动——表现为"我明明改了，查出来还是旧值"。
    """
    return _request_session.get()


def require_session() -> AsyncSession:
    """取当前 session，不在事务里则抛错。

    用于那些"必须在事务内被调用"的函数——早失败比拿到 ``None`` 后踩空好。
    """
    session = current_session()
    if session is None:
        raise RuntimeError(
            "当前不在事务上下文中。请用 @transactional 包裹调用方，或显式开启 Database.session()"
        )
    return session


class Database:
    """连接池与 session 工厂的持有者。**进程内只应有一个实例**。"""

    __slots__ = ("_engine", "_sessionmaker")

    def __init__(self, engine: AsyncEngine, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._engine = engine
        self._sessionmaker = sessionmaker

    @classmethod
    def from_settings(cls, settings: DatabaseSettings) -> Database:
        """按配置建连接池。

        ``pool_size`` 取 ``pool_min``、``max_overflow`` 取
        ``pool_max - pool_min``，于是**实际上限恰好是 ``pool_max``**。
        设计文档 §2.5 提醒过：这是共享数据库，连接数要克制，不要把服务器吃满。
        """
        url = settings.url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)

        overflow = max(0, settings.pool_max - settings.pool_min)
        engine = create_async_engine(
            url,
            pool_size=settings.pool_min,
            max_overflow=overflow,
            # 连接可能被服务端或中间设备悄悄断开；pre_ping 会在取用时先探一下，
            # 避免把"连接已死"报成业务错误。
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            connect_args={
                # asyncpg 的命令超时（秒）。与库级 statement_timeout 是两道独立的闸：
                # 前者在客户端计时，后者在服务端计时。
                "command_timeout": settings.command_timeout,
                "server_settings": {"application_name": "toolhive"},
            },
        )
        return cls(
            engine,
            async_sessionmaker(
                engine,
                class_=AsyncSession,
                # 提交后不过期对象：否则每次 commit 后再读属性都会触发一次隐式查询，
                # 在异步上下文里这种隐式 IO 会以意外的形式暴露出来。
                expire_on_commit=False,
                autoflush=False,
            ),
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sessionmaker

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """开一个 **不自动提交** 的会话。退出时若仍有未提交的改动则回滚。

        若当前**还没有**请求级事务，它会把这次会话登记为请求级事务——
        这样在其中调用 ``@transactional`` 服务函数会**加入**它，
        而不是另开一个连接和新事务。否则会出现"路由里改的数据，
        服务函数看不见（因为它连的是另一个连接）"这类难查的问题。

        ``autoflush=False``：设计里"先查后改"的模式很多（例如乐观锁），
        自动 flush 会在查询前把半成品写出去，掩盖真正的顺序问题。
        """
        session = self._sessionmaker()
        token = None
        if _request_session.get() is None:
            token = _request_session.set(session)
        try:
            yield session
        finally:
            if token is not None:
                _request_session.reset(token)
            await session.close()

    async def ping(self) -> bool:
        """连通性探测（供启动自检与 readiness 使用，设计 §11）。"""
        from sqlalchemy import text

        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            _log.warning("database_ping_failed", exc_info=True)
            return False

    async def dispose(self) -> None:
        """关闭连接池。应用停机时调用。"""
        await self._engine.dispose()


async def get_db(database: Database | None = None) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：产出一个**不自动提交**的会话。

    ⚠️ **刻意不在这里提交**。路由处理函数要么显式 ``await session.commit()``，
    要么调用被 ``@transactional`` 包裹的服务函数。这样"提交"永远是一个
    能被看见的动作，而不是藏在依赖清理里的副作用。
    """
    db = database or _require_database()
    async with db.session() as session:
        yield session


def _wrap(
    fn: Callable[Concatenate[AsyncSession, P], Awaitable[R]], *, requires_new: bool
) -> Callable[P, Awaitable[R]]:
    """两个装饰器的共同实现。**不要直接用它**——用有类型标注的那两个入口。"""
    params = list(inspect.signature(fn).parameters)
    if not params or params[0] != "session":
        name = "@independent_transaction" if requires_new else "@transactional"
        raise TypeError(
            f"{fn.__qualname__} 的第一个参数必须命名为 session（{name} 要注入它）"
        )

    @functools.wraps(fn)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        if "session" in kwargs:
            raise TypeError(f"{fn.__qualname__} 的 session 由装饰器注入，调用方不要传")

        # --- 独立事务：只设临时覆盖，**绝不触碰**请求级事务的身份 ---
        if requires_new:
            session = _require_database().sessionmaker()
            token = _override_session.set(session)
            try:
                result = await fn(session, *args, **kwargs)
                await session.commit()
                return result
            except BaseException:
                await session.rollback()
                raise
            finally:
                _override_session.reset(token)
                await session.close()

        # --- 加入已有事务（独立事务作用域内的调用也归到那里）---
        existing = current_session()
        if existing is not None:
            return await fn(existing, *args, **kwargs)

        # --- 最外层：开启请求级事务 ---
        session = _require_database().sessionmaker()
        token = _request_session.set(session)
        try:
            result = await fn(session, *args, **kwargs)
            await session.commit()
            return result
        except BaseException:
            # 含 CancelledError：协程被取消时也必须回滚，否则连接会被
            # 带着未结束的事务还回连接池。
            await session.rollback()
            raise
        finally:
            _request_session.reset(token)
            await session.close()

    return wrapper


def transactional(
    fn: Callable[Concatenate[AsyncSession, P], Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """把函数包进**请求级**事务。用法::

        @transactional
        async def approve(session: AsyncSession, version_id: int) -> None:
            ...
        await approve(version_id=42)      # session 由装饰器注入

    被装饰函数的**第一个参数必须命名为 ``session``**，由装饰器注入；
    调用方**不要**自己传它，其余参数照常传（位置或关键字都行）。

    嵌套语义
    --------
    若外层已有事务，**复用同一个 session**：既不提交也不回滚，
    由最外层统一决定。这是"要么全成、要么全败"该有的样子。

    > 需要"父事务失败也要留下痕迹"的写入（审计、配额），请用
    > :func:`independent_transaction`，**不要**试图用参数开关来切换——
    > 那会让签名退化成一个 union，类型检查器再也推断不出装饰后的函数类型。
    """
    return _wrap(fn, requires_new=False)


def independent_transaction(
    fn: Callable[Concatenate[AsyncSession, P], Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """把函数包进**独立**事务：新开一个 session（新连接、新事务），自己提交。

    外层的回滚**不会**影响它。用于审计落库、配额扣减这类
    "父事务失败也必须留下痕迹"的写入::

        @independent_transaction
        async def record_audit(session: AsyncSession, entry: AuditEntry) -> None:
            ...

    ⚠️ 它多占一个数据库连接，在连接池紧张时可能等待——这是"独立提交"必须付的代价。

    > **为什么单独一个装饰器，而不是 ``@transactional(requires_new=True)``**：
    > 要同时支持"裸装饰器"和"带参数调用"两种形态，返回类型就必须写成
    > ``Callable | Callable[[Callable], Callable]`` 这样的 union，
    > 于是 **mypy 再也推断不出装饰后的函数签名**——在这个全程类型化的代码库里，
    > 被装饰的函数会退化成"参数与返回值都不可知"，得不偿失。
    > 拆成两个入口后，两者都能用 ``ParamSpec`` 完整保留原签名。
    """
    return _wrap(fn, requires_new=True)
