"""出站 HTTP 客户端与整体 deadline（任务 B5，设计 §10.2 / §7.2）。

本模块只负责**把请求安全、有界地发出去**。至于"这个地址能不能连"
（域名白名单、私网判定、DNS rebinding）是 SSRF 防护的职责（任务 E2，
``core/providers/ssrf.py``），不在这里——那是**业务规则**，按模块 B 的边界不归本层。

三个安全默认值，为什么一个都不能省
----------------------------------
设计 §10.2 的 ④ 明确要求：**禁重定向 · trust_env=False · verify=True**。

* ``verify=True`` —— 关掉证书校验等于把出站流量暴露给中间人；凭据就在这里注入。
* ``follow_redirects=False`` —— **这是最容易被忽略的一个**：如果允许自动跟随重定向，
  攻击者只要让一个"已被白名单放行"的地址返回 302 指向 ``169.254.169.254``
  （云元数据）或内网地址，SSRF 防护就被**从侧面绕过**了。校验发生在第一跳，
  而请求跑到了第二跳。
* ``trust_env=False`` —— 不读 ``HTTP_PROXY`` / ``NO_PROXY`` / ``.netrc``。
  否则一次环境变量注入（或一个残留的 ``.netrc``）就能把全部出站流量导向攻击者。

整体 deadline（设计 §7.2）
--------------------------
"一个整体 deadline 从入口贯穿到出站，所有阶段共享"。所以本模块**不接受**
"给我一个超时秒数"，而是接受一个 :class:`Deadline` 对象——
它从请求入口创建，一路传到这里，剩余时间被自动折算成本次调用的超时。

差别很实际：假如预算 500ms，前面已花掉 480ms，那么这里只剩 20ms；
若各阶段各自用"配置里的 10s"，整体预算就形同虚设。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

import httpx

from toolhive.config import UpstreamSettings

__all__ = [
    "Deadline",
    "DeadlineExceededError",
    "UpstreamClient",
    "create_client",
]

#: 调用方传入的 ``X-Request-ID`` 之类的头一律不转发——出站请求只带工具定义里声明的头。
#: 平台自己加的标识用这个头，便于上游侧排查。
TRACE_HEADER: Final = "X-ToolHive-Trace-Id"


class DeadlineExceededError(Exception):
    """整体 deadline 已耗尽。

    这**不是**上游的问题，而是请求自己超时了。调用方（执行内核）应当把它
    映射成超时类错误码，而**不是** ``TH_UPSTREAM_ERROR``——把自家超时报成上游故障
    会误导排查方向。
    """


@dataclass(frozen=True, slots=True)
class Deadline:
    """从请求入口创建、贯穿所有阶段的整体预算。

    记录的是**单调时钟**的时刻，因此不受系统时间调整影响——
    用 ``time.time()`` 做超时会因为 NTP 校正而忽长忽短。
    """

    expires_at: float

    @classmethod
    def in_seconds(cls, seconds: float) -> Deadline:
        """创建一个从现在起 ``seconds`` 秒后到期的 deadline。"""
        if seconds <= 0:
            raise ValueError("deadline 必须为正数")
        return cls(expires_at=time.monotonic() + seconds)

    @property
    def remaining(self) -> float:
        """剩余秒数。已耗尽时为 0 或负数。"""
        return self.expires_at - time.monotonic()

    @property
    def expired(self) -> bool:
        return self.remaining <= 0

    def ensure_alive(self) -> float:
        """返回剩余秒数；已耗尽则抛 :class:`DeadlineExceededError`。

        在**任何**可能耗时的动作之前调用它：已经超时就不该再去发起网络连接。
        """
        remaining = self.remaining
        if remaining <= 0:
            raise DeadlineExceededError(
                f"整体 deadline 已耗尽（超出 {-remaining * 1000:.0f}ms），未发起出站请求"
            )
        return remaining


def create_client(
    settings: UpstreamSettings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """按配置建出站客户端。

    ``transport`` 供 SSRF 防护（任务 E2）注入"固定已校验 IP"的自定义传输层——
    设计 §10.2 的 ③ 要求"固定已校验 IP 发起连接（杜绝 DNS rebinding）"。
    本层只留出这个口子，不实现它。
    """
    limits = httpx.Limits(
        max_connections=settings.max_connections,
        max_keepalive_connections=settings.max_keepalive_connections,
    )
    timeout = httpx.Timeout(
        connect=settings.connect_timeout_seconds,
        read=settings.read_timeout_seconds,
        write=settings.read_timeout_seconds,
        pool=settings.connect_timeout_seconds,
    )
    return httpx.AsyncClient(
        # ④ 的三个安全默认值 —— 一个都不能省，理由见模块文档
        verify=True,
        follow_redirects=False,
        trust_env=False,
        timeout=timeout,
        limits=limits,
        headers={"User-Agent": settings.user_agent},
        transport=transport,
    )


class UpstreamClient:
    """把 httpx 客户端与"整体 deadline"绑在一起的小包装。

    存在的价值只有一个：**让 deadline 无法被忘记**。
    直接暴露 ``httpx.AsyncClient`` 的话，调用方很容易写成
    ``client.get(url)``——那样用的是配置里的 10s，整体预算就白设了。
    """

    __slots__ = ("_client", "_settings")

    def __init__(self, client: httpx.AsyncClient, settings: UpstreamSettings) -> None:
        self._client = client
        self._settings = settings

    @property
    def raw(self) -> httpx.AsyncClient:
        """底层客户端。**仅供 SSRF 防护等基础设施使用**，业务代码请用 :meth:`request`。"""
        return self._client

    def effective_timeout(self, deadline: Deadline | None) -> httpx.Timeout:
        """把 deadline 的剩余时间折算成 httpx 超时。

        取**配置值与剩余时间的较小者**：配置值防止单次调用过长，
        deadline 防止整体预算被单个阶段吃光。
        """
        base_connect = self._settings.connect_timeout_seconds
        base_read = self._settings.read_timeout_seconds
        if deadline is None:
            return httpx.Timeout(
                connect=base_connect, read=base_read, write=base_read, pool=base_connect
            )

        remaining = deadline.ensure_alive()
        return httpx.Timeout(
            connect=min(base_connect, remaining),
            read=min(base_read, remaining),
            write=min(base_read, remaining),
            pool=min(base_connect, remaining),
        )

    async def request(
        self,
        method: str,
        url: str,
        *,
        deadline: Deadline | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        trace_id: str | None = None,
    ) -> httpx.Response:
        """发起一次出站请求。

        ``deadline`` 为 ``None`` 时退回配置里的超时——**仅限确实没有整体预算的场景**
        （例如后台任务）。请求路径上应当**一律**传 deadline。
        """
        timeout = self.effective_timeout(deadline)

        merged: dict[str, str] = dict(headers or {})
        if trace_id:
            # 把 trace_id 带给上游，便于跨系统串链路（设计 §11）。
            merged[TRACE_HEADER] = trace_id

        return await self._client.request(
            method,
            url,
            headers=merged or None,
            content=content,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
