"""仓储基类（任务 B2）。

三个能力，对应三种并发/定位需求
--------------------------------
======================  ==============================================================
能力                     解决什么问题
======================  ==============================================================
:meth:`get_by_id`       按主键读。最常用，**不加锁**。
:meth:`get_for_update`  按主键读并**行锁**（``SELECT ... FOR UPDATE``）。
                        用于"读—判断—写"必须原子完成的场景，例如设计 §4.3 要求
                        "并发 approve 只有一个成功"。
:meth:`update_with_row_version`  **乐观锁**条件更新。用于跨事务的并发保护：
                        两个请求都读到 ``row_version=3``，只有一个能改成 4。
======================  ==============================================================

一个必须讲清楚的陷阱
--------------------
乐观锁**必须**用条件 UPDATE 实现::

    UPDATE t SET ..., row_version = 4 WHERE id = ? AND row_version = 3

而不能写成"读出来 → Python 里比一下 → 写回去"。后者在两次操作之间没有原子性：
两个请求可能都读到 3、都比对通过、都写回 4，**乐观锁就白加了**。
所以本模块只提供条件更新这一条路径，不提供"检查后保存"的便捷方法。

本模块**不含业务规则**（模块 B 的边界）：不知道什么状态能改、谁有权改，
只负责"按主键读"、"加锁读"、"带版本号地写"。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Generic, TypeVar, cast

from sqlalchemy import CursorResult, Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from toolhive.adapters.db.base import Base

__all__ = [
    "EntityNotFoundError",
    "OptimisticLockError",
    "Repository",
    "RepositoryError",
    "UnflushedChangesError",
]

_log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=Base)


class RepositoryError(Exception):
    """仓储异常的共同基类，调用方可在仓储边界统一捕获。"""


class UnflushedChangesError(RepositoryError):
    """读取刷新或条件更新会覆盖当前对象的未 flush 修改。"""

    def __init__(self, model: str, entity_id: int) -> None:
        self.model = model
        self.entity_id = entity_id
        super().__init__(f"{model} id={entity_id} 存在未 flush 修改，请先明确保存或撤销")


class EntityNotFoundError(RepositoryError, LookupError):
    """按主键查不到实体。

    注意：**不要把这个异常直接透给调用方**。设计 §9.3 的"不可区分原则"要求
    "工具不存在 / 无权 / 已停用 / 无已发布版本"返回**完全相同**的结果；
    把"查不到"与"无权"区分开就会泄露信息。映射由模块 D/I 负责。
    """

    def __init__(self, model: str, entity_id: object) -> None:
        super().__init__(f"{model} 不存在：id={entity_id}")
        self.model = model
        self.entity_id = entity_id


class OptimisticLockError(RepositoryError, RuntimeError):
    """乐观锁冲突：``row_version`` 已被别的请求改掉。

    这是**正常的并发结果**，不是系统故障。调用方应当把它映射成
    "版本冲突，请重试"这类可重试语义，而不是 500。
    """

    def __init__(self, model: str, entity_id: object, expected: int) -> None:
        super().__init__(
            f"{model} id={entity_id} 的 row_version 已不是 {expected} —— "
            "该记录已被并发修改，请重新读取后再试"
        )
        self.model = model
        self.entity_id = entity_id
        self.expected = expected


class Repository(Generic[ModelT]):
    """泛型仓储基类。子类只需声明 ``model``。"""

    #: 子类必须指定具体模型。
    model: ClassVar[type[Any]]

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @property
    def session(self) -> AsyncSession:
        return self._session

    @property
    def _model_name(self) -> str:
        return getattr(self.model, "__name__", str(self.model))

    # -- 读 -----------------------------------------------------------------

    def _select(self) -> Select[Any]:
        return select(self.model)

    def _ensure_clean(self, entity_ids: Sequence[int]) -> None:
        """刷新前保护本地修改，避免 autoflush=False 时静默覆盖。"""
        ids = set(entity_ids)
        for entity in self._session.dirty:
            if isinstance(entity, self.model):
                entity_id = getattr(entity, "id", None)
                if entity_id in ids:
                    raise UnflushedChangesError(self._model_name, entity_id)

    async def get_by_id(self, entity_id: int) -> ModelT | None:
        """按主键读并刷新已加载属性，**不加锁**。

        返回数据库在当前事务隔离级别下可见的状态。存在未 flush 修改时拒绝覆盖。
        """
        self._ensure_clean([entity_id])
        result = await self._session.execute(
            self._select().where(self.model.id == entity_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, entity_id: int) -> ModelT | None:
        """按主键读并加**行锁**（``SELECT ... FOR UPDATE``）。

        ⚠️ 必须在事务内使用：没有事务时 ``FOR UPDATE`` 拿到的锁会在语句结束即释放，
        等于没加锁。设计 §4.3 的"并发 approve 只有一个成功"就依赖这个锁。
        刷新会覆盖已加载属性，调用前不要保留该对象的未 flush 修改。
        """
        self._ensure_clean([entity_id])
        result = await self._session.execute(
            self._select().where(self.model.id == entity_id).with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def require(self, entity_id: int) -> ModelT:
        """按主键读，查不到抛 :class:`EntityNotFoundError`。"""
        entity = await self.get_by_id(entity_id)
        if entity is None:
            raise EntityNotFoundError(self._model_name, entity_id)
        return entity

    async def require_for_update(self, entity_id: int) -> ModelT:
        """加锁读，查不到抛错。"""
        entity = await self.get_for_update(entity_id)
        if entity is None:
            raise EntityNotFoundError(self._model_name, entity_id)
        return entity

    async def list_by_ids(self, entity_ids: Sequence[int]) -> list[ModelT]:
        """按一批主键读取并刷新；同样保护未 flush 修改。空列表不查询。"""
        if not entity_ids:
            return []
        self._ensure_clean(entity_ids)
        result = await self._session.execute(
            self._select().where(self.model.id.in_(entity_ids))
            .execution_options(populate_existing=True)
        )
        return list(result.scalars().all())

    async def exists(self, entity_id: int) -> bool:
        result = await self._session.execute(
            select(self.model.id).where(self.model.id == entity_id).limit(1)
        )
        return result.scalar_one_or_none() is not None

    # -- 写 -----------------------------------------------------------------

    async def add(self, entity: ModelT) -> ModelT:
        """加入会话。**不提交**——提交由事务边界决定（任务 B1）。"""
        self._session.add(entity)
        await self._session.flush()
        return entity

    async def delete_by_id(self, entity_id: int) -> bool:
        """按主键删除，返回是否真的删掉了一行。"""
        result = await self._session.execute(
            delete(self.model).where(self.model.id == entity_id)
        )
        return _rowcount(result) > 0

    async def refresh(self, entity: ModelT) -> ModelT:
        """从库里重新读一遍实体（覆盖本地未提交的改动）。

        用于拿到加锁后的最新值，或在乐观锁冲突后重新同步。
        """
        await self._session.refresh(entity)
        return entity

    # -- 乐观锁 -------------------------------------------------------------

    def ensure_row_version(self, entity: ModelT, expected: int) -> None:
        """比对本地实体的 ``row_version``，不一致即抛错。

        这是**廉价的预检**，不能替代真正的并发保护——它只是让"明显过期"的请求
        早点失败，不用白跑一次 UPDATE。真正的保护在
        :meth:`update_with_row_version` 的条件 UPDATE 里。
        """
        actual = getattr(entity, "row_version", None)
        if actual != expected:
            raise OptimisticLockError(self._model_name, getattr(entity, "id", None), expected)

    async def update_with_row_version(
        self,
        entity_id: int,
        *,
        expected_row_version: int,
        values: Mapping[str, Any],
    ) -> int:
        """**乐观锁条件更新**，返回新的 ``row_version``。

        生成的 SQL 是::

            UPDATE t SET <values>, row_version = expected+1
            WHERE id = :id AND row_version = :expected

        ``rowcount != 1`` 意味着期间有别人改过（或记录被删），此时抛
        :class:`OptimisticLockError`。**必须检查 rowcount**——
        不检查的话 UPDATE 影响 0 行也会"成功返回"，冲突被静默吞掉。
        显式 fetch 同步身份映射，使已加载对象的字段/版本同步更新；
        后续 touch() 从新版本递增。它不替代 ORM 修改路径自己的并发保护。
        """
        self._ensure_clean([entity_id])
        new_version = expected_row_version + 1
        statement = (
            update(self.model)
            .where(
                self.model.id == entity_id,
                self.model.row_version == expected_row_version,
            )
            .values(row_version=new_version, **dict(values))
            .execution_options(synchronize_session="fetch")
        )
        result = await self._session.execute(statement)
        if _rowcount(result) != 1:
            raise OptimisticLockError(self._model_name, entity_id, expected_row_version)
        return new_version


def _rowcount(result: object) -> int:
    """取受影响行数。

    ``AsyncSession.execute`` 的静态返回类型是 ``Result``，而实际返回的是
    ``CursorResult``（只有它带 ``rowcount``）。这里收口一次，避免每处都 cast。

    **必须检查行数**：乐观锁的 UPDATE 若匹配 0 行，不检查就会被当成成功，
    冲突被静默吞掉——那正是乐观锁失效最常见的方式。
    """
    return int(cast("CursorResult[Any]", result).rowcount or 0)
