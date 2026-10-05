"""Redis 客户端与 Lua 脚本装载（任务 B3，设计 §7.2 / §12）。

本模块只做两件事，**不含任何业务规则**：

1. 按配置建一个可控的连接（池大小、连接超时、命令超时都可配）。
2. 把 ``scripts/*.lua`` 装载进来并执行——**原子性由 Lua 保证**。

为什么 Lua 脚本以**文件**管理而不是内联字符串
--------------------------------------------
* 内联在 Python 里没有语法高亮，也没有任何工具能检查它；
* 无法单独 review：一个 30 行的 Lua 挤在 Python 字符串里，评审时会被跳过；
* 原子性是配额与并发的正确性基础，值得让它**独立成文件、独立被看见**。

为什么时间戳由调用方传入而不是脚本内取
--------------------------------------
一次请求会经过多个阶段（配额 → 幂等 → 并发），它们**必须共享同一个时间基准**。
若各脚本自己取 ``TIME``，就会出现"配额按 T1 算、幂等按 T2 算"这类边界行为，
排查时几乎无法复现。因此统一由调用方传入 ``now_ms``。

与设计的对应
------------
* 配额 key 命名：``quota:{principal_id}:{scope_type}:{scope_value}:{window}``（§9.1）
* fail-open / fail-closed 的**分类**由策略层决定（§7.2 的矩阵），
  本模块只负责"抛得出异常"，不替调用方决定 Redis 挂了该怎么办。
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from redis.asyncio import Redis
from redis.asyncio.connection import BlockingConnectionPool
from redis.exceptions import NoScriptError

from toolhive.config import RedisSettings

__all__ = ["SCRIPTS_DIR", "ScriptRegistry", "create_client", "ping"]

_log = logging.getLogger(__name__)

#: Lua 脚本目录。与 ``pyproject.toml`` 的 package-data 声明保持一致，
#: 否则 ``pip install`` 之后脚本不会随包分发。
SCRIPTS_DIR: Final[Path] = Path(__file__).parent / "scripts"


def create_client(settings: RedisSettings) -> Redis:
    """按配置建 Redis 客户端（含连接池）。

    为什么用 **BlockingConnectionPool** 而不是默认的 ConnectionPool
    ---------------------------------------------------------------
    默认池在连接用尽时**立刻抛 ``MaxConnectionsError``，不排队**（已实测：
    ``max_connections=1`` 时并发 5 次，4 次直接报错）。后果很严重：

    * 设计 §7.2 把**幂等定为 fail-closed**（Redis 不可用 → 503）。
      ``MaxConnectionsError`` 会被当成"Redis 不可用"，于是**一波中等并发就能把平台打成 503**——
      而 Redis 其实好好的，只是连接池小。
    * 配额与并发虽是 fail-open，但会因此**静默失去限流**，等于没做。

    换成阻塞池后，连接不够时**等待**，等不到才报错。等待时长由
    ``pool_wait_timeout_seconds`` 控制，它必须**短于最紧的请求预算**——
    否则 Redis 争用会先吃掉整个延迟预算，再以一个语义不清的超时收场。

    三个超时必须显式设置：

    * ``socket_connect_timeout`` —— 连不上时**快速失败**。设计 §7.2 的分类处理
      以"能及时知道它挂了"为前提。
    * ``socket_timeout`` —— 单条命令上限；对 Lua 脚本而言是"整段脚本"的上限，
      这正是我们要的语义：脚本要么整体生效，要么整体不生效。
    * ``health_check_interval`` —— 定期探测空闲连接，避免拿到服务端已关闭的连接。
    """
    pool = BlockingConnectionPool.from_url(
        settings.url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=settings.pool_max_connections,
        timeout=settings.pool_wait_timeout_seconds,
        socket_connect_timeout=settings.connect_timeout_seconds,
        socket_timeout=settings.command_timeout_seconds,
        health_check_interval=settings.health_check_interval_seconds,
    )
    return Redis(connection_pool=pool)


async def ping(client: Redis) -> bool:
    """连通性探测。供启动自检与健康检查使用（设计 §11 的 readiness）。"""
    try:
        return bool(await client.ping())
    except Exception:
        return False


#: Redis 命令参数允许的类型。``bool`` 是 ``int`` 的子类，Lua 侧当 1/0，属有意用法。
_ALLOWED_ARG_TYPES: Final = (str, int, float, bytes)


def _validate_script_args(
    name: str,
    keys: Sequence[str],
    args: Sequence[str | int | float | bytes],
) -> None:
    """在发往 Redis **之前**校验参数。

    为什么要显式校验：``None``、``dict``、``Decimal`` 这类值会被 redis-py 一路带到
    编码阶段才炸，报错信息里既没有脚本名也没有参数位置，排查要重新读一遍调用方代码。
    在这里拦下来，错误信息可以直接指到"哪个脚本的第几个参数是什么类型"。

    ``nan`` / ``inf`` 单独拦：它们能通过 ``isinstance(x, float)``，
    但 Redis 收到 "nan" 会回一个同样难懂的错误。
    """
    for index, key in enumerate(keys):
        if not isinstance(key, str):
            raise TypeError(
                f"脚本 {name!r} 的第 {index} 个 key 必须是 str，实得 {type(key).__name__}"
            )
        if not key:
            raise ValueError(f"脚本 {name!r} 的第 {index} 个 key 是空字符串（几乎必然是 bug）")

    for index, arg in enumerate(args):
        if isinstance(arg, float) and not math.isfinite(arg):
            raise ValueError(f"脚本 {name!r} 的第 {index} 个参数是 {arg!r}，Redis 不接受")
        if not isinstance(arg, _ALLOWED_ARG_TYPES):
            raise TypeError(
                f"脚本 {name!r} 的第 {index} 个参数类型不支持：{type(arg).__name__}"
                f"（允许 str / int / float / bytes）"
            )


class ScriptRegistry:
    """装载并执行 ``scripts/`` 下的 Lua 脚本。

    用 ``EVALSHA`` 而不是每次发整段脚本：省带宽，也让命令日志可读
    （``evalsha <sha> 1 key`` 比几十行 Lua 清楚得多）。
    首次使用或 Redis 重启（sha 失效）时自动回退到 ``SCRIPT LOAD``。
    """

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = directory or SCRIPTS_DIR
        paths = sorted(self._dir.glob("*.lua"))
        if not paths:
            raise RuntimeError(
                f"{self._dir} 下没有任何 .lua 脚本 —— "
                "检查包是否装全（pyproject 的 package-data 声明）"
            )
        self._sources: dict[str, str] = {
            p.stem: p.read_text(encoding="utf-8") for p in paths
        }
        self._shas: dict[str, str] = {}

    @property
    def names(self) -> tuple[str, ...]:
        """已装载的脚本名（不含扩展名），按字典序。"""
        return tuple(sorted(self._sources))

    def source(self, name: str) -> str:
        """取脚本源码。用于评审与单测断言脚本内容。"""
        if name not in self._sources:
            raise KeyError(f"未知脚本 {name!r}；已知：{list(self.names)}")
        return self._sources[name]

    async def load_all(self, client: Redis) -> dict[str, str]:
        """把所有脚本 ``SCRIPT LOAD`` 一遍，返回 ``{name: sha}``。

        在启动时调用一次可以让后续调用少一次 ``NOSCRIPT`` 往返。
        """
        loaded: dict[str, str] = {}
        for name, source in self._sources.items():
            sha = await client.script_load(source)
            self._shas[name] = sha
            loaded[name] = sha
        _log.info(
            "lua_scripts_loaded",
            extra={"scripts": sorted(loaded), "count": len(loaded)},
        )
        return loaded

    async def run(
        self,
        client: Redis,
        name: str,
        *,
        keys: Sequence[str] = (),
        args: Sequence[str | int | float | bytes] = (),
    ) -> list[Any]:
        """执行脚本。

        参数会先经 :func:`_validate_script_args` 校验——类型不对时**在发往 Redis 之前**
        就报出"哪个脚本的第几个参数"，而不是让它烂在编码阶段。

        脚本一律返回 Lua table（在 Python 侧是 ``list``），元素是整数或字符串。
        返回类型标成 ``list[Any]``：Redis 的返回值形状由脚本决定，
        强行定死类型只会让每处调用都要 cast。
        """
        if name not in self._sources:
            raise KeyError(f"未知脚本 {name!r}；已知：{list(self.names)}")

        _validate_script_args(name, keys, args)

        sha = self._shas.get(name)
        if sha is None:
            sha = await client.script_load(self._sources[name])
            self._shas[name] = sha

        try:
            return self._as_list(
                await client.evalsha(sha, len(keys), *keys, *args)
            )
        except NoScriptError:
            # Redis 重启或 SCRIPT FLUSH 会让 sha 失效。重新装载再试一次——
            # 这比让调用方去处理"脚本没了"要合理得多。
            sha = await client.script_load(self._sources[name])
            self._shas[name] = sha
            return self._as_list(
                await client.evalsha(sha, len(keys), *keys, *args)
            )

    @staticmethod
    def _as_list(value: object) -> list[Any]:
        if isinstance(value, list):
            return value
        # 脚本只返回 table，所以走到这里说明脚本被改坏了。
        return [value]
