"""ORM 根基：声明式 Base 与两个必备 Mixin（任务 B1 / B2 的公共依赖）。

为什么需要这个文件
------------------
:mod:`toolhive.adapters.db.repository` 是**泛型仓储**，需要一个 ``DeclarativeBase``
才能表达"某个具体模型"。模型本身由任务 C1 定义，但 Base 属于基础设施，放这里。

两个 Mixin 直接把设计 §4.1 的**两条全局约定**变成代码：

* :class:`SnowflakePrimaryKeyMixin` —— `id bigint PRIMARY KEY`，**由应用层生成雪花 ID**
  （数据库不自增、不用序列）。用 SQLAlchemy 的 ``default=`` 而不是 ``server_default=``，
  正是为了体现"值来自应用层"：数据库不会给兜底。
* :class:`AuditMixin` —— 六个审计字段在**每张表**上都有（§4.1 全局约定②）。
  做成 Mixin 而不是逐表手写，是因为"新增表时漏了审计字段"这类错误
  只有等到某次审计追溯时才会暴露——那时记录已经缺了操作人。

关于 ``*_by_name`` 的一个要点（设计 §4.1）
------------------------------------------
它是**写入时刻的名称快照**，不随账号改名而变。所以它必须是普通列，
**不能做成指向 ``principal`` 的外键**——审计字段一律不加外键：
操作人可能已离职、也可能是服务型 Principal，加 FK 会导致删号失败或历史被牵连。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import BigInteger, DateTime, Integer, String, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

__all__ = [
    "AuditMixin",
    "Base",
    "RowVersionMixin",
    "SnowflakePrimaryKeyMixin",
    "audit_snapshot",
    "bump_row_version",
]


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    ``alembic/env.py`` 的 ``target_metadata`` 将来指向 ``Base.metadata``
    （任务 C1 接线），此后 ``alembic revision --autogenerate`` 才会生效。
    """

    def __repr__(self) -> str:
        # 默认 repr 会打印所有列；模型里可能有凭据密文之类的字段。
        # 只显示主键，需要细节时显式取字段。
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


class SnowflakePrimaryKeyMixin:
    """雪花主键（设计 §4.1 全局约定① + §4.4 的位分配）。

    ``bigint`` 对应 Python ``int``；**默认值由应用层提供**，
    所以是 ``default=`` 而不是 ``server_default=``。
    """

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)


class AuditMixin:
    """六个审计字段（设计 §4.1 全局约定②）。

    全部可空——因为追加型表（``invocation`` / ``search_event`` / ``audit_log``）
    只填 ``create_*``，``update_*`` 恒为空，语义即"不可修改"。
    列仍然存在，只是不被写入；这正是"六列在每张表上都存在"的价值：
    ORM 可以用同一个 Mixin，不需要维护两套模型。
    """

    create_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: 写入时刻的名称快照，不随账号改名而变（设计 §4.1）。
    create_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: 唯一带服务端默认值的审计列：即使应用忘了传，时间也不会缺。
    create_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    update_by_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    update_by_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: **没有服务端默认值**：只有真正发生更新时才由应用显式写入。
    #: 若给它默认值，"从未被修改过"与"被改过但没记录"就分不出来了。
    update_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def touch(self, actor_id: int | None, actor_name: str | None) -> None:
        """标记一次更新：写入 ``update_*`` 三列，并**推进 ``row_version``**。

        **为什么用 Python 的 ``datetime`` 而不是 SQL 的 ``func.now()``**
        给 ORM 属性赋一个 SQL 表达式，会让 ``entity.update_time`` 在 flush 之前
        变成一个 ``Function`` 对象而不是时间——读它、写进日志、或丢给
        :func:`audit_snapshot` 都会拿到意外的类型，而且这个错要到运行时才暴露。
        设计 §4.1 说的是"只在真正更新时由**应用**显式设置"（区别于数据库触发器），
        Python 侧取当前时间正好符合这个语义，并且可测试。
        代价是依赖应用主机的时钟；若将来要求"以数据库时钟为准"，再统一改。

        **为什么同时推进 ``row_version``**
        乐观锁的令牌必须在**每次修改后变化**。若经 ORM 改完字段而版本号不动，
        别的请求拿着旧版本号仍能通过 :meth:`update_with_row_version` 的条件更新，
        那次改动就被乐观锁漏掉了。

        > 注意两者职责不同，不要混用：
        > * ``touch()`` 走 ORM 属性赋值 → 版本号**无条件**递增（后写者赢）。
        > * :meth:`Repository.update_with_row_version` 走**条件 UPDATE**
        >   （``WHERE row_version = :expected``）→ 这才是真正的并发保护。
        >   它经 Session.execute 的 ORM DML 路径执行并同步身份映射；
        >   随后的 touch() 代表另一次修改，从同步后的版本递增。
        """
        self.update_by_id = actor_id
        self.update_by_name = actor_name
        self.update_time = datetime.now(UTC)
        bump_row_version(self)

    def stamp_create(self, actor_id: int | None, actor_name: str | None) -> None:
        """写入 ``create_*`` 的操作人（时间由服务端默认值兜底）。"""
        self.create_by_id = actor_id
        self.create_by_name = actor_name


class RowVersionMixin:
    """乐观锁版本号（设计 §4.1 里多处实体带 ``row_version``）。

    为什么用乐观锁而不是悲观锁：设计 §4.3 要求"**并发 approve 只有一个成功**"
    这类语义，而 ToolHive 的写冲突**不密集**（管理面操作、低频），
    乐观锁不需要在读取时就占住数据库行锁，代价小得多。

    ⚠️ 递增**必须**通过 :meth:`toolhive.adapters.db.repository.Repository.update_with_row_version`
    里的**条件 UPDATE** 完成（``WHERE row_version = :expected``），
    而不是"读出来比一下再写回去"——后者两个请求可能同时通过比对，
    乐观锁就形同虚设。
    """

    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )


@runtime_checkable
class _Versioned(Protocol):
    """只用于"这个实体有没有 ``row_version``"的运行时判定。

    用 ``isinstance(entity, _Versioned)``（``runtime_checkable`` 的 Protocol 只检查
    属性是否存在）而不是 ``hasattr`` + ``setattr``：后者对静态检查是隐形的，
    而 ``setattr`` 传常量属性名也会被 lint 判为无谓的间接层。
    """

    row_version: int


def bump_row_version(entity: object) -> None:
    """推进 ``row_version``（实体没有这一列时静默跳过）。

    单独成函数，是为了让"哪一行推进了版本号"只有一处实现——
    分散在各处手写 ``+= 1`` 迟早会漏掉一处，而漏掉就意味着乐观锁有个洞。
    """
    if not isinstance(entity, _Versioned):
        return
    # 未加载/新对象时按 0 起算，于是首次得到 1。
    entity.row_version = (entity.row_version or 0) + 1


def audit_snapshot(entity: object) -> dict[str, Any]:
    """取一个实体的审计字段快照，便于写日志或对比。

    独立成函数是为了让"审计字段有哪些"只有一处定义——
    将来若调整字段，不必去各处找硬编码的列名。
    """
    return {
        name: getattr(entity, name, None)
        for name in (
            "create_by_id",
            "create_by_name",
            "create_time",
            "update_by_id",
            "update_by_name",
            "update_time",
        )
    }
