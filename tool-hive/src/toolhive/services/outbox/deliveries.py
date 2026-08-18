"""Outbox 投递目标实现。

每个投递目标独立执行、独立重试；当前一期没有业务事件源，
redis/chroma 投递为骨架实现，具体投递规则随业务事件接入。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from toolhive.models.outbox_event import OutboxEvent

logger = logging.getLogger(__name__)


class DeliveryError(Exception):
    """可重试的投递失败（网络、临时不可用等）。"""


class DeterministicDeliveryError(Exception):
    """确定性投递错误（未知目标、未知事件类型等），有限重试后进入 DEAD。"""


class DeliveryTarget(ABC):
    """投递目标接口。"""

    name: str

    @abstractmethod
    async def deliver(self, event: OutboxEvent) -> None:
        """执行投递；失败抛出 ``DeliveryError`` 或 ``DeterministicDeliveryError``。"""


class RedisCacheDelivery(DeliveryTarget):
    """Redis 普通缓存失效投递。

    普通缓存失效使用可重复的删除操作；具体失效 key 规则随业务事件接入。
    """

    name = "redis"

    async def deliver(self, event: OutboxEvent) -> None:
        logger.info("outbox delivery target=redis event=%s", event.event_id)


class ChromaIndexDelivery(DeliveryTarget):
    """Chroma 派生索引投递。

    所有 Chroma 写入只允许通过本投递执行；检索实现在一期下半接入
    ``VectorIndex`` 后按稳定业务 ID 执行 upsert/delete。
    """

    name = "chroma"

    async def deliver(self, event: OutboxEvent) -> None:
        logger.info("outbox delivery target=chroma event=%s", event.event_id)


TARGETS: dict[str, DeliveryTarget] = {
    target.name: target
    for target in (RedisCacheDelivery(), ChromaIndexDelivery())
}
